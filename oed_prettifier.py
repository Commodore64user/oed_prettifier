import argparse
import os
import sys
import time
import shutil
import itertools
import subprocess
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from pyglossary.glossary_v2 import Glossary
from processing_worker import process_entry_line_worker
from concurrent.futures import as_completed

class DictionaryConverter:
    """Orchestrates the conversion from a TSV file to a Stardict dictionary."""
    def __init__(self, input_tsv: Path, output_ifo: str, add_syns: bool, workers: int | None, debug_words: list[str] | None):
        if not input_tsv.is_file():
            sys.exit(f"Error: Input TSV file not found at '{input_tsv}'")
        self.input_tsv = input_tsv
        self.output_ifo_name = output_ifo
        self.add_syns = add_syns
        self.debug_words = set(debug_words) if debug_words else None

        if self.debug_words:
            self.workers = 1
        elif workers is not None:
            self.workers = max(1, min(workers, os.cpu_count() or 1))
        else:
            self.workers = max(1, (os.cpu_count() or 1) - 1)

        self.start_time = time.time()
        self.metrics = {
            'source_entry_count': 0, 'split_entry_count': 0, 'final_entry_count': 0,
            'malformed_lines': 0, 'dotted_words': 0, 'dot_corrected': 0,
            'synonyms_added_count': 0, 'total_entries': 0
        }
        self.processing_errors = []
        self.unique_headwords = set()
        Glossary.init()
        self.glos = Glossary()

    def _create_entry(self, all_words: list[str], final_definition: str):
        """Helper function to create a glossary entry from processed data."""
        main_headword = all_words[0]
        other_words = set(all_words[1:])
        other_words.discard(main_headword)
        sorted_words = [main_headword] + sorted(list(other_words))

        entry = self.glos.newEntry(word=sorted_words, defi=final_definition, defiFormat='h')
        self.glos.addEntry(entry)
        self.metrics['final_entry_count'] += 1

    def run(self):
        """Reads a TSV file, processes entries in parallel, and prepares the glossary."""
        if self.debug_words:
            print(f"--> Running in DEBUG mode for headword(s): {', '.join(sorted(self.debug_words))}")
        label = "process" if self.workers == 1 else "processes"
        print(f"--> Using {self.workers} worker {label}.")
        print(f"--> Reading and processing '{self.input_tsv}'...")

        try:
            with open(self.input_tsv, 'r', encoding='utf-8') as f:
                all_lines = []
                for line in f:
                    stripped_line = line.strip()
                    if not stripped_line:
                        continue
                    if stripped_line.startswith('##'):
                        self._process_metadata_line(stripped_line)
                    else:
                        if self.debug_words:
                            word = stripped_line.split('\t', 1)[0]
                            if word in self.debug_words:
                                all_lines.append(stripped_line)
                        else:
                            all_lines.append(stripped_line)

                if self.metrics['total_entries'] == 0:
                    self.metrics['total_entries'] = len(all_lines)

            # Package lines with the add_syns flag for the workers
            tasks = [(line, self.add_syns) for line in all_lines]
            completed_count = 0
            spinner = itertools.cycle(['▁', '▂', '▃', '▄', '▅', '▆', '▇', '█', '▇', '▆', '▅', '▄', '▃', '▂'])

            print("--> Submitting tasks to workers... this might take a few seconds.")

            with ProcessPoolExecutor(max_workers=self.workers) as executor:
                # Submit all tasks at once and get a dictionary of future-to-task mappings
                futures = {executor.submit(process_entry_line_worker, task): task for task in tasks}

                # Start the line for the spinner/progress
                print("--> Processing: ", end='', flush=True)

                # Process results as they are completed
                for future in as_completed(futures):
                    try:
                        result = future.result()
                        # --- Existing result processing logic starts here ---
                        if result['status'] == 'ok':
                            for res in result['results']:
                                self._create_entry(res['words'], res['definition'])
                                self.unique_headwords.add(res['words'][0])

                            m = result['metrics']
                            self.metrics['source_entry_count'] += m['source_entry']
                            self.metrics['split_entry_count'] += m['split_entry']
                            self.metrics['dotted_words'] += m['dotted_words']
                            self.metrics['dot_corrected'] += m['dot_corrected']
                            self.metrics['synonyms_added_count'] += m['synonyms_added']

                        elif result['type'] == 'malformed_line':
                            self.metrics['malformed_lines'] += 1
                        elif result['type'] == 'processing_error':
                            self.processing_errors.append(result)
                    except Exception as e:
                        # Handle potential errors from the worker process itself
                        original_task_line = futures[future][0] # Get the line from the original task
                        self.processing_errors.append({
                            'status': 'error',
                            'type': 'future_error',
                            'line': original_task_line[:100] + "...",
                            'error': str(e)
                        })

                    completed_count += 1

                    # Update progress bar and spinner, but throttle it to avoid excessive printing,
                    # modulo 97 (prime number), provides a good distributed and periodic progress feedback to users.
                    if completed_count % 97 == 0 or completed_count == len(tasks):
                        percent = (completed_count / len(tasks)) * 100
                        print(f"\r--> Processing: {next(spinner)} {completed_count:,}/{len(tasks):,} ({percent:.1f}%)", end='', flush=True)

            # Clear the progress line before printing the final summary
            print("\r" + " " * 80, end='\r')

            print("\n--> Processing complete. Writing Stardict files...")
            self._write_output()
            self._print_summary()
        except Exception as e:
            sys.exit(f"An unexpected error occurred: {e}")
        finally:
            self._cleanup()

    def _process_metadata_line(self, line: str):
        """Parses a metadata line and updates the glossary info."""
        meta_parts = line.lstrip('#').strip().split('\t', 1)
        if len(meta_parts) == 2:
            key, value = meta_parts
            if key.strip() == 'wordcount' and not self.debug_words:
                try:
                    self.metrics['total_entries'] = int(value.strip())
                except ValueError:
                    pass
            print(f"    - Found metadata: '{key.strip()}' = '{value.strip()}'")
            self.glos.setInfo(key.strip(), value.strip())

    def _write_output(self):
        """Writes the final Stardict files, including CSS and .syn handling."""
        output_dir = Path(self.output_ifo_name)
        output_dir.mkdir(parents=True, exist_ok=True)

        # And back to Stradict we go!
        if self.debug_words:
            self.glos.setInfo("title", "debug OED")
        self.glos.setInfo("description", "This dictionary was created using Commodore64user's oed_prettifier, if you encounter any formatting issues, do not hesitate to report them" \
                    " in the GitHub repo. Happy reading!")
        self.glos.setInfo("date", time.strftime("%Y-%m-%d"))
        script_dir = Path(__file__).resolve().parent
        css_path = script_dir / 'style.css'
        if css_path.is_file():
            try:
                with open(css_path, 'rb') as f_css:
                    css_content = f_css.read()

                    # Create a data entry for the stylesheet
                    css_entry = self.glos.newDataEntry(f"../{self.output_ifo_name}.css", css_content)
                    self.glos.addEntry(css_entry)
                    print(f"--> Attached stylesheet: '{css_path}'")
            except Exception as e:
                print(f"--> Warning: Could not read or add CSS file '{css_path}'. Error: {e}")
        else:
            print("--> No 'style.css' file found in the source directory. Skipping.")
        try:
            output_base_path = output_dir / Path(self.output_ifo_name).name
            if self.add_syns:
                self.glos.write(str(output_base_path), formatName="Stardict", dictzip=True)
            else: # don't create a syn file for the 1000-ish abbreviations we're adding.
                self.glos.write(str(output_base_path), formatName="StardictMergeSyns", dictzip=True)
            time.sleep(2)  # Ensure the file is written before proceeding
            syn_dz_path = output_base_path.with_suffix('.syn.dz')
            if syn_dz_path.is_file():
                print(f"--> Decompressing '{syn_dz_path}'...")
                subprocess.run(f"dictzip -d \"{syn_dz_path}\"", shell=True, check=True)
        except Exception as e:
            sys.exit(f"An error occurred during the write process: {e}")

    def _cleanup(self):
        """Performs final cleanup of temporary files and directories."""
        print("\nPerforming final cleanup...")
        pycache_dir = "__pycache__"
        if os.path.exists(pycache_dir) and os.path.isdir(pycache_dir):
            try:
                shutil.rmtree(pycache_dir)
                print(f"Successfully removed {pycache_dir} directory.")
            except OSError as e:
                print(f"Error cleaning up {pycache_dir}: {e}")
        else:
            print("No __pycache__ directory found to clean.")

    def _print_summary(self):
        """Prints the final metrics and summary of the conversion process."""
        end_time = time.time()
        duration = end_time - self.start_time
        minutes, seconds = divmod(duration, 60)

        print("\n----------------------------------------------------")
        print(f"Process complete. New dictionary '{self.output_ifo_name}.ifo' created.")
        print("----------------------------------------------------")
        print("Metrics:")
        print(f"- Entries read from source TSV:     {self.metrics['source_entry_count']:,}")
        print(f"- Entries with homographs split:    {self.metrics['split_entry_count']:,}")
        print(f"- Unique headwords processed:       {len(self.unique_headwords):,}")
        print(f"- Malformed lines skipped:          {self.metrics['malformed_lines']:,}")
        if self.processing_errors:
            print(f"- Unexpected processing errors:     {len(self.processing_errors):,}")
        if self.add_syns:
            print(f"- Synonyms added from b-tags:       {self.metrics['synonyms_added_count']:,}")
        print(f"- Words ending in full stops found: {self.metrics['dotted_words']:,}")
        print(f"- Full stops corrected:             {self.metrics['dot_corrected']:,}")
        print(f"- Total final entries written:      {self.metrics['final_entry_count']:,}")
        print(f"- Total execution time:             {int(minutes):02d}:{int(seconds):02d}")
        print("----------------------------------------------------\n")
        if self.processing_errors:
            print("\nEncountered processing errors on the following lines:")
            for err in self.processing_errors[:20]: # Show first 20 errors
                print(f"  - Error: {err['error']}\n    Line:  {err['line'][:100]}...")
            if len(self.processing_errors) > 20:
                print(f"  ... and {len(self.processing_errors) - 20} more.")
        print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Reads a TSV dictionary, preserves metadata, splits homographs, cleans HTML, and writes a Stardict file.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("input_tsv", type=Path, help="Path to the source .tsv file.")
    parser.add_argument("output_ifo", type=str, help="Base name for the new output Stardict files (e.g., 'OED_2ed').")
    parser.add_argument("--add-syns", action="store_true", help="Scan HTML for b-tags and add their cleaned content as synonyms for the entry.")
    parser.add_argument("--workers", type=int, default=None, help="Number of worker processes to use. Defaults to the number of system cores minus one.")
    parser.add_argument("--debug", nargs='+', help="Run the script only for the specified headword(s) to speed up testing.")
    args = parser.parse_args()

    converter = DictionaryConverter(args.input_tsv, args.output_ifo, args.add_syns, args.workers, args.debug)
    converter.run()

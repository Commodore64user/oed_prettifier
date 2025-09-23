import argparse
import re
import os
import sys
import time
import shutil
import subprocess
from pathlib import Path
from pyglossary.glossary_v2 import Glossary
from pyglossary.entry import Entry
from entry_processor import EntryProcessor
from synonym_extractor import SynonymExtractor

class DictionaryConverter:
    """Orchestrates the conversion from a TSV file to a Stardict dictionary."""
    CORE_HOMOGRAPH_PATTERN = r'<b><span style="color:#8B008B">▪ <span>[IVXL]+\.</span></span></b>'

    def __init__(self, input_tsv: Path, output_ifo: str, add_syns: bool, debug_words: list[str] | None):
        if not input_tsv.is_file():
            sys.exit(f"Error: Input TSV file not found at '{input_tsv}'")
        self.input_tsv = input_tsv
        self.output_ifo_name = output_ifo
        self.add_syns = add_syns
        self.start_time = time.time()
        self.metrics = {
            'source_entry_count': 0, 'split_entry_count': 0, 'final_entry_count': 0,
            'malformed_lines': 0, 'dotted_words': 0, 'dot_corrected': 0,
            'synonyms_added_count': 0, 'total_entries': 0
        }
        self.unique_headwords = set()
        self.debug_words = set(debug_words) if debug_words else None
        Glossary.init()
        self.glos = Glossary()
        self.homograph_pattern = re.compile(f'(?={self.CORE_HOMOGRAPH_PATTERN})')

    def _create_entry(self, entry_word, final_definition):
        """Helper function to handle synonym extraction and entry creation."""
        source_words = list(entry_word) if isinstance(entry_word, list) else [entry_word]

        # Only extract and add synonyms if the flag is set
        synonyms_added = 0
        if self.add_syns:
            # Ensure we pass a string headword (not a list) to extract_synonyms to avoid .strip() on a list
            synonyms = SynonymExtractor.extract(source_words[0], final_definition)
            if synonyms:
                if self.debug_words:
                    sorted_syns = sorted(synonyms, key=lambda s: (len(s), s))
                    print(f"--> Synonyms for '{entry_word}': {'; '.join(sorted_syns)}")
                source_words.extend(synonyms)
                original_word_count = len(entry_word) if isinstance(entry_word, list) else 1
                synonyms_added = len(source_words) - original_word_count

        main_headword = source_words[0]
        other_words = set(source_words[1:])
        other_words.discard(main_headword)
        all_words = [main_headword] + sorted(list(other_words))

        entry = Entry(word=all_words, defi=final_definition, defiFormat='h')
        self.glos.addEntry(entry)

        self.metrics['synonyms_added_count'] += synonyms_added
        self.metrics['final_entry_count'] += 1


    def run(self):
        """Reads a TSV file, splits homographs, processes the HTML of each part,
        and prepares the glossary for writing."""
        if self.debug_words:
            print(f"--> Running in DEBUG mode for headword(s): {', '.join(sorted(self.debug_words))}")
        print(f"--> Reading and processing '{self.input_tsv}'...")
        try:
            with open(self.input_tsv, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    # Process metadata lines for the .ifo file
                    if line.startswith('##'):
                        self._process_metadata_line(line)
                    else:
                        self._process_entry_line(line)

            print()
            print("--> Processing complete. Writing Stardict files...")
            self._write_output()
            self._print_summary()
        except Exception as e:
            sys.exit(f"Error processing TSV file: {e}")
        finally:
            self._cleanup()

    def _process_entry_line(self, line: str):
        """Processes a single dictionary entry line."""
        parts = line.split('\t', 1)
        if len(parts) != 2:
            self.metrics['malformed_lines'] += 1
            return # Skip malformed lines

        self.metrics['source_entry_count'] += 1
        if self.metrics['total_entries'] > 0:
            if self.debug_words:
                print(f"--> Processing: {self.metrics['source_entry_count']}/{self.metrics['total_entries']}", end='\r')
            else:
                percent = (self.metrics['source_entry_count'] / self.metrics['total_entries']) * 100
                print(f"--> Processing: {self.metrics['source_entry_count']}/{self.metrics['total_entries']} ({percent:.1f}%)", end='\r')
        word, definition = parts
        if self.debug_words and word not in self.debug_words:
            return
        self.unique_headwords.add(word)

        if word.endswith(('.', '‖', '¶', '†')):
            entry_word, definition = self._handle_dotted_word_quirks(word, definition)
        else:
            entry_word = word

        # First, split the definition by the homograph pattern
        split_parts = self.homograph_pattern.split(definition)

        if len(split_parts) > 1:
            self._process_homograph_entry(entry_word, word, split_parts)
        else: # If no splits, process the HTML of the whole definition
            self._process_single_entry(entry_word, word, definition)

    def _process_metadata_line(self, line: str):
        """Parses a metadata line and updates the glossary info."""
        meta_parts = line.lstrip('#').strip().split('\t', 1)
        if len(meta_parts) == 2:
            key, value = meta_parts
            key, value = key.strip(), value.strip()
            if key == 'wordcount':
                try:
                    if self.debug_words:
                        self.metrics['total_entries'] = len(self.debug_words)
                    else:
                        self.metrics['total_entries'] = int(value)
                except ValueError:
                    pass # Ignore if wordcount isn't a valid number
            print(f"    - Found metadata: '{key}' = '{value}'")
            self.glos.setInfo(key, value)

    def _handle_dotted_word_quirks(self, word: str, definition: str) -> tuple:
        """Handles special logic for words ending in full stops or symbols."""
        # Some of these seem to be legitimate entries, whilst others seem to have been added by a previous "editor"
        # I'm choosing to preserve them but we need to handle some quirks.
        if word == "Prov.":
            definition = "<br/>proverb, (in the Bible) Proverbs"
        elif word == "Div.":
            definition = "<br/>division, divinity"
        elif word == ". s. d.":
            word = "l. s. d."
        # For some bizarre and unbeknown reason, these abbreviation entries have their definition duplicated
        # so we will have to verify if it is the case (it is!) and clean it up. After that we will add a synonym
        # entry for the headword without the leading full stop, so koreader can find it without editing.
        test_definition = definition.replace('\\n', '')
        def_len = len(test_definition)

        # sadly this method fails for some duplicated entries (about 7%, see "adj.") but it works for most of them
        if def_len > 0 and def_len % 2 == 0:
            midpoint = def_len // 2
            if test_definition[:midpoint] == test_definition[midpoint:]:
                # If it's a duplicate, the correct definition is the part
                # before the original newline separator.
                definition = '<br/>' + definition.split('\\n')[0]
                self.metrics['dot_corrected'] += 1
        alt_key = word.rstrip('.')
        entry_word = [word, alt_key]
        self.metrics['dotted_words'] += 1
        return entry_word, definition

    def _process_homograph_entry(self, entry_word, word: str, split_parts: list):
        """Processes an entry that contains multiple homographs."""
        self.metrics['split_entry_count'] += 1
        for part in split_parts:
            if part.strip():
                processor = EntryProcessor(part, word)
                processed_part = processor.process()
                if re.search(r'<b><sup>[IVXL]+</sup></b>\s*<span class="headword">', processed_part):
                    # A headword is already present, so use the part as-is.
                    final_definition = processed_part
                else:
                    # The headword is missing, so we prepend it.
                    headword_b_tag = f' <span class="headword"><b>{word}</b></span>'
                    final_definition = processed_part.replace('</b>', '</b>' + headword_b_tag, 1)

                self._create_entry(entry_word, final_definition)

    def _process_single_entry(self, entry_word, word: str, definition: str):
        """Processes a standard, non-homograph entry."""
        processor = EntryProcessor(definition, word)
        processed_definition = processor.process()
        headword_div = f'<span class="headword"><b>{word}</b></span>'
        final_definition = headword_div + processed_definition

        if re.search(
            r'<span class="headword"><b>(.*?)</b></span>(<blockquote>)?<b>(<span class="abbreviation">[‖¶†]</span>\s)?[\w\u00C0-\u017F\u0180-\u024F\u02C8\' &\-\.]',
            final_definition): # \u02C8 is ˈ
            # If the headword was already present, we don't need to prepend it, so remove it.
            # Seems backwards to do it this way but it is much safer.
            final_definition = final_definition.replace(headword_div, '', 1)
            # Finally, wrap the headword in a span tag, to match the expected format.
            final_definition = re.sub(r'<b>(.*?)</b>', r'<span class="headword"><b>\1</b></span>', final_definition, count=1)
        elif re.search(r'<span class="headword"><b>(.*?)</b></span>(<i>)?(<span class="abbreviation">\w|[\w])', final_definition):
            # some entries (see "gen") need some space
            final_definition = final_definition.replace(headword_div, headword_div + ' ', 1)

        self._create_entry(entry_word, final_definition)

    def _write_output(self):
        """Writes the final Stardict files, including CSS and .syn handling."""
        output_dir = Path(self.output_ifo_name)
        output_dir.mkdir(parents=True, exist_ok=True)

        # And back to Stradict we go!
        if self.debug_words:
            self.glos.setInfo("title", "debug OED")
        self.glos.setInfo("description", "This dictionary includes alternate search keys to make abbreviations searchable with and without their trailing full stops. " \
                    "This feature does not include grammatical inflections.")
        self.glos.setInfo("date", time.strftime("%Y-%m-%d"))
        css_path = self.input_tsv.parent / 'style.css'
        if css_path.is_file():
            try:
                # Open the CSS file in mode and read its content
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
                self.glos.write(str(output_base_path), formatName="Stardict")
            else:
                self.glos.write(str(output_base_path), formatName="StardictMergeSyns")
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
        if self.add_syns:
            print(f"- Synonyms added from b-tags:       {self.metrics['synonyms_added_count']:,}")
        print(f"- Words ending in full stops found: {self.metrics['dotted_words']:,}")
        print(f"- Full stops corrected:             {self.metrics['dot_corrected']:,}")
        print(f"- Total final entries written:      {self.metrics['final_entry_count']:,}")
        print(f"- Total execution time:             {int(minutes):02d}:{int(seconds):02d}")
        print("----------------------------------------------------\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Reads a TSV dictionary, preserves metadata, splits homographs, cleans HTML, and writes a Stardict file.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("input_tsv", type=Path, help="Path to the source .tsv file.")
    parser.add_argument("output_ifo", type=str, help="Base name for the new output Stardict files (e.g., 'OED_2ed').")
    parser.add_argument("--add-syns", action="store_true", help="Scan HTML for b-tags and add their cleaned content as synonyms for the entry.")
    parser.add_argument("--debug", nargs='+', help="Run the script only for the specified headword(s) to speed up testing.")
    args = parser.parse_args()

    converter = DictionaryConverter(args.input_tsv, args.output_ifo, args.add_syns, args.debug)
    converter.run()

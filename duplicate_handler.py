import hashlib
import re
from pathlib import Path

class DuplicateHandler:
    """
    Handles post-processing deduplication.
    Buffers processed entries, merges duplicates based on HTML content,
    and writes the merger log.
    """
    def __init__(self, output_base_name):
        self.output_name = output_base_name
        self.entries = []            # The final list of unique entries
        self.seen_hashes = {}        # hash -> index in self.entries
        self.dropped_log = {}        # hash -> list of dropped headwords [word1, word2]

    def add(self, words: list[str], definition: str, debug_words=None, is_split_part: bool = False):
        # Hash the processed definition
        def_hash = hashlib.sha256(definition.encode('utf-8')).hexdigest()

        if def_hash in self.seen_hashes:
            # duplicate found
            existing_idx = self.seen_hashes[def_hash]
            existing_entry = self.entries[existing_idx]

            new_word = words[0]
            current_primary = existing_entry['words'][0]

            headword_text = ""
            match = re.search(r'<span class="headword"><b>(.*?)</b></span>', definition)
            if match:
                headword_text = re.sub(r'<[^>]+>', '', match.group(1))

            clean_hw = re.sub(r'[ˈˌ]', '', headword_text)
            clean_hw = re.sub(r'\(', '', clean_hw)
            if is_split_part:
                if new_word not in clean_hw:
                    return

            # We check position of both valid candidates in the headword text
            # If both are present, the one with the lower index wins.
            candidates = [current_primary, new_word]
            # Filter candidates that are actually in the text
            valid_candidates = [c for c in candidates if c in clean_hw]

            winning_word = current_primary # Default to keeping current if uncertain

            if len(valid_candidates) > 0:
                # Sort by their first appearance index in the string
                try:
                    valid_candidates.sort(key=lambda w: clean_hw.find(w))
                    winning_word = valid_candidates[0]
                except ValueError:
                    pass

            if winning_word == new_word:
                # Swap needed: New word is better suited as primary
                dropped_headword = current_primary

                # Reconstruct entry words with new winner at front
                # Create set for unique, but preserve winning_word as 0
                all_w = set(existing_entry['words'] + words)
                all_w.discard(winning_word)
                existing_entry['words'] = [winning_word] + list(all_w)
            else:
                # No swap: Current is still best
                dropped_headword = new_word
                for w in words:
                    if w not in existing_entry['words']:
                        existing_entry['words'].append(w)

            if dropped_headword != winning_word:
                if def_hash not in self.dropped_log:
                    self.dropped_log[def_hash] = []
                if dropped_headword not in self.dropped_log[def_hash]:
                    self.dropped_log[def_hash].append(dropped_headword)

            if debug_words:
                print(f"\n\n--> Duplicated entry found: '{new_word}'")
                print(f"--> '{dropped_headword}' is a duplicate of: '{winning_word}'")
                print(f"--> From headword: >> {headword_text} <<")

        else:
            # new entry
            self.seen_hashes[def_hash] = len(self.entries)
            self.entries.append({'words': words, 'definition': definition})

    def get_entries(self):
        """Returns the final list of unique, merged entries."""
        return self.entries

    def write_log(self):
        """Writes the kept|dropped1|dropped2 log file."""
        if not self.dropped_log:
            return

        log_file = Path(self.output_name).parent / f"{Path(self.output_name).name}_dup_log.txt"
        try:
            if log_file.exists():
                log_file.unlink()

            with open(log_file, 'w', encoding='utf-8') as lf:
                for def_hash, dropped_list in self.dropped_log.items():
                    # Find the kept word for this hash
                    idx = self.seen_hashes[def_hash]
                    kept_word = self.entries[idx]['words'][0]

                    # Format: kept|dropped1|dropped2
                    line_str = f"{kept_word}|{'|'.join(dropped_list)}\n"
                    lf.write(line_str)

            print(f"--> Duplicate entries log written to '{log_file}'.")
        except Exception as e:
            print(f"--> Warning: Could not write duplicate log: {e}")

    def get_stats(self):
        """Returns tuple: (unique_hashes_count, entries_with_dupes_count, total_dropped_count)"""
        total_dropped = sum(len(drops) for drops in self.dropped_log.values())
        return len(self.seen_hashes), len(self.dropped_log), total_dropped

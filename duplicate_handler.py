import hashlib
import html
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
        self.mismatch_log = []       # list of (word, headword_span)
        self.seen_hashes = {}        # hash -> index in self.entries
        self.dropped_log = {}        # hash -> list of dropped headwords [word1, word2]
        self.quarantine = {}         # def_hash -> (words, definition, headword_text)

    def add(self, words: list[str], definition: str, debug_words=None, is_split_part: bool = False):
        headword_text = ""
        match = re.search(r'<span class="headword"><b>(.*?)</b></span>', definition)
        if match:
            headword_text = html.unescape(re.sub(r'<[^>]+>', '', match.group(1)))

        # clean_hw retains bare opening parens (e.g. 'hois(s') intentionally
        # paren_only relies on this to detect words that only exist as parenthetical roots.
        clean_hw = re.sub(r'[ˈˌ]', '', headword_text)
        hw_forms = self._expand_parens(clean_hw)      # expand balanced parens first
        hw_forms = [re.sub(r'\(', '', f) for f in hw_forms]  # then strip bare opening parens
        clean_hw_base = re.sub(r'\([^)]*\)', '', clean_hw)  # e.g. '† ey(e)rer' → '† eyrer'

        # Hash the processed definition
        def_hash = hashlib.sha256(definition.encode('utf-8')).hexdigest()

        if is_split_part and headword_text and not any(words[0] in form for form in hw_forms):
            if debug_words:
                print(f"\n\n--> Headword mismatch: '{words[0]}' not found in headword span")
                print(f"    Headword span: >> {headword_text} <<")
                print(f"    Quarantining entry pending duplicate check")
            self.quarantine[def_hash] = (words, definition, headword_text)
            return

        if def_hash in self.seen_hashes:
            # duplicate found
            existing_idx = self.seen_hashes[def_hash]
            existing_entry = self.entries[existing_idx]

            new_word = words[0]
            current_primary = existing_entry['words'][0]

            candidates = [current_primary, new_word]
            # Filter candidates that are actually in the text
            valid_candidates = [c for c in candidates if
                any(re.search(rf'(?<!\w){re.escape(c)}(?!\w)', form) for form in hw_forms) or
                re.search(rf'(?<!\w){re.escape(c)}\(', clean_hw)]

            winning_word = current_primary # Default to keeping current if uncertain

            if debug_words:
                print(f"\n\n--> Duplicated entry found: '{new_word}'")

            if valid_candidates:
                def sort_key(w):
                    """
                    Calculates sorting criteria and metadata for a candidate word.
                    Pecking order:
                        1. Whoever appears earliest in the headword wins
                        2. Words that only exist by virtue of expanding a parenthetical form yield
                        3. If tied on position, a clean standalone word beats one that only exists as a parenthetical root
                        4. If still tied, the longer word wins
                    """
                    # Look for the earliest occurrence across all forms
                    occurrences = [form.find(w) for form in hw_forms if w in form]
                    pos = min(occurrences) if occurrences else len(clean_hw_base)

                    # Boundary-aware regex to check for standalone existence
                    pattern = rf'(?<!\w){re.escape(w)}(?!\w)'

                    in_base = bool(re.search(pattern, clean_hw_base))
                    in_any_form = any(re.search(pattern, form) for form in hw_forms)

                    expanded_only = int(not in_base and in_any_form)
                    paren_only = int(not in_any_form and re.search(rf'(?<!\w){re.escape(w)}\(', clean_hw) is not None)

                    return (pos, expanded_only, paren_only, -len(w))

                # Sort using the metadata tuple
                valid_candidates.sort(key=sort_key)

                if debug_words:
                    print(f"    hw_forms: {hw_forms}")
                    print(f"    candidates: {valid_candidates}")
                    for w in valid_candidates:
                        pos, exp_only, par_only, neg_len = sort_key(w)
                        print(f"        * '{w}': pos={pos}, expanded_only={exp_only}, paren_only={par_only}, len={-neg_len}")

                winning_word = valid_candidates[0]

            if winning_word == new_word:
                # Swap needed: New word is better suited as primary
                dropped_headword = current_primary
                # Reconstruct entry words with new winner at front
                # Create set for unique, but preserve winning_word as 0
                all_w = set(existing_entry['words'] + words)
                all_w.discard(winning_word)
                existing_entry['words'] = [winning_word] + list(all_w)
                # Push this entry's sort index past the current tail so it sorts after
                # any entries that were registered before the swap occurred.
                existing_entry['idx'] = len(self.entries)
            else: # No swap: Current is still best
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
                print(f"    '{new_word}' is a duplicate of: '{current_primary}'")
                print(f"    From headword: >> {headword_text} <<")
                print(f"    Merging '{dropped_headword}' into '{winning_word}'")
        else:
            self.seen_hashes[def_hash] = len(self.entries)
            self.entries.append({'words': list(words), 'definition': definition, 'idx': len(self.entries)})

    def _expand_parens(self, text):
        """Expand 'ey(e)rer' into ['eyrer', 'eyerer']."""
        results = [text]
        for m in re.finditer(r'\(([^)]+)\)', text):
            results = [
                r.replace(m.group(0), '', 1)      # without paren content
                for r in results
            ] + [
                r.replace(m.group(0), m.group(1), 1)  # with paren content
                for r in results
            ]
        return results

    def drain(self):
        """Yield entries in sorted order, clearing as we go."""
        for entry in sorted(self.entries, key=lambda e: (e['words'][0], e['idx'])):
            yield {'words': entry['words'], 'definition': entry['definition']}
            entry['definition'] = None
        self.entries.clear()
        self.seen_hashes.clear()
        self.dropped_log.clear()
        self.mismatch_log.clear()

    def quarentine_trial(self, debug_words=None):
        """Trial for quarantined entries — run after all adds, before drain."""
        for def_hash, (words, definition, headword_text) in self.quarantine.items():
            if def_hash in self.seen_hashes:
                if debug_words:
                    print(f"\n    Quarantine trial: '{words[0]}' confirmed duplicate — sending to Gaol")
                    print(f"     Headword span: >> {headword_text} <<")
                self.mismatch_log.append((words[0], headword_text))
            else:
                if debug_words:
                    print(f"\n    Quarantine trial: '{words[0]}' not a duplicate — reinstating")
                    print(f"     Headword span: >> {headword_text} <<")
                self.entries.append({'words': list(words), 'definition': definition, 'idx': len(self.entries)})
        self.quarantine.clear()

    def write_logs(self):
        if self.dropped_log:
            self._write_log_file(
                f"{Path(self.output_name).name}_dup_log.txt",
                (f"{self.entries[self.seen_hashes[h]]['words'][0]}|{'|'.join(d)}\n"
                for h, d in self.dropped_log.items()),
                "Duplicate entries log",
            )
        if self.mismatch_log:
            self._write_log_file(
                f"{Path(self.output_name).name}_mismatch_log.txt",
                (f"{w}|{s}\n" for w, s in self.mismatch_log),
                "Headword mismatch log",
            )

    def _write_log_file(self, filename, lines, label):
        log_file = Path(self.output_name).parent / filename
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            if log_file.exists():
                log_file.unlink()
            with open(log_file, 'w', encoding='utf-8') as lf:
                lf.writelines(lines)
            print(f"--> {label} written to '{log_file}'.")
        except Exception as e:
            print(f"--> Warning: Could not write {label.lower()}: {e}")

    def get_stats(self):
        """Returns tuple: (unique_hashes_count, entries_with_dupes_count, mismatched_entries, total_dropped_count)"""
        total_dropped = sum(len(drops) for drops in self.dropped_log.values()) + len(self.mismatch_log)
        return len(self.seen_hashes), len(self.dropped_log), len(self.mismatch_log), total_dropped

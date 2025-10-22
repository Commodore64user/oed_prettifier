import re
from entry_processor import EntryProcessor
from synonym_extractor import SynonymExtractor

# This pattern was moved here from the main class to make the worker self-contained.
CORE_HOMOGRAPH_PATTERN = r'(?:<b><span style="color:#8B008B">▪ <span>(?:[IVXL]+\.)</span></span></b>)'
HOMOGRAPH_PATTERN = re.compile(f'(?={CORE_HOMOGRAPH_PATTERN})')

def _handle_dotted_word_quirks(word: str, definition: str) -> tuple:
    """Handles special logic for words ending in full stops or symbols."""
    # Some of these seem to be legitimate entries, whilst others seem to have been added by a previous "editor"
    # I'm choosing to preserve them but we need to handle some quirks.
    metrics = {'dotted_words': 1, 'dot_corrected': 0}
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
            metrics['dot_corrected'] = 1

    alt_key = word.rstrip('.')
    entry_word = [word, alt_key]
    return entry_word, definition, metrics

def finalise_entry(base_word: list[str] | str, final_definition: str, add_syns: bool, debug_words: set[str] | None) -> dict:
    """Takes a processed definition, extracts synonyms, and packages the final entry data."""
    all_words = list(base_word) if isinstance(base_word, list) else [base_word]
    syn_count = 0

    if add_syns:
        # The headword for synonym extraction is the first word in the base list.
        headword_for_syns = all_words[0]
        synonyms = SynonymExtractor.extract(headword_for_syns, final_definition)
        if synonyms:
            all_words.extend(synonyms)
            syn_count = len(synonyms)
            # Although architecturally impure, this pragmatic printing to console here
            # will avoid us a whole set of unnecessarily complex rerouting of synonyms.
            if debug_words and headword_for_syns in debug_words:
                sorted_syns = sorted(synonyms, key=lambda s: (len(s), s))
                print(f"\n\n--> Synonyms for '[{headword_for_syns}]': {'; '.join(sorted_syns)}\n")

    return {'words': all_words, 'definition': final_definition, 'syn_count': syn_count}

def process_entry_line_worker(line_tuple: tuple[str, bool, set[str] | None]) -> dict:
    """Worker function to process a single TSV line.
    This function is designed to be run in a separate process.
    It returns a dictionary with status, results, and metrics."""
    line, add_syns, debug_words = line_tuple
    try:
        parts = line.split('\t', 1)
        if len(parts) != 2:
            return {'status': 'error', 'type': 'malformed_line', 'line': line}

        word, definition = parts
        metrics = {'source_entry': 1, 'split_entry': 0, 'dotted_words': 0, 'dot_corrected': 0, 'synonyms_added': 0}

        entry_word_base = word
        if word.endswith(('.', '‖', '¶', '†')):
            entry_word_base, definition, dot_metrics = _handle_dotted_word_quirks(word, definition)
            metrics.update(dot_metrics)

        split_parts = HOMOGRAPH_PATTERN.split(definition)
        processed_results = []

        if len(split_parts) > 1:
            metrics['split_entry'] = 1
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

                    final_entry = finalise_entry(entry_word_base, final_definition, add_syns, debug_words)
                    processed_results.append(final_entry)
                    metrics['synonyms_added'] += final_entry['syn_count']
        else:
            # Logic for a standard, non-homograph entry.
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

            final_entry = finalise_entry(entry_word_base, final_definition, add_syns, debug_words)
            processed_results.append(final_entry)
            metrics['synonyms_added'] += final_entry['syn_count']

        return {'status': 'ok', 'results': processed_results, 'metrics': metrics}

    except Exception as e:
        return {'status': 'error', 'type': 'processing_error', 'line': line, 'error': str(e)}

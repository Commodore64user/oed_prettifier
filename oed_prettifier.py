import argparse
import re
import sys
import time
import subprocess
from pathlib import Path
from bs4 import BeautifulSoup
from pyglossary.glossary_v2 import Glossary
from pyglossary.entry import Entry

CORE_HOMOGRAPH_PATTERN = r'<b><span style="color:#8B008B">▪ <span>[IVXL]+\.</span></span></b>'

SYNONYM_CLEANUP_MAP = {
    "†": "",   "*": "",   "ˈ": "",   "ˌ": "",   "(": "",   ")": "",   "[": "",   "]": "",   "‖": "",   "¶": "",   "?": "",   "!": "",
    "–": "",   "—": "",   ";": "",   ":": "",
}

IGNORED_SYN_WORDS = {'to', 'or', 'and', 'a', 'an', 'the', 'after', 'before', 'in', 'on', 'at', 'for', 'with', 'by', 'of', 'from', 'Derivatives.',
                        'that', 'which', 'who', 'whom', 'whose', 'as', 'than', 'like', 'such', 'so', 'but', 'if', 'when', 'up', 'down', 'Compounds.'}

def process_html(html: str, headword: str) -> str:
    html = re.sub(r'<img[^>]+>', '', html)
    html = re.sub(r'\\n', ' ', html)
    html = re.sub(r'\\t', ' ', html)
    if headword.endswith('.'):
        html = html.replace('<abr>', '', 1)
        html = html.replace('</abr>', '', 1)

    html = re.sub(r'(<span>[IVXL]+\.</span></span></b>)\s*(<blockquote>)?(<b>.*?</b>)(</blockquote>)?', r'\1 <span class="headword">\3</span>', html, flags=re.DOTALL)
    html = re.sub(r'<blockquote>\(<span style="color:#2F4F4F">(.*?)</span>\)</blockquote>', r' (<span class="phonetic">\1</span>)', html, flags=re.DOTALL)

    html = html.replace('<blockquote><ex>', '<div class="quotations">')
    html = html.replace('</ex></blockquote>', '</div>')

    html = re.sub(r'(<abr>†</abr>)\s', r'\1', html)
    html = re.sub(r'(<abr>¶</abr>)\s', r'\1', html)
    html = re.sub(r'<kref>(.*?)</kref>', r'<span class="kref">\1</span>', html)
    html = html.replace('<abr>=</abr>', '<span class="same-as">=</span>')
    # This is a liberty I've taken, which will capture some false positives (relative to the original OED text, see entry "them" section II. 4),
    # but as it is a very common pattern, it will be useful to have it regardless.
    html = re.sub(r'(<span class="same-as">=</span>)\s+([a-zA-Z]+)', r'\1 <span class="kref">\2</span>', html)

    # This should separate quotations blocks in cases like "weak" where there are continuous quotations for different subsenses
    # or cases like "which" sense 14, subsense a. where there are sub-subsenses (a) and (b).
    # or when greek letters are involved, see "fantastic". Finally combine all other blocks into one.
    html = re.sub(r'(</div>)(<div class="quotations">)(<b>[a-z]\.</b>)', r'\1 \2\3', html)
    html = re.sub(r'(</div>)(<div class="quotations">)(<i>\([a-z]\)</i>)', r'\1 \2\3', html)
    html = re.sub(r'(</div>)(<div class="quotations">)(<i><abr>[a-zA-Z]+\.</abr></i>)', r'\1 \2\3', html) # weak 2.a
    html = re.sub(r'(</div>)(<div class="quotations">)(<i>[a-zA-Z]+\.?(?:[-\s][a-zA-Z]+\.)?</i>)', r'\1 \2\3', html) # weak 5.a
    html = re.sub(r'(</div>)(<div class="quotations">)([\u03b1-\u03c9](?:<sup>[0-9]</sup>)? <b>)', r'\1 \2\3', html) # greek letters
    html = re.sub(r'(</div>)(<div class="quotations">)(<b>)', r'\1\2 \3', html)
    html = html.replace('</div><div class="quotations">', '')

    html = re.sub(r'(<b>)<span style="color:#8B008B">▪ <span>([IVXL]+)\.</span></span>(</b>)', r'\1<sup>\2</sup>\3', html)
    # Fix dates, only match exactly 3 or 4 digit years. This should turn "c 1500" into "c1500" or "? a 1300" into "?a1300".
    html = re.sub(r'<b>(\?)?\s?<i>([acp])</i> (\d{3,4})(\u2013\d{2})?</b>', r'<b>\1<i>\2</i>\3\4</b>', html)
    html = re.sub(r'<b>(\?)?\s?(\d{3,4})(\u2013\d{2})?</b>', r'<b>\1\2\3</b>', html)
    # Handle anonymous "in Source" patterns first, we add a placeholder which will be removed later.
    html = re.sub(
        r'(<b>(?:\?)?(?:<i>[acp]</i>)?(\d{3,4})(\u2013\d{2})?</b>)\s+((?:in\s+[^<]*|―\s+)<i>.*?</i>)',
        r'\1 <ANON_IN_SOURCE>\4</ANON_IN_SOURCE>',
        html
    )
    html = re.sub(
        r'(<b>(?:\?)?(?:<i>[acp]</i>)?(\d{3,4})(\u2013\d{2})?</b>)\s+([^\s<]+(?:\s+[^\s<]+)*?)\s+(?=in\s+<i>|<i>|in|\(\w)',
        r'\1 <span class="author">\4</span> ',
        html
    )
    html = re.sub(
        r'(<span class="author">[^<]*</span>)\s+((?:in\s+)?<i>[^<]*</i>)', r'\1 <span class="title">\2</span>', html)
    html = re.sub( # Handle author + number reference pattern (like Ormin 9500)
        r'(<b>(?:\?)?(?:<i>[acp]</i>)?(\d{3,4})</b>)\s+([^\s<]+(?:\s+[^\s<]+)*)\s+(\d+)\s+<span style="color:#8B008B">',
        r'\1 <span class="author">\3</span> <span class="reference">\4</span> <span style="color:#8B008B">',
        html
    )
    html = re.sub( # Handle author + number line-number pattern (like Lay. 3014)
        r'(<b>(?:\?)?(?:<i>[acp]</i>\s?)?(\d{3,4})</b>)\s+((?:[A-Z]+\.)?\s?<abr>[^<]+</abr>)\s+(\d+)\s+<span style="color:#8B008B">',
        r'\1 <span class="author">\3</span> <span class="line-number">\4</span> <span style="color:#8B008B">',
        html
    )

    # html = re.sub(
    #     r'(<b>(?:\?)?(?:<i>[acp]</i>)?(\d{3,4})(\u2013\d{2})?</b>)\s+([^\s<,]+(?:\s+[^\s<,]+)*),\s+<span class="quotes">',
    #     r'\1 <span class="author">\4</span>, <span class="quotes">',
    #     html
    # )

    # Replace the start of the etymology block, but only the first occurrence, just in case.
    html = re.sub(
        r'<blockquote><span style="color:#808080">\[',
        '<div class="etymology"><blockquote><span class="etymology-main">[',
        html,
        count=1
    )
    # Then let's try finding the correct closing tag for the etymology block. stop_pos is a point at which it will for sure have closed.
    stop_pos = html.find('<b><span style="color:#4B0082">')
    search_text = html[:stop_pos] if stop_pos != -1 else html
    result, count = re.subn(r'\](</span>)</blockquote>', ']</span></div>', search_text, count=1)
    if count == 0:
        result = re.sub(r'\]</blockquote>', ']</div>', result, count=1)
    html = result + (html[stop_pos:] if stop_pos != -1 else '')
    # Not quite done yet, now add class to all other blockquotes inside the etymology block.
    def process_etymology(match):
        block = match.group(1)
        # Add indent class to all blockquotes
        block = re.sub(r'(</blockquote>)<blockquote>', r'\1<blockquote class="etymology-notes">', block)
        return f'<div class="etymology">{block}</div>'
    html = re.sub(r'<div class="etymology">(.*?)</div>', process_etymology, html, flags=re.S)

    # Heuristic approach to wrap in the forms section. note: there are multiple variations here so other forms sections found deep
    # into an entry might not be captured. HELP WANTED @fixme.
    html = re.sub(r'<blockquote>(Forms:?.*?)</blockquote>', r'<div class="forms">\1</div>', html, flags=re.DOTALL)
    html = re.sub(r'<blockquote>(Also [0-9].*?)</blockquote>', r'<div class="forms">\1</div>', html, flags=re.DOTALL)
    html = re.sub(r'<blockquote>(<abr>Pa.</abr>.*?)</blockquote>', r'<div class="forms">\1</div>', html, flags=re.DOTALL)
    html = re.sub(r'<blockquote>(Past and <abr>pple.</abr>.*?)</blockquote>', r'<div class="forms">\1</div>', html, flags=re.DOTALL)
    html = re.sub(r'<blockquote>(Pl. <b>.*?)</blockquote>', r'<div class="forms">\1</div>', html, flags=re.DOTALL)
    html = re.sub(r'<blockquote>(Usually in <abr>pl.</abr>.*?)</blockquote>', r'<div class="forms">\1</div>', html, flags=re.DOTALL)
    html = re.sub(r'<blockquote>(commonly in (?:<i>)?<abr>pl.</abr>.*?)</blockquote>', r'<div class="forms">\1</div>', html, flags=re.DOTALL)
    # sometimes the 'forms' section is placed below its normal location and is preceded by a greek letter, e.g., "α", so we need to capture that too.
    html = re.sub(r'<blockquote>(\(<i>[\u03b1-\u03c9]</i>\).*?)</blockquote>', r'<div class="forms">\1</div>', html, flags=re.DOTALL)
    html = re.sub(r'<blockquote>([\u03b1-\u03c9]<sup>[0-9]</sup>.*?)</blockquote>', r'<div class="forms">\1</div>', html, flags=re.DOTALL) # greek letters

    # These are mini etymologies found for specific senses (i.e., not the main at the top of the entry).
    html = html.replace('<blockquote>[', '<div class="etymology">[')
    html = html.replace(']</blockquote>', ']</div>')

    html = html.replace('<span style="color:#8B008B">', '<span class="quotes">')
    html = re.sub(r'</span><b>(\??(<i>)?[acp0-9])', r'</span> <b>\1', html)
    html = re.sub(r'(<span class="quotes">.*?</span>)(<[^>]+>)', r'\1 \2', html)

    html = re.sub(r'\{sup([a-z])\}', r'<span class="small-cap-letter">\1</span>', html)
    html = re.sub(r'(</blockquote>)(<blockquote><abr>†</abr>\s*<b><span style="color:#4B0082">)', r'\1 \2', html)
    # Remove embedded styles and add classes to the spans
    html = re.sub(r'<span style="color:#4B0082">(\[?[0-9]+\.\]?)</span>', r'<span class="senses">\1</span>', html)
    html = re.sub(r'<span style="color:#4B0082">(\[?[a-z]\.\]?)</span>', r'<span class="subsenses">\1</span>', html)
    html = re.sub(r'<span style="color:#4B0082"><abr>(\[?[a-z]\.\]?)</abr></span>', r'<span class="subsenses">\1</span>', html)
    html = re.sub(r'<span style="color:#4B0082">(\[?[0-9]+\.\]?) (\[?[a-z]\.\]?)</span>', r'<span class="senses">\1</span> <span class="subsenses">\2</span>', html)
    html = re.sub(r'<span style="color:#4B0082">(\[?[IVXL]+\.\]?) (\[?[0-9]+\.\]?)</span>', r'<span class="major-division">\1</span> <span class="senses">\2</span>', html)
    html = re.sub(r'<span style="color:#4B0082">(\[?[IVXL]+\.\]?)</span>', r'<span class="major-division">\1</span>', html)
    html = re.sub(r'<span style="color:#4B0082">(\[?[A-Z]\.\]?)</span>', r'<span class="pos">\1</span>', html)
    html = re.sub(r'<span style="color:#4B0082">(\[?[A-Z]\.\]?) (\[?[IVXL]+\.\]?)</span>', r'<span class="pos">\1</span> <span class="major-division">\2</span>', html)

    html = re.sub(
        r'(<blockquote><b><span class="(?:senses|subsenses)">[a-z0-9]+\.</span></b>) (.*?\(<i>[\u03b1-\u03c9]</i>\).*?)</blockquote>',
        r'\1 <span class="forms">\2</span></blockquote>',
        html,
        flags=re.DOTALL
    )

    html = re.sub(r'</blockquote><blockquote>(\s*)(<b>)?<span class=', r'</blockquote><blockquote class="definition-partial">\1\2<span class=', html)
    html = re.sub(r'(_____</blockquote>)<blockquote>', r'\1<blockquote class="addendum">', html)
    html = re.sub(r'<blockquote>\*', '<blockquote class="subheading">*', html)
    # This seems to be introducing some false positives, see entry "in", but overall it follows the OED pattern,
    # so keeping it for now, however it might need to be revisited. @fixme.
    html = html.replace('</blockquote><blockquote>', '</blockquote><blockquote class="usage-note">')

    # see "them"'s etymology.
    def replace_acute(match):
        letter = match.group(1)
        accent_map = {
            'a': '\u00e1',  'A': '\u00c1', # á
            'e': '\u00e9',  'E': '\u00c9', # é
            'i': '\u00ed',  'I': '\u00cd', # í
            'o': '\u00f3',  'O': '\u00d3', # ó
            'u': '\u00fa',  'U': '\u00da', # ú
            'y': '\u00fd',  'Y': '\u00dd', # ý
        }
        return accent_map.get(letter, match.group(0))
    html = re.sub(r'\{([aeiouyAEIOUY])acu\}', replace_acute, html)
    html = html.replace('{ddd}', '...')
    html = html.replace('{oqq}', '\u201C')  # Left double quotation mark
    html = html.replace('{cqq}', '\u201D')  # Right double quotation mark
    html = html.replace('{nfced}', '\u00B8') # cedilla [squiggly bit only, which technically is what a cedilla is ;)]
    html = html.replace('{aacuced}', '\u00e1')
    def replace_cedilla(match):
        letter = match.group(1)
        cedilla_map = {
            'a': 'a\u0327', # a̧
            'c': '\u00e7', # ç
            'C': '\u00c7', # Ç
            # 'i': 'i\u0327', # i̧
            # 'u': 'u\u0327', # u̧
            'd': 'd\u0327', # ḑ
            't': '\u0163', # ţ
            'z': 'z\u0327', # z̧
        }
        return cedilla_map.get(letter, match.group(0))
    html = re.sub(r'\{([actdzC])ced\}', replace_cedilla, html)
    html = re.sub(r'⊇', 'e', html)
    # Leap of faith here, but cross-referencing with the OED online, this seems to be in fact the case. Not sure why is missing though.
    html = re.sub(r'\u2013 ([,;\.])', f'– <b>{re.escape(headword)}</b>' + r'\1', html) # n-dash –

    html = re.sub(r'(<b>(?:\?)?(?:<i>[acp]</i>)?(\d{3,4})</b>) (<abr>tr\.</abr>)(\s<i>)', r'\1 <span class="translator">tr.</span>\4', html)
    # Handle "Author abbreviation." pattern (like "Francis tr.")
    html = re.sub(r'(<b>(?:\?)?(?:<i>[acp]</i>)?(\d{3,4})</b>) ((?:[\w]\.)?\s?[\w]+)\s(<abr>[\w]+\.</abr>)(\s<i>)', r'\1 <span class="author">\3</span> \4\5', html)
    # Handle specific "Initial Author (Source) Number" pattern
    html = re.sub(
        r'(<b>(?:\?)?(?:<i>[acp]</i>)?(?:\d{3,4})</b>) ([A-Z]\.)\s<abr>([\w]+\.)</abr>\s(\([^)]+\))\s([0-9]+)',
        r'\1 <span class="author">\2 \3</span> \4 \5',
        html
    )
    # This grew out of control, but is seems to be held together by fairy dust, it works although this should have been done in a more structured way.
    html = re.sub(
        r'(<b>(?:\?)?(?:<i>[acp]</i>)?(?:\d{3,4})</b>) ([^<]*)?<abr>([\w]+\.)</abr>\s([\w]+)?\s?((<i>)?[0-9]?\s?)(<i>|<abr>)',
        r'\1 <span class="author">\2\3 \4</span> \5\7',
        html
    )
    # Finally, convert the placeholder back
    html = re.sub(r'<ANON_IN_SOURCE>', '', html)
    html = re.sub(r'</ANON_IN_SOURCE>', '', html)
    def fix_author_tr(match):
        content = match.group(0)
        if ' tr.' in content:
            return re.sub(r'<span class="author">(.*?) (tr\.(?:\s)*)</span>', r'<span class="author">\1</span> \2', content)
        return content
    html = re.sub(r'<span class="author">.*?</span>', fix_author_tr, html)

    html = re.sub(r'<span class="translator">tr.</span>', '<abr>tr.</abr>', html)
    html = html.replace('<abr>', '<span class="abbreviation">')
    html = html.replace('</abr>', '</span>')

    return html

def clean_synonym(text: str) -> str:
    """Removes unwanted characters from a potential synonym string."""
    for char, replacement in SYNONYM_CLEANUP_MAP.items():
        text = text.replace(char, replacement)
    return text.strip()

def extract_synonyms(headword: str, html: str) -> list[str]:
    soup = BeautifulSoup(html, 'html.parser')
    cleaned_syns = set()
    headword = clean_synonym(headword.strip())
    word_initial = headword[:1]

    # Find and remove all quotation divs from the parse tree.
    for div in soup.find_all('div', class_='quotations'):
        div.decompose()

    for b_tag in soup.find_all('b'):
        final_synonym = clean_synonym(b_tag.get_text().strip())

        if not final_synonym or final_synonym in IGNORED_SYN_WORDS:
            continue
        if final_synonym.startswith('-') or final_synonym.endswith('-'):
            continue
        if re.search(r'\d{2,}', final_synonym):
            continue
        if re.fullmatch(r'[IVXL]+\.', final_synonym):
            continue
        if re.fullmatch(r'[A-Za-z]\.?', final_synonym):
            continue
        if re.fullmatch(r'[0-9]\.?', final_synonym):
            continue
        # Skip overly long multi-word synonyms (likely phrases rather than single synonyms)
        if len(final_synonym.split()) > 3:
            continue

        # some entries (e.g., plover) when creating compounds, use "p." as shorthands
        final_synonym = final_synonym.replace(word_initial + ".", headword)
        cleaned_syns.add(final_synonym)

    return sorted(list(cleaned_syns))

def create_entry_with_or_with_optional_synonyms(entry_word, final_definition, add_syns, glos):
    """Helper function to handle synonym extraction and entry creation."""
    source_words = list(entry_word) if isinstance(entry_word, list) else [entry_word]

    # Only extract and add synonyms if the flag is set
    synonyms_added = 0
    if add_syns:
        # Ensure we pass a string headword (not a list) to extract_synonyms to avoid .strip() on a list
        synonyms = extract_synonyms(source_words[0], final_definition)
        if synonyms:
            source_words.extend(synonyms)
            original_word_count = len(entry_word) if isinstance(entry_word, list) else 1
            synonyms_added = len(source_words) - original_word_count

    main_headword = source_words[0]
    other_words = set(source_words[1:])
    other_words.discard(main_headword)
    all_words = [main_headword] + sorted(list(other_words))

    entry = Entry(word=all_words, defi=final_definition, defiFormat='h')
    glos.addEntry(entry)

    return synonyms_added


def run_processing(input_tsv: Path, output_ifo_name: str, add_syns: bool = False):
    """ Reads a TSV file, splits homographs, processes the HTML of each part,
    and writes a new Stardict dictionary, preserving all metadata."""
    if not input_tsv.is_file():
        sys.exit(f"Error: Input TSV file not found at '{input_tsv}'")

    start_time = time.time()
    source_entry_count, split_entry_count, final_entry_count, malformed_lines, dotted_words, dot_corrected = 0, 0, 0, 0, 0, 0
    synonyms_added_count, total_entries = 0, 0
    unique_headwords = set()

    homograph_pattern = re.compile(f'(?={CORE_HOMOGRAPH_PATTERN})')

    print(f"--> Reading and processing '{input_tsv}'...")

    Glossary.init()
    glos = Glossary()

    try:
        with open(input_tsv, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                # --- Process metadata lines for the .ifo file ---
                if line.startswith('##'):
                    meta_parts = line.lstrip('#').strip().split('\t', 1)
                    if len(meta_parts) == 2:
                        key, value = meta_parts
                        key, value = key.strip(), value.strip()
                        if key == 'wordcount':
                            try:
                                total_entries = int(value)
                            except ValueError:
                                pass # Ignore if wordcount isn't a valid number
                        print(f"    - Found metadata: '{key}' = '{value}'")
                        glos.setInfo(key, value)
                    continue # Move to the next line after processing metadata

                parts = line.split('\t', 1)
                if len(parts) != 2:
                    malformed_lines += 1
                    continue # Skip malformed lines

                source_entry_count += 1
                if total_entries > 0:
                    percent = (source_entry_count / total_entries) * 100
                    print(f"--> Processing: {source_entry_count}/{total_entries} ({percent:.1f}%)", end='\r')
                word, definition = parts
                unique_headwords.add(word)

                entry_word = word
                # Some of these seem to be legitimate entries, whilst others seem to have been added by a previous "editor"
                # I'm choosing to preserve them but we need to handle some quirks.
                if word.endswith(('.', '‖', '¶', '†')):
                    if word == "Prov.":
                        definition = "<br/>proverb, (in the Bible) Proverbs"
                    elif word == "Div.":
                        definition = "<br/>division, divinity"
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
                            dot_corrected += 1
                    alt_key = word.rstrip('.')
                    entry_word = [word, alt_key]
                    dotted_words += 1

                # First, split the definition by the homograph pattern
                split_parts = homograph_pattern.split(definition)

                if len(split_parts) > 1:
                    split_entry_count += 1
                    for part in split_parts:
                        if part.strip():
                            processed_part = process_html(part, word)
                            if re.search(r'<b><sup>[IVXL]+</sup></b>\s*<span class="headword">', processed_part):
                                # A headword is already present, so use the part as-is.
                                final_definition = processed_part
                            else:
                                # The headword is missing, so we prepend it.
                                headword_b_tag = f' <span class="headword"><b>{word}</b></span>'
                                final_definition = processed_part.replace('</b>', '</b>' + headword_b_tag, 1)

                            synonyms_added = create_entry_with_or_with_optional_synonyms(entry_word, final_definition, add_syns, glos)
                            if add_syns:
                                synonyms_added_count += synonyms_added
                            final_entry_count += 1
                else: # If no splits, process the HTML of the whole definition
                    processed_definition = process_html(definition, word)
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

                    synonyms_added = create_entry_with_or_with_optional_synonyms(entry_word, final_definition, add_syns, glos)
                    synonyms_added_count += synonyms_added
                    final_entry_count += 1

    except Exception as e:
        sys.exit(f"Error processing TSV file: {e}")

    print()
    print("--> Processing complete. Writing Stardict files...")

    # And back to Stradict we go!
    glos.setInfo("description", "This dictionary includes alternate search keys to make abbreviations searchable with and without their trailing full stops. " \
                "This feature does not include grammatical inflections.")
    glos.setInfo("date", time.strftime("%Y-%m-%d"))
    try:
        glos.write(output_ifo_name, formatName="Stardict")
        time.sleep(2)  # Ensure the file is written before proceeding
        syn_dz_path = Path(output_ifo_name).with_suffix('.syn.dz')
        if syn_dz_path.is_file():
            print(f"--> Decompressing '{syn_dz_path}'...")
            subprocess.run(f"dictzip -d \"{syn_dz_path}\"", shell=True, check=True)
    except Exception as e:
        sys.exit(f"An error occurred during the write process: {e}")

    end_time = time.time()
    duration = end_time - start_time
    minutes, seconds = divmod(duration, 60)

    print("\n----------------------------------------------------")
    print(f"Process complete. New dictionary '{output_ifo_name}.ifo' created.")
    print("----------------------------------------------------")
    print("Metrics:")
    print(f"- Entries read from source TSV:     {source_entry_count:,}")
    print(f"- Entries with homographs split:    {split_entry_count:,}")
    print(f"- Unique headwords processed:       {len(unique_headwords):,}")
    print(f"- Malformed lines skipped:          {malformed_lines:,}")
    if add_syns:
        print(f"- Synonyms added from b-tags:       {synonyms_added_count:,}")
    print(f"- Words ending in full stops found: {dotted_words:,}")
    print(f"- Full stops corrected:             {dot_corrected:,}")
    print(f"- Total final entries written:      {final_entry_count:,}")
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
    args = parser.parse_args()
    run_processing(args.input_tsv, args.output_ifo, args.add_syns)

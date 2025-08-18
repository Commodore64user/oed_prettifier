import argparse
import re
import sys
import time
import subprocess
from pathlib import Path
from pyglossary.glossary_v2 import Glossary
from pyglossary.entry import Entry

CORE_HOMOGRAPH_PATTERN = r'<b><span style="color:#8B008B">▪ <span>[IVXL]+\.</span></span></b>'

def process_html(html: str, word: str) -> str:
    html = re.sub(r'<img[^>]+>', '', html)
    html = re.sub(r'\\n', ' ', html)
    html = re.sub(r'\\t', ' ', html)
    if word.endswith('.'):
        html = html.replace('<abr>', '', 1)
        html = html.replace('</abr>', '', 1)

    html = re.sub(r'(<span>[IVXL]+\.</span></span></b>)\s*(<blockquote>)?(<b>.*?</b>)(</blockquote>)?', r'\1 <span class="headword">\3</span>', html, flags=re.DOTALL)
    html = re.sub(r'<blockquote>\(<span style="color:#2F4F4F">(.*?)</span>\)</blockquote>', r' (<span class="phonetic">\1</span>)', html, flags=re.DOTALL)

    html = html.replace('<blockquote><ex>', '<div class="quotations">')
    html = html.replace('</ex></blockquote>', '</div>')

    html = re.sub(r'<abr>†</abr>', '<span class="obsolete">†</span>', html)
    html = re.sub(r'(<span class="obsolete">†</span>)\s', r'\1', html)
    html = re.sub(r'<abr>¶</abr>', '<span class="pilcrow">¶</span>', html)
    html = re.sub(r'(<span class="pilcrow">¶</span>)\s', r'\1', html)
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
    html = re.sub(r'(</div>)(<div class="quotations">)([\u03b1-\u03c9] <b>)', r'\1 \2\3', html) # greek letters
    html = html.replace('</div><div class="quotations">', '')

    html = re.sub(r'(<b>)<span style="color:#8B008B">▪ <span>([IVXL]+)\.</span></span>(</b>)', r'\1<sup>\2</sup>\3', html)
    # Fix dates, only match exactly 3 or 4 digit years. This should turn "c 1500" into "c1500" or "? a 1300" into "?a1300".
    html = re.sub(r'<b>(\?)?\s?<i>([acp])</i> (\d{3,4})(\u2013\d{2})?</b>', r'<b>\1<i>\2</i>\3\4</b>', html)
    html = re.sub(
        r'(<b>(?:\?)?(?:<i>[acp]</i>)?(\d{3,4})(\u2013\d{2})?</b>)\s+([^\s<]+(?:\s+[^\s<]+)*?)\s+(?=in\s+<i>|<i>)',
        r'\1 <span class="author">\4</span> ',
        html
    )
    html = re.sub(
        r'(<span class="author">[^<]*</span>)\s+((?:in\s+)?<i>[^<]*</i>)',
        r'\1 <span class="title">\2</span>',
        html
    )
    html = re.sub( # Handle author + number reference pattern (like Ormin 9500)
        r'(<b>(?:\?)?(?:<i>[acp]</i>)?(\d{3,4})</b>)\s+([^\s<]+(?:\s+[^\s<]+)*)\s+(\d+)\s+<span style="color:#8B008B">',
        r'\1 <span class="author">\3</span> <span class="reference">\4</span> <span style="color:#8B008B">',
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
    # sometimes the 'forms' section is placed below its normal location and is preceded by a greek letter, e.g., "α", so we need to capture that too.
    html = re.sub(r'<blockquote>(\(<i>[\u03b1-\u03c9]</i>\).*?)</blockquote>', r'<div class="forms">\1</div>', html, flags=re.DOTALL)
    html = re.sub(r'<blockquote>([\u03b1-\u03c9]<sup>[0-9]</sup>.*?)</blockquote>', r'<div class="forms">\1</div>', html, flags=re.DOTALL) # greek letters

    # These are mini etymologies found for specific senses (i.e., not the main at the top of the entry).
    html = html.replace('<blockquote>[', '<div class="etymology">[')
    html = html.replace(']</blockquote>', ']</div>')

    html = html.replace('<span style="color:#8B008B">', '<span class="quotes">')
    html = re.sub(r'</span><b>(\??(<i>)?[acp0-9])', r'</span> <b>\1', html)

    html = re.sub(r'\{sup([a-z])\}', r'<span class="small-cap-letter">\1</span>', html)
    # Remove embedded styles and add classes to the spans
    html = re.sub(r'<span style="color:#4B0082">(\[?[0-9]+\.\]?)</span>', r'<span class="senses">\1</span>', html)
    html = re.sub(r'<span style="color:#4B0082">(\[?[a-z]\.\]?)</span>', r'<span class="subsenses">\1</span>', html)
    html = re.sub(r'<span style="color:#4B0082"><abr>(\[?[a-z]\.\]?)</abr></span>', r'<span class="subsenses">\1</span>', html)
    html = re.sub(r'<span style="color:#4B0082">(\[?[0-9]+\.\]?) (\[?[a-z]\.\]?)</span>', r'<span class="senses">\1</span> <span class="subsenses">\2</span>', html)
    html = re.sub(r'<span style="color:#4B0082">(\[?[IVXL]+\.\]?) (\[?[0-9]+\.\]?)</span>', r'<span class="major-division">\1</span> <span class="senses">\2</span>', html)
    html = re.sub(r'<span style="color:#4B0082">(\[?[IVXL]+\.\]?)</span>', r'<span class="major-division">\1</span>', html)
    html = re.sub(r'<span style="color:#4B0082">(\[?[A-Z]\.\]?)</span>', r'<span class="pos">\1</span>', html)

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
            'a': '\u00e1',  # á
            'e': '\u00e9',  # é
            'i': '\u00ed',  # í
            'o': '\u00f3',  # ó
            'u': '\u00fa'   # ú
        }
        return accent_map.get(letter, match.group(0))
    html = re.sub(r'\{([aeiou])acu\}', replace_acute, html)
    html = html.replace('{ddd}', '...')
    # Leap of faith here, but cross-referencing with the OED online, this seems to be in fact the case. Not sure why is missing though.
    html = re.sub(r'\u2013 [,\.]', f'\u2013 <b>{word}</b>.', html) # n-dash –

    html = html.replace('<abr>', '<span class="abbreviation">')
    html = html.replace('</abr>', '</span>')
    # Although we cannot fully restore all the original editorial minutiae, this pattern is reliable.
    # Authors presented as initial(s) + surname are always capitalised in the OED. However, other
    # names are capitalised as well, so this approach is not comprehensive. For example, "JOYCE"
    # (James Joyce) appears in uppercase but is presented as "JOYCE", not "J. JOYCE". see "other" sense 2 subsense f.
    def uppercase_author(match):
        first_initial, second_initial, surname = match.groups()
        second_initial = second_initial if second_initial else ''
        return f'<span class="author">{first_initial} {second_initial} {surname.upper()}</span>'
    html = re.sub(r'<span class="author">([A-Z]\.)\s*([A-Z]\.)?\s*([\w]+)</span>', uppercase_author, html)

    return html


def run_processing(input_tsv: Path, output_ifo_name: str):
    """ Reads a TSV file, splits homographs, processes the HTML of each part,
    and writes a new Stardict dictionary, preserving all metadata."""
    if not input_tsv.is_file():
        sys.exit(f"Error: Input TSV file not found at '{input_tsv}'")

    start_time = time.time()
    source_entry_count, split_entry_count, final_entry_count, malformed_lines, dotted_words, dot_corrected = 0, 0, 0, 0, 0, 0
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
                        print(f"    - Found metadata: '{key}' = '{value}'")
                        glos.setInfo(key, value)
                    continue # Move to the next line after processing metadata

                parts = line.split('\t', 1)
                if len(parts) != 2:
                    malformed_lines += 1
                    continue # Skip malformed lines

                source_entry_count += 1
                word, definition = parts
                unique_headwords.add(word)

                entry_word = word
                # Some of these seem to be legitimate entries, whilst others seem to have been added by a previous "editor"
                # I'm choosing to preserve them but we need to handle some quirks.
                if word.endswith('.'):
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
                            definition = ' ' + definition.split('\\n')[0]
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
                            entry = Entry(word=entry_word, defi=final_definition, defiFormat='h')
                            glos.addEntry(entry)
                            final_entry_count += 1
                else: # If no splits, process the HTML of the whole definition
                    processed_definition = process_html(definition, word)
                    headword_div = f'<span class="headword"><b>{word}</b></span>'
                    final_definition = headword_div + processed_definition
                    if re.search(r'<span class="headword"><b>[a-zA-Z\'\d \-\.]+</b></span><b>[a-zA-Z\u02C8\'\d \-\.]', final_definition): # \u02C8 is ˈ
                        # If the headword was already present, we don't need to prepend it, so remove it.
                        # Seems backwards to do it this way but it is much safer.
                        final_definition = final_definition.replace(headword_div, '', 1)
                        # Finally, wrap the headword in a span tag, to match the expected format.
                        final_definition = re.sub(r'<b>(.*?)</b>', r'<span class="headword"><b>\1</b></span>', final_definition, count=1)
                    entry = Entry(word=entry_word, defi=final_definition, defiFormat='h')
                    glos.addEntry(entry)
                    final_entry_count += 1

    except Exception as e:
        sys.exit(f"Error processing TSV file: {e}")

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
    args = parser.parse_args()
    run_processing(args.input_tsv, args.output_ifo)

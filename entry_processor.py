import re
import html as html_module
from bs4 import BeautifulSoup, Tag, FeatureNotFound

class EntryProcessor:
    """Encapsulates all HTML cleaning and processing for a single dictionary entry."""

    def __init__(self, html: str, headword: str):
        self.html = html
        self.headword = headword

    @staticmethod
    def _process_pos_forms_section(html: str) -> str:
        """Finds a 'forms' section demarcated by <span class="pos"> markers
        and wraps any unstyled sense/subsense blockquotes within that range."""
        try:
            soup = BeautifulSoup(html, 'lxml')
        except FeatureNotFound:
            soup = BeautifulSoup(html, 'html.parser')

        pos_spans = soup.find_all('span', class_='pos', limit=2)
        if len(pos_spans) < 2:
            return html

        start_node = pos_spans[0].find_parent('blockquote')
        # Check the trigger *before* doing more work.
        if start_node is None or 'forms' not in start_node.get_text(strip=True).lower():
            return html
        end_node = pos_spans[1].find_parent('blockquote')
        # Guard against invalid start/end nodes to prevent uncontrolled loops.
        if not end_node or start_node is end_node:
            return html

        # Collect all target nodes in a separate list before modifying the document,
        # we want to ensure we only wrap sections with actual forms in them.
        targets_to_wrap = []
        current_node = start_node
        while current_node and current_node != end_node:
            if (isinstance(current_node, Tag) and
                    current_node.name == 'blockquote' and not current_node.has_attr('class') and
                    current_node.find('span', class_=['senses', 'subsenses'])):

                if not current_node.find_parent(class_='forms'):
                    targets_to_wrap.append(current_node)

            current_node = current_node.find_next_sibling()

        # Safely iterate over the collected list to modify the soup object.
        for blockquote_node in targets_to_wrap:
            all_b_tags = blockquote_node.find_all('b')
            # Check for a 'content' <b> tag (one without a nested <span>).
            for b_tag in all_b_tags:
                if not b_tag.find('span'):
                    # If found, wrap the blockquote and stop checking this node.
                    wrapper_div = soup.new_tag('div', attrs={'class': 'forms'})
                    blockquote_node.wrap(wrapper_div)
                    break

        return str(soup)

    def process(self) -> str:
        """Runs the full suite of cleaning and formatting operations on the HTML."""
        html = self.html
        html = re.sub(r'<img[^>]+>', '', html)
        html = re.sub(r'\\n', ' ', html)
        html = re.sub(r'\\t', ' ', html)
        if self.headword.endswith('.'):
            html = html.replace('<abr>', '', 1)
            html = html.replace('</abr>', '', 1)

        html = re.sub(r'(<span>[IVXL]+\.</span></span></b>)\s*(<blockquote>)?(<b>.*?</b>)(</blockquote>)?', r'\1 <span class="headword">\3</span>', html, flags=re.DOTALL)
        html = re.sub(r'<blockquote>\(<span style="color:#2F4F4F">(.*?)</span>\)</blockquote>', r' (<span class="phonetic">\1</span>)', html, flags=re.DOTALL)
        html = re.sub(r'<span style="color:#2F4F4F">(.*?)</span>', r'<span class="phonetic">\1</span>', html, flags=re.DOTALL)

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
        html = re.sub(r'<b>(\?)?(\d{3,4})(\u2013\d{2})?</b>([^\s])', r'<b>\1\2\3</b> \4', html)
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
        html = re.sub(r'(<span class="author">[^<]*</span>)\s+((?:in\s+)?<i>[^<]*</i>)', r'\1 <span class="title">\2</span>', html)
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
        html = re.sub( # Handle year-digit + author (ex: <b>1925–6</b> E. Hemingway in <i>)
            r'(<b>(?:\?)?(?:<i>[acp]</i>\s?)?(\d{3,4})(?:[-–]\d{1,2})?</b>)\s+([A-Z]\.\s+[A-Z][a-z]+)\s+in\s+(<i>)',
            r'\1 <span class="author">\3</span> in \4',
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
        result, count = re.subn(r'\](</span>)</blockquote>', ']</span></blockquote></div> ', search_text, count=1)
        if count == 0:
            result = re.sub(r'\]</blockquote>', ']</blockquote></div> ', result, count=1)
        html = result + (html[stop_pos:] if stop_pos != -1 else '')
        # Not quite done yet, now add class to all other blockquotes inside the etymology block.
        def process_etymology(match):
            block = match.group(1)
            # Add indent class to all blockquotes
            block = re.sub(r'(</blockquote>)<blockquote>', r'\1<blockquote class="etymology-notes">', block)
            return f'<div class="etymology">{block}</div>'
        html = re.sub(r'<div class="etymology">(.*?)</div>', process_etymology, html, flags=re.S)

        # Heuristic approach to wrap in the forms section. note: there are multiple variations here so other forms sections found deep
        # into an entry might not be captured. HELP WANTED #fixme.
        html = re.sub(r'<blockquote>(Forms:?.*?)</blockquote>', r'<div class="forms">\1</div>', html, flags=re.DOTALL)
        html = re.sub(r'<blockquote>(?:<i>)?(Compared.*?)</blockquote>', r'<div class="forms">\1</div>', html, flags=re.DOTALL)
        html = re.sub(r'<blockquote>(Also [0-9].*?)</blockquote>', r'<div class="forms">\1</div>', html, flags=re.DOTALL)
        html = re.sub(r'<blockquote>(<abr>Pa.</abr>.*?)</blockquote>', r'<div class="forms">\1</div>', html, flags=re.DOTALL)
        html = re.sub(r'<blockquote>(Past and <abr>pple.</abr>.*?)</blockquote>', r'<div class="forms">\1</div>', html, flags=re.DOTALL)
        html = re.sub(r'<blockquote>(Pl. <b>.*?)</blockquote>', r'<div class="forms">\1</div>', html, flags=re.DOTALL)
        html = re.sub(r'<blockquote>(Usually in <abr>pl.</abr>.*?)</blockquote>', r'<div class="forms">\1</div>', html, flags=re.DOTALL)
        html = re.sub(r'<blockquote>(commonly in (?:<i>)?<abr>pl.</abr>.*?)</blockquote>', r'<div class="forms">\1</div>', html, flags=re.DOTALL)
        html = re.sub(r'<blockquote>(Inflected .*?)</blockquote>', r'<div class="forms">\1</div>', html, flags=re.DOTALL)
        # sometimes the 'forms' section is placed below its normal location and is preceded by a greek letter, e.g., "α", so we need to capture that too.
        html = re.sub(r'<blockquote>(\(<i>[\u03b1-\u03c9]</i>\).*?)</blockquote>', r'<div class="forms">\1</div>', html, flags=re.DOTALL)
        html = re.sub(r'<blockquote>([\u03b1-\u03c9]<sup>[0-9]</sup>.*?)</blockquote>', r'<div class="forms">\1</div>', html, flags=re.DOTALL) # greek letters

        # These are mini etymologies found for specific senses (i.e., not the main at the top of the entry).
        # Note: this needs rethinking, see issue #3
        # html = html.replace('<blockquote>[', '<blockquote class="etymology">[')
        # html = html.replace(']</blockquote>', ']</div>')

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
        html = re.sub(r'<span style="color:#4B0082">(\[?[0-9]+\.\]?) <abr>(\[?[a-z]\.\]?)</abr></span>', r'<span class="senses">\1</span> <span class="subsenses">\2</span>', html)
        html = re.sub(r'<span style="color:#4B0082">(\[?[IVXL]+\.\]?) (\[?[0-9]+\.\]?)</span>', r'<span class="major-division">\1</span> <span class="senses">\2</span>', html)
        html = re.sub(r'<span style="color:#4B0082">(\[?[IVXL]+\.\]?)</span>', r'<span class="major-division">\1</span>', html)
        html = re.sub(r'<span style="color:#4B0082">(\[?[A-Z]\.\]?)</span>', r'<span class="pos">\1</span>', html)
        html = re.sub(r'<span style="color:#4B0082">(\[?[A-Z]\.\]?) (\[?[IVXL]+\.\]?)</span>', r'<span class="pos">\1</span> <span class="major-division">\2</span>', html)
        html = re.sub(r'<span style="color:#4B0082">(\[?[A-Z]\.\]?) (\[?[0-9]+\.\]?)</span>', r'<span class="pos">\1</span> <span class="senses">\2</span>', html)

        if 'class="pos"' in html:
            html = self._process_pos_forms_section(html)

        # it is crazy how the mind forgets, why one does things ¯\_(ツ)_/¯, i believe this is here so main sections don't get turned into usage-notes.
        html = re.sub(r'</blockquote><blockquote>(\s*)(<b>)?<span class=', r'</blockquote><blockquote class="definition-partial">\1\2<span class=', html)
        html = re.sub(r'(_____</blockquote>)<blockquote>', r'\1<blockquote class="addendum">', html)
        html = re.sub(r'<blockquote>\*', '<blockquote class="subheading">*', html)
        # This seems to be introducing some false positives, see entry "in", but overall it follows the OED pattern,
        # so keeping it for now, however it might need to be revisited. #fixme.
        html = html.replace('</blockquote><blockquote>', '</blockquote><blockquote class="usage-note">')
        html = re.sub(r'(</blockquote></div>)(<blockquote><b><span class="major-division">)', r'\1 \2', html)
        html = html.replace('</blockquote></div><blockquote>', '</blockquote></div><blockquote class="usage-note">')

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
        html = html.replace('{p}', '\u02c8')  # ˈ (primary stress marker) see entry flat adv and n^3 12.b year 1901.
        html = html.replace('{ddd}', '...')
        html = html.replace('{oqq}', '\u201C')  # Left double quotation mark
        html = html.replace('{cqq}', '\u201D')  # Right double quotation mark
        html = html.replace('{nfced}', '\u00B8') # cedilla [squiggly bit only, which technically is what a cedilla is ;)]
        html = html.replace('{aacuced}', '\u00e1') # verified by og quote, see "id-al-adha" or issue #12
        html = html.replace('{pstlg}', '£')
        html = html.replace('{supg}', 'g') # odd one, seems to be just a regular 'g'
        html = html.replace('{ddag}', '‡')
        html = html.replace('{ruasper}', 'u\u0314') # u̔
        html = html.replace('{roasper}', 'o\u0314') # o̓
        html = html.replace('{nfasper}', '\u0314')
        html = html.replace('{egyasper}', '[egyasper]') # still needs revision, same as following line
        html = html.replace('{ormg}', '[ormg]') # OED shows it like this, hard to tell what it actually is at the moment. tracked in #12
        html = html.replace('{wlenisisub}', 'ᾠ')
        html = html.replace('{nfacu}', '´')
        html = html.replace('{nfgra}', 'ˋ')
        html = html.replace('{nfcirc}', 'ˆ')
        def replace_cedilla(match):
            letter = match.group(1)
            cedilla_map = {
                'a': 'a\u0327', # a̧
                'c': '\u00e7', # ç
                'C': '\u00c7', # Ç
                'S': '\u015e',
                'i': 'i\u0327', # see "Lamba" or issue https://github.com/Commodore64user/oed_prettifier/issues/12
                'd': 'd\u0327', # ḑ
                't': '\u0163', # ţ
                'z': 'z\u0327', # z̧
            }
            return cedilla_map.get(letter, match.group(0))
        html = re.sub(r'\{([actdzCS])ced\}', replace_cedilla, html)
        html = re.sub(r'⊇', 'e', html)
        # Leap of faith here, but cross-referencing with the OED online, this seems to be in fact the case. Not sure why is missing though.
        html = re.sub(r'\u2013 ([,;\.])', f'– <b>{html_module.escape(self.headword)}</b>' + r'\1', html)
        html = re.sub(r'([0-9]) ([,;\.])', r'\1' + f' <b>{html_module.escape(self.headword)}</b>' + r'\2', html)
        def replace_breve(match):
            letter = match.group(1)
            breve_map = {
                'c': 'c\u0306',   's': 's\u0306',  # s̆
                'y': 'y\u0306',   'A': '\u0102',   # Ă
                'z': 'z\u0306',   'G': '\u011e',   # Ğ
                'r': 'r\u0306',   'S': 'S\u0306',  # S̆
                'I': '\u012c',    'O': '\u014e',   # Ŏ
                'j': 'j\u0306',   'n': 'n\u0306',  # n̆
                'nf': '\u0306',   'ae': 'æ̆̆',
                # that 'sq' replacement IS supposed to be like that, don't undo it again silly...
                'go': '\u03bf\u0306',  'sq': '', # see issue https://github.com/Commodore64user/oed_prettifier/issues/12#issuecomment-3316062903
                'ymac': 'y\u0304\u0306',   'kmac': 'k\u0304\u0306',
                'oemac': '\u0153\u0304\u0306', #'gamac': 'FILLER_gamac_breve',
                'aemac': '\u00e6\u0304\u0306', 'ohook': '\u01eb\u0306',
            }
            return breve_map.get(letter, match.group(0))
        html = re.sub(r'\{([^}]+)breve\}', replace_breve, html)
        def replace_mac(match):
            letter = match.group(1)
            mac_map = {
                'g': 'g\u0304',   'n': 'n\u0304',
                'S': 'S\u0304',   'I': 'I\u0304',
                'z': 'z\u0304',   'w': 'w\u0304',
                'nf': '\u0304',   'oe': '\u0153\u0304',
                'gh': '\u03b7\u0304',    'Ae': '\u00c6\u0304',  # Ǣ
                'ope': '\u025b\u0304',   'revv': '\u028c\u0304',
                'revr': '\u0279\u0304',   'obar': '\u00f8\u0304',
                'ahook': 'ą̄̄̄',  'schwa': '\u0259\u0304',
                # 'shtsyll': '',   'rcircbl': '',
                'edotbl': 'e\u0323\u0304', 'odotbl': 'o\u0323\u0304',
                # 'alenis': '', 'ilenis': '', # no clue for either, seems like greek chars used in entries sun and exipotic
                'ibreve': 'i\u0304\u0306', 'obreve': 'o\u0304\u0306',
            }
            return mac_map.get(letter, match.group(0))
        html = re.sub(r'\{([^}]+)mac\}', replace_mac, html)
        def replace_bar(match):
            letter = match.group(1)
            bar_map = {
                'o': '\u00F8', # ø
                'L': '\u0141',
                'i': '\u0268',
                # 'p': '', # no clue either, see issue https://github.com/Commodore64user/oed_prettifier/issues/12
                'u': '\u0289',
                # 'th': '', # no idea what this is, see issue https://github.com/Commodore64user/oed_prettifier/issues/12
            }
            return bar_map.get(letter, match.group(0))
        html = re.sub(r'\{([^}]+)bar\}', replace_bar, html)

        html = re.sub(r'(<b>(?:\?)?(?:<i>[acp]</i>)?(\d{3,4})</b>) (<abr>tr\.</abr>)(\s<i>)', r'\1 <span class="translator">tr.</span>\4', html)
        # Handle "Author abbreviation." pattern (like "Francis tr.")
        html = re.sub(r'(<b>(?:\?)?(?:<i>[acp]</i>)?(\d{3,4})</b>) ((?:[\w]\.)?\s?[\w]+)\s(<abr>[\w]+\.</abr>)(\s<i>)', r'\1 <span class="author">\3</span> \4\5', html)
        # Handle specific "Initial Author (Source) Number" pattern
        html = re.sub(
            r'(<b>(?:\?)?(?:<i>[acp]</i>)?(?:\d{3,4})</b>) ([A-Z]\.)\s<abr>([\w]+\.)</abr>\s(\([^)]+\))\s([0-9]+)',
            r'\1 <span class="author">\2 \3</span> \4 \5',
            html
        )
        # handle authors with abbreviated names.
        html = re.sub(r'(<b>(?:\?)?(?:<i>[acp]</i>)?(?:\d{3,4})</b>) (<abr>[\w]+\.</abr>)\s([0-9]+)', r'\1 <span class="author">\2</span> \3', html)
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
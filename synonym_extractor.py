"""Provides the SynonymExtractor class for parsing and cleaning synonym data from dictionary HTML."""

import re
from bs4 import BeautifulSoup, Tag, FeatureNotFound

class SynonymExtractor:
    """Handles extraction and cleaning of synonyms from entry HTML."""
    SYNONYM_CLEANUP_MAP = {
        "†": "",   "*": "",   "ˈ": "",   "ˌ": "",   "(": "",   ")": "",   "[": "",   "]": "",   "‖": "",   "¶": "",   "?": "",   "!": "",
        "–": "",   "—": "",   ";": "",   ":": "",
    }

    IGNORED_SYN_WORDS = {'to', 'or', 'and', 'a', 'an', 'the', 'after', 'before', 'in', 'on', 'at', 'for', 'with', 'by', 'of', 'from', 'Derivatives.',
                         'that', 'which', 'who', 'whom', 'whose', 'as', 'than', 'like', 'such', 'so', 'but', 'if', 'when', 'up', 'down', 'Compounds.'}
    PAREN_PATTERN = re.compile(r'\(.*?\)')

    @staticmethod
    def _clean_synonym(text: str) -> str:
        """Removes unwanted characters from a potential synonym string."""
        text = SynonymExtractor.PAREN_PATTERN.sub('', text)
        for char, replacement in SynonymExtractor.SYNONYM_CLEANUP_MAP.items():
            text = text.replace(char, replacement)
        return text.strip()

    @staticmethod
    def _prepare_and_validate_synonym(headword: str, word_initial: str, final_synonym: str) -> str | None:
        if not final_synonym or final_synonym in SynonymExtractor.IGNORED_SYN_WORDS:
            return None
        if final_synonym.startswith('-') or final_synonym.endswith('-'):
            return None
        if re.search(r'\d{2,}', final_synonym):
            return None
        if re.fullmatch(r'[IVXL]+\.', final_synonym):
            return None
        if re.fullmatch(r'[A-Za-z]\.?', final_synonym):
            return None
        if re.fullmatch(r'[0-9]\.?', final_synonym):
            return None
        # Skip overly long multi-word synonyms (likely phrases rather than single synonyms)
        if len(final_synonym.split()) > 4:
            return None
        # some entries (e.g., plover) when creating compounds, use "p." as shorthands
        final_synonym = final_synonym.replace(word_initial + ".", headword)
        return final_synonym

    @staticmethod
    def extract(headword: str, html: str) -> list[str]:
        """Extracts potential synonyms from <b> tags within the definition HTML."""
        try:
            soup = BeautifulSoup(html, 'lxml')
        except FeatureNotFound:
            # If lxml fails, fall back to the more lenient, built-in parser.
            soup = BeautifulSoup(html, 'html.parser')
        cleaned_syns = set()

        clean_headword = SynonymExtractor._clean_synonym(headword.strip())
        if not clean_headword:
            return []
        word_initial = clean_headword[:1]

        # Find and remove all quotation divs from the parse tree.
        for div in soup.find_all('div', class_='quotations'):
            div.decompose()

        # Also remove isolated roman-numeral markers like <b><sup>IV</sup></b>
        for sup in soup.find_all('sup'):
            if sup.parent and sup.parent.name == 'b':
                sup.decompose()

        # Categorize all <b> tags into strict or lax processing sets.
        lax_tags = set()
        strict_tags = set()

        pos_blocks = []
        for tag in soup.find_all('span', class_='pos'):
            parent_block = tag.find_parent('blockquote')
            if parent_block:
                pos_blocks.append(parent_block)
        if pos_blocks and 'forms' in pos_blocks[0].get_text(strip=True).lower():
            start_node = pos_blocks[0]
            end_node = pos_blocks[1] if len(pos_blocks) > 1 else None

            current_node = start_node
            while current_node:
                current_node = current_node.find_next_sibling()
                if not current_node or current_node == end_node:
                    break
                if isinstance(current_node, Tag):
                    lax_tags.update(current_node.find_all('b'))

        all_b_tags = set(soup.find_all('b'))
        remaining_tags = all_b_tags - lax_tags

        strict_blocks = set()
        for marker in soup.find_all('span', class_=['senses', 'subsenses']):
            parent_block = marker.find_parent('blockquote')
            if parent_block:
                strict_blocks.add(parent_block)
        if lax_tags and pos_blocks:
            strict_blocks.discard(pos_blocks[0])

        all_tags_in_strict_blocks = set()
        for block in strict_blocks:
            if block:
                all_tags_in_strict_blocks.update(block.find_all('b'))

        strict_tags = remaining_tags.intersection(all_tags_in_strict_blocks)
        lax_tags.update(remaining_tags - strict_tags)

        # Process tags that require the strict headword-containment check.
        for tag in strict_tags:
            synonym_text = SynonymExtractor._clean_synonym(tag.get_text())
            validated = SynonymExtractor._prepare_and_validate_synonym(clean_headword, word_initial, synonym_text)

            # Apply the special rule: keep only if it contains the headword
            if validated and clean_headword.lower() in validated.lower():
                cleaned_syns.add(validated)

        # Process all tags that require lax validation.
        for tag in lax_tags:
            synonym_text = SynonymExtractor._clean_synonym(tag.get_text())
            validated = SynonymExtractor._prepare_and_validate_synonym(clean_headword, word_initial, synonym_text)
            if validated:
                cleaned_syns.add(validated)

        cleaned_syns.discard(clean_headword)
        return sorted(list(cleaned_syns))
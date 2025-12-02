import re
import pandas as pd
from typing import Dict, List, Tuple, Optional

class PharmaceuticalNameParser:
    """
    Parse and normalize pharmaceutical product names.
    Extracts: brand, generic, dosage, form, pack size.
    """

    # Common dosage units
    DOSAGE_UNITS = [
        'MG', 'GM', 'G', 'ML', 'MCG', 'IU', 'UNIT', 'UNITS',
        'MICROGRAM', 'MILLIGRAM', 'GRAM', 'MILLILITRE', 'LITRE'
    ]

    # Pharmaceutical forms
    FORMS = [
        'TAB', 'TABS', 'TABLET', 'TABLETS',
        'CAP', 'CAPS', 'CAPSULE', 'CAPSULES',
        'SYRUP', 'SUSPENSION', 'SUSP', 'DROPS',
        'INJ', 'INJECTION', 'CREAM', 'OINTMENT', 'GEL',
        'LOTION', 'SPRAY', 'POWDER', 'SACHET', 'SACHETS',
        'SOLUTION', 'SOL', 'AMPOULE', 'AMP', 'VIAL',
        'SUPPOSITORY', 'SUPP', 'PESSARY'
    ]

    # Common abbreviations in pharmaceutical names
    ABBREVIATIONS = {
        'CAL': 'CALCIUM',
        'MAG': 'MAGNESIUM',
        'VIT': 'VITAMIN',
        'PARACET': 'PARACETAMOL',
        'P-MOL': 'PARACETAMOL',
        'PMOL': 'PARACETAMOL',
        'IBUPROF': 'IBUPROFEN',
        'DICLO': 'DICLOFENAC',
        'AMOXI': 'AMOXICILLIN',
        'AMOX': 'AMOXICILLIN',
        'CEFU': 'CEFUROXIME',
        'CEFURO': 'CEFUROXIME',
        'CLAV': 'CLAVULANIC',
        'ATORVA': 'ATORVASTATIN',
        'ROSUVA': 'ROSUVASTATIN',
        'MONTE': 'MONTELUKAST',
        'LEVO': 'LEVOCETIRIZINE',
        'CETIRIZ': 'CETIRIZINE',
        'CETIRI': 'CETIRIZINE',
        'LORA': 'LORATADINE',
        'DEXA': 'DEXAMETHASONE',
        'PRED': 'PREDNISOLONE',
        'HYDRO': 'HYDROCORTISONE',
        'DECONGEST': 'DECONGESTANT',
        'ANTIHISTAM': 'ANTIHISTAMINE',
        'SUPPL': 'SUPPLEMENT',
        'MULTIVIT': 'MULTIVITAMIN',
    }

    # Stopwords to remove from matching (but keep for display)
    STOPWORDS = {
        'THE', 'AND', 'WITH', 'FOR', 'PLUS', 'NEW', 'ADVANCED',
        'EXTRA', 'SUPER', 'MAXIMUM', 'ORIGINAL', 'REGULAR',
    }

    def __init__(self):
        # Compile regex patterns for performance
        self.dosage_pattern = re.compile(
            r'(\d+(?:\.\d+)?)\s*(' + '|'.join(self.DOSAGE_UNITS) + r')',
            re.IGNORECASE
        )
        self.pack_pattern = re.compile(r'(\d+)\s*[\'S]?\s*$', re.IGNORECASE)
        self.form_pattern = re.compile(
            r'\b(' + '|'.join(self.FORMS) + r')[S]?\b',
            re.IGNORECASE
        )

    def clean_basic(self, text: str) -> str:
        """Basic cleaning: uppercase, remove punctuation, collapse spaces."""
        if pd.isna(text):
            return ""
        s = str(text).upper()
        # Remove common punctuation but keep + for formulations
        for ch in ["*", ",", ".", "-", "/", "(", ")", "%", "'", '"', "&"]:
            s = s.replace(ch, " ")
        s = " ".join(s.split())
        return s

    def expand_abbreviations(self, text: str) -> str:
        """Expand common pharmaceutical abbreviations."""
        words = text.split()
        expanded = []
        for word in words:
            expanded.append(self.ABBREVIATIONS.get(word, word))
        return " ".join(expanded)

    def extract_dosage(self, text: str) -> List[str]:
        """Extract all dosages from text (e.g., ['500MG', '10ML'])."""
        matches = self.dosage_pattern.findall(text)
        return [f"{num}{unit}".upper() for num, unit in matches]

    def extract_pack_size(self, text: str) -> Optional[str]:
        """Extract pack size from end of text (e.g., '30S', '100ML')."""
        match = self.pack_pattern.search(text)
        if match:
            return match.group(1)
        return None

    def extract_form(self, text: str) -> Optional[str]:
        """Extract pharmaceutical form (e.g., 'TAB', 'CAP', 'SYRUP')."""
        match = self.form_pattern.search(text)
        if match:
            form = match.group(1).upper()
            # Normalize plural forms
            if form.endswith('S') and form[:-1] in ['TAB', 'CAP', 'SACHET']:
                return form[:-1]
            return form
        return None

    def tokenize_smart(self, text: str) -> Dict[str, any]:
        """
        Smart tokenization for pharmaceutical names.
        Returns dict with: tokens, dosages, form, pack_size, clean_text
        """
        clean = self.clean_basic(text)
        expanded = self.expand_abbreviations(clean)

        # Extract components
        dosages = self.extract_dosage(expanded)
        form = self.extract_form(expanded)
        pack_size = self.extract_pack_size(expanded)

        # Remove dosages, form, pack size from tokens for name matching
        working = expanded
        for dosage in dosages:
            working = working.replace(dosage, '')
        if form:
            working = re.sub(r'\b' + re.escape(form) + r'[S]?\b', '', working, flags=re.IGNORECASE)
        if pack_size:
            working = re.sub(r'\b' + pack_size + r'\s*[\'S]?\s*$', '', working)

        # Filter stopwords for matching (keep important words)
        tokens = [w for w in working.split() if w and w not in self.STOPWORDS]

        return {
            'tokens': tokens,
            'dosages': dosages,
            'form': form,
            'pack_size': pack_size,
            'clean_text': ' '.join(tokens),
            'full_clean': expanded
        }

    def normalize_form(self, form: Optional[str]) -> Optional[str]:
        """Normalize form to standard (e.g., TABLETS -> TAB)."""
        if not form:
            return None
        form = form.upper()

        form_map = {
            'TABLETS': 'TAB', 'TABLET': 'TAB', 'TABS': 'TAB',
            'CAPSULES': 'CAP', 'CAPSULE': 'CAP', 'CAPS': 'CAP',
            'SUSPENSION': 'SUSP', 'INJECTION': 'INJ',
            'SOLUTION': 'SOL', 'AMPOULE': 'AMP',
            'SUPPOSITORY': 'SUPP', 'SACHETS': 'SACHET'
        }

        return form_map.get(form, form)


class PhoneticMatcher:
    """
    Phonetic matching for brand names (handles typos and variations).
    Uses a simplified Soundex-like algorithm.
    """

    @staticmethod
    def soundex(text: str) -> str:
        """Generate simplified soundex code for pharmaceutical names."""
        if not text:
            return ""

        text = text.upper()
        # Keep first letter
        code = text[0]

        # Map letters to phonetic codes
        mapping = {
            'B': '1', 'F': '1', 'P': '1', 'V': '1',
            'C': '2', 'G': '2', 'J': '2', 'K': '2', 'Q': '2', 'S': '2', 'X': '2', 'Z': '2',
            'D': '3', 'T': '3',
            'L': '4',
            'M': '5', 'N': '5',
            'R': '6'
        }

        prev_code = ''
        for char in text[1:]:
            code_char = mapping.get(char, '0')
            if code_char != '0' and code_char != prev_code:
                code += code_char
                prev_code = code_char

        # Pad or trim to 4 characters
        return (code + '000')[:4]

    @staticmethod
    def phonetic_similarity(text1: str, text2: str) -> float:
        """
        Compare two texts using phonetic encoding.
        Returns similarity score 0-1.
        """
        if not text1 or not text2:
            return 0.0

        # Split into words and compare soundex codes
        words1 = text1.upper().split()
        words2 = text2.upper().split()

        if not words1 or not words2:
            return 0.0

        # Compare soundex codes
        codes1 = [PhoneticMatcher.soundex(w) for w in words1]
        codes2 = [PhoneticMatcher.soundex(w) for w in words2]

        # Count matching codes
        matches = sum(1 for c1 in codes1 if c1 in codes2)

        return matches / max(len(codes1), len(codes2))


def levenshtein_distance(s1: str, s2: str) -> int:
    """Calculate Levenshtein (edit) distance between two strings."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            # j+1 instead of j since previous_row and current_row are one character longer
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def levenshtein_similarity(s1: str, s2: str) -> float:
    """Convert Levenshtein distance to similarity score (0-1)."""
    if not s1 or not s2:
        return 0.0

    distance = levenshtein_distance(s1, s2)
    max_len = max(len(s1), len(s2))

    if max_len == 0:
        return 1.0

    return 1.0 - (distance / max_len)


def jaccard_similarity(tokens1: List[str], tokens2: List[str]) -> float:
    """Calculate Jaccard similarity between two token sets."""
    if not tokens1 or not tokens2:
        return 0.0

    set1 = set(tokens1)
    set2 = set(tokens2)

    intersection = len(set1 & set2)
    union = len(set1 | set2)

    if union == 0:
        return 0.0

    return intersection / union

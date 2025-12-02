import pandas as pd
import numpy as np
from difflib import SequenceMatcher
from typing import Dict, List, Tuple, Optional
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import warnings
warnings.filterwarnings('ignore')

from modules.pharmaceutical_utils import (
    PharmaceuticalNameParser,
    PhoneticMatcher,
    levenshtein_similarity,
    jaccard_similarity
)


class AdvancedPharmaceuticalMatcher:
    """
    Elite multi-algorithm ensemble matcher for pharmaceutical products.
    Combines 5 different matching strategies with intelligent weighting.
    """

    def __init__(self, master_df: pd.DataFrame):
        """
        Initialize matcher with master product list.

        Args:
            master_df: DataFrame with columns: Item Code, Item Name, CleanName, etc.
        """
        self.master = master_df.copy()
        self.parser = PharmaceuticalNameParser()
        self.phonetic = PhoneticMatcher()

        # Preprocess master list
        self._preprocess_master()

        # Build TF-IDF vectorizer on master list
        self._build_tfidf()

    def _preprocess_master(self):
        """Preprocess master list: tokenize and extract components."""
        print("Preprocessing master list...")

        parsed_data = []
        for idx, row in self.master.iterrows():
            item_name = row.get('Item Name', '')
            parsed = self.parser.tokenize_smart(item_name)
            parsed_data.append(parsed)

        # Add parsed columns to master
        self.master['Tokens'] = [p['tokens'] for p in parsed_data]
        self.master['Dosages'] = [p['dosages'] for p in parsed_data]
        self.master['Form'] = [p['form'] for p in parsed_data]
        self.master['PackSize'] = [p['pack_size'] for p in parsed_data]
        self.master['CleanTokens'] = [p['clean_text'] for p in parsed_data]
        self.master['FullClean'] = [p['full_clean'] for p in parsed_data]

        print(f"Preprocessed {len(self.master)} master items.")

    def _build_tfidf(self):
        """Build TF-IDF vectorizer on master product names."""
        print("Building TF-IDF index...")

        # Use clean token text for TF-IDF
        corpus = self.master['CleanTokens'].fillna('').tolist()

        # Build TF-IDF with character n-grams for fuzzy matching
        self.tfidf = TfidfVectorizer(
            ngram_range=(1, 3),  # Word unigrams, bigrams, trigrams
            analyzer='char_wb',  # Character n-grams within word boundaries
            lowercase=True,
            min_df=1
        )

        self.tfidf_matrix = self.tfidf.fit_transform(corpus)
        print(f"TF-IDF index built with {self.tfidf_matrix.shape[1]} features.")

    def _compute_similarity_scores(
        self,
        invoice_parsed: Dict,
        candidate_row: pd.Series
    ) -> Dict[str, float]:
        """
        Compute 5 different similarity scores for a candidate.

        Returns:
            Dict with: sequence_match, tfidf_score, phonetic_score,
                      jaccard_score, levenshtein_score, component_bonus
        """
        inv_tokens = invoice_parsed['tokens']
        inv_dosages = invoice_parsed['dosages']
        inv_form = invoice_parsed['form']
        inv_clean = invoice_parsed['clean_text']
        inv_full = invoice_parsed['full_clean']

        cand_tokens = candidate_row['Tokens']
        cand_dosages = candidate_row['Dosages']
        cand_form = candidate_row['Form']
        cand_clean = candidate_row['CleanTokens']
        cand_full = candidate_row['FullClean']

        scores = {}

        # 1. Sequence Matcher (basic fuzzy)
        scores['sequence_match'] = SequenceMatcher(None, inv_full, cand_full).ratio()

        # 2. Levenshtein similarity
        scores['levenshtein'] = levenshtein_similarity(inv_clean, cand_clean)

        # 3. Jaccard (token overlap)
        scores['jaccard'] = jaccard_similarity(inv_tokens, cand_tokens)

        # 4. Phonetic similarity (good for brand names)
        scores['phonetic'] = self.phonetic.phonetic_similarity(inv_clean, cand_clean)

        # 5. Component matching bonuses
        component_bonus = 0.0

        # Exact dosage match bonus (critical!)
        if inv_dosages and cand_dosages:
            dosage_matches = sum(1 for d in inv_dosages if d in cand_dosages)
            if dosage_matches > 0:
                component_bonus += 0.3 * (dosage_matches / max(len(inv_dosages), len(cand_dosages)))

        # Form match bonus
        if inv_form and cand_form:
            inv_form_norm = self.parser.normalize_form(inv_form)
            cand_form_norm = self.parser.normalize_form(cand_form)
            if inv_form_norm == cand_form_norm:
                component_bonus += 0.1

        scores['component_bonus'] = min(component_bonus, 0.4)  # Cap at 0.4

        return scores

    def find_candidates_tfidf(
        self,
        invoice_text: str,
        top_k: int = 10
    ) -> List[int]:
        """
        Use TF-IDF to find top-K candidates quickly.

        Args:
            invoice_text: Cleaned invoice item name
            top_k: Number of candidates to return

        Returns:
            List of master DataFrame indices
        """
        # Parse invoice text
        parsed = self.parser.tokenize_smart(invoice_text)
        query_text = parsed['clean_text']

        if not query_text:
            return []

        # Transform query to TF-IDF
        query_vec = self.tfidf.transform([query_text])

        # Compute cosine similarity
        similarities = cosine_similarity(query_vec, self.tfidf_matrix).flatten()

        # Get top-K indices
        top_indices = similarities.argsort()[-top_k:][::-1]

        return top_indices.tolist()

    def compute_final_score(
        self,
        name_scores: Dict[str, float],
        supplier_score: float,
        mrp_score: float,
        cost_score: float,
        has_mrp: bool
    ) -> float:
        """
        Compute final weighted score with dynamic weight redistribution.

        Args:
            name_scores: Dict of individual name matching scores
            supplier_score: Supplier history score (0-1)
            mrp_score: MRP matching score (0-1)
            cost_score: Cost sanity score (0-1)
            has_mrp: Whether invoice has MRP data

        Returns:
            Final score (0-1)
        """
        # Ensemble name score (weighted average of 5 algorithms)
        name_score = (
            0.25 * name_scores['sequence_match'] +
            0.20 * name_scores['levenshtein'] +
            0.20 * name_scores['jaccard'] +
            0.15 * name_scores['phonetic'] +
            0.20 * name_scores['component_bonus']
        )

        # Dynamic weight redistribution based on MRP availability
        if has_mrp:
            # Standard weights when MRP available
            final_score = (
                0.45 * name_score +        # Increased name importance
                0.25 * supplier_score +
                0.20 * mrp_score +
                0.10 * cost_score
            )
        else:
            # Redistribute MRP weight when not available
            final_score = (
                0.55 * name_score +        # 0.45 + (0.20 * 0.5) redistribution
                0.30 * supplier_score +    # 0.25 + (0.20 * 0.25) redistribution
                0.15 * cost_score          # 0.10 + (0.20 * 0.25) redistribution
            )

        return final_score

    def match_item(
        self,
        invoice_name: str,
        supplier_clean: str,
        effective_unit_price: Optional[float],
        mrp_invoice_adj: Optional[float],
        last_purchase_global_idx: pd.DataFrame,
        last_purchase_by_supplier_idx: pd.DataFrame,
        top_k: int = 10
    ) -> Dict:
        """
        Find best match for an invoice item using elite multi-algorithm approach.

        Args:
            invoice_name: Raw invoice item name
            supplier_clean: Cleaned supplier name
            effective_unit_price: Effective cost per unit (after bonuses)
            mrp_invoice_adj: MRP from invoice (VAT-adjusted)
            last_purchase_global_idx: Purchase history (global)
            last_purchase_by_supplier_idx: Purchase history (by supplier)
            top_k: Number of candidates to consider

        Returns:
            Dict with match results
        """
        # Parse invoice name
        invoice_parsed = self.parser.tokenize_smart(invoice_name)

        # Get top-K candidates using TF-IDF
        candidate_indices = self.find_candidates_tfidf(invoice_name, top_k=top_k)

        if not candidate_indices:
            return self._empty_result()

        best = {
            'item_code': None,
            'item_name': None,
            'mrp_master': None,
            'name_scores': {},
            'supplier_score': 0.0,
            'mrp_score': 0.0,
            'cost_score': 0.0,
            'final_score': -1.0,
            'last_sup': '',
            'last_date': '',
            'last_rate': '',
            'has_mrp': False,
            'match_details': ''
        }

        # Evaluate each candidate
        for idx in candidate_indices:
            candidate = self.master.loc[idx]

            # Compute name similarity scores
            name_scores = self._compute_similarity_scores(invoice_parsed, candidate)

            # Compute supplier score
            supplier_score = self._compute_supplier_score(
                candidate['CleanName'],
                supplier_clean,
                last_purchase_global_idx,
                last_purchase_by_supplier_idx
            )

            # Compute MRP score
            has_mrp = (
                mrp_invoice_adj is not None
                and candidate.get('MRP_Master') is not None
                and not pd.isna(candidate.get('MRP_Master'))
            )
            mrp_score = self._compute_mrp_score(
                mrp_invoice_adj,
                candidate.get('MRP_Master')
            ) if has_mrp else 0.0

            # Compute cost score
            cost_score = self._compute_cost_score(
                effective_unit_price,
                candidate.get('B.Rate')
            )

            # Compute final score
            final_score = self.compute_final_score(
                name_scores,
                supplier_score,
                mrp_score,
                cost_score,
                has_mrp
            )

            # Update best if this is better
            if final_score > best['final_score']:
                # Get purchase history
                last_sup_row, last_global_row = self._get_purchase_history(
                    candidate['CleanName'],
                    supplier_clean,
                    last_purchase_global_idx,
                    last_purchase_by_supplier_idx
                )

                lp_row = last_sup_row if last_sup_row is not None else last_global_row

                best.update({
                    'item_code': candidate['Item Code'],
                    'item_name': candidate['Item Name'],
                    'mrp_master': candidate.get('MRP_Master'),
                    'name_scores': name_scores,
                    'supplier_score': supplier_score,
                    'mrp_score': mrp_score,
                    'cost_score': cost_score,
                    'final_score': final_score,
                    'has_mrp': has_mrp,
                    'last_sup': lp_row.get('Supplier', '') if lp_row is not None else '',
                    'last_date': lp_row.get('Date.', '') if lp_row is not None else '',
                    'last_rate': lp_row.get('P.Rate', '') if lp_row is not None else '',
                    'match_details': self._format_match_details(name_scores)
                })

        return best

    def _compute_supplier_score(
        self,
        clean_name: str,
        supplier_clean: str,
        last_purchase_global_idx: pd.DataFrame,
        last_purchase_by_supplier_idx: pd.DataFrame
    ) -> float:
        """Compute supplier history score."""
        # Check supplier-specific history
        key_sup = (clean_name, supplier_clean)
        if key_sup in last_purchase_by_supplier_idx.index:
            return 1.0

        # Check global history
        if clean_name in last_purchase_global_idx.index:
            return 0.5

        return 0.0

    def _get_purchase_history(
        self,
        clean_name: str,
        supplier_clean: str,
        last_purchase_global_idx: pd.DataFrame,
        last_purchase_by_supplier_idx: pd.DataFrame
    ) -> Tuple[Optional[pd.Series], Optional[pd.Series]]:
        """Get purchase history rows."""
        last_sup_row = None
        last_global_row = None

        key_sup = (clean_name, supplier_clean)
        if key_sup in last_purchase_by_supplier_idx.index:
            last_sup_row = last_purchase_by_supplier_idx.loc[key_sup]

        if clean_name in last_purchase_global_idx.index:
            last_global_row = last_purchase_global_idx.loc[clean_name]

        return last_sup_row, last_global_row

    def _compute_mrp_score(
        self,
        mrp_invoice_adj: Optional[float],
        mrp_master: Optional[float]
    ) -> float:
        """Compute MRP similarity score."""
        try:
            mi = float(mrp_invoice_adj)
            mm = float(mrp_master)
            if mi <= 0 or mm <= 0:
                return 0.0
        except (TypeError, ValueError):
            return 0.0

        rel_diff = abs(mi - mm) / max(mi, mm)
        score = max(0.0, 1.0 - rel_diff * 3)
        return score

    def _compute_cost_score(
        self,
        effective_unit_price: Optional[float],
        pos_brate: Optional[float]
    ) -> float:
        """Compute cost sanity score."""
        try:
            inv = float(effective_unit_price)
            last = float(pos_brate)
            if inv <= 0 or last <= 0:
                return 0.0
        except (TypeError, ValueError):
            return 0.0

        ratio = inv / last
        delta = abs(ratio - 1.0)

        # within ±10% -> 1.0
        if delta <= 0.10:
            return 1.0
        # within ±40% -> 0.5
        if delta <= 0.40:
            return 0.5
        return 0.0

    def _format_match_details(self, name_scores: Dict[str, float]) -> str:
        """Format match details for explainability."""
        return (
            f"Seq:{name_scores['sequence_match']:.2f} "
            f"Lev:{name_scores['levenshtein']:.2f} "
            f"Jac:{name_scores['jaccard']:.2f} "
            f"Pho:{name_scores['phonetic']:.2f} "
            f"Cmp:{name_scores['component_bonus']:.2f}"
        )

    def _empty_result(self) -> Dict:
        """Return empty result when no match found."""
        return {
            'item_code': None,
            'item_name': None,
            'mrp_master': None,
            'name_scores': {},
            'supplier_score': 0.0,
            'mrp_score': 0.0,
            'cost_score': 0.0,
            'final_score': 0.0,
            'last_sup': '',
            'last_date': '',
            'last_rate': '',
            'has_mrp': False,
            'match_details': ''
        }

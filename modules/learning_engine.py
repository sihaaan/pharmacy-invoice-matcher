import sqlite3
import pandas as pd
from typing import Dict, Optional, List, Tuple
from datetime import datetime
import os


class LearningEngine:
    """
    Learning engine that stores and applies human corrections.
    Builds intelligence over time by learning from user feedback.
    """

    def __init__(self, db_path: str = "data/learned_mappings.db"):
        """
        Initialize learning engine with SQLite database.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._ensure_database()

    def _ensure_database(self):
        """Create database and tables if they don't exist."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Table for learned mappings
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS learned_mappings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_pattern TEXT NOT NULL,
                invoice_pattern_clean TEXT NOT NULL,
                supplier_pattern TEXT,
                master_item_code TEXT NOT NULL,
                master_item_name TEXT NOT NULL,
                confidence REAL NOT NULL,
                learned_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                times_seen INTEGER DEFAULT 1,
                times_confirmed INTEGER DEFAULT 1,
                last_confirmed TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Index for fast lookup
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_invoice_pattern
            ON learned_mappings(invoice_pattern_clean, supplier_pattern)
        """)

        # Table for correction history (audit trail)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS correction_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_no TEXT,
                line_no TEXT,
                invoice_item_name TEXT NOT NULL,
                supplier_name TEXT,
                suggested_item_code TEXT,
                suggested_item_name TEXT,
                suggested_score REAL,
                corrected_item_code TEXT NOT NULL,
                corrected_item_name TEXT NOT NULL,
                correction_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                correction_reason TEXT
            )
        """)

        conn.commit()
        conn.close()

    def lookup_learned_mapping(
        self,
        invoice_name_clean: str,
        supplier_clean: Optional[str] = None,
        min_confidence: float = 0.75
    ) -> Optional[Dict]:
        """
        Look up a learned mapping for an invoice item.

        Args:
            invoice_name_clean: Cleaned invoice item name
            supplier_clean: Cleaned supplier name (optional)
            min_confidence: Minimum confidence threshold

        Returns:
            Dict with learned mapping or None
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Try exact match with supplier first
        if supplier_clean:
            cursor.execute("""
                SELECT master_item_code, master_item_name, confidence,
                       times_seen, times_confirmed
                FROM learned_mappings
                WHERE invoice_pattern_clean = ?
                  AND (supplier_pattern = ? OR supplier_pattern IS NULL)
                  AND confidence >= ?
                ORDER BY supplier_pattern IS NOT NULL DESC, confidence DESC
                LIMIT 1
            """, (invoice_name_clean, supplier_clean, min_confidence))
        else:
            cursor.execute("""
                SELECT master_item_code, master_item_name, confidence,
                       times_seen, times_confirmed
                FROM learned_mappings
                WHERE invoice_pattern_clean = ?
                  AND confidence >= ?
                ORDER BY confidence DESC
                LIMIT 1
            """, (invoice_name_clean, min_confidence))

        row = cursor.fetchone()
        conn.close()

        if row:
            return {
                'item_code': row[0],
                'item_name': row[1],
                'confidence': row[2],
                'times_seen': row[3],
                'times_confirmed': row[4],
                'learned': True
            }

        return None

    def add_learned_mapping(
        self,
        invoice_pattern: str,
        invoice_pattern_clean: str,
        master_item_code: str,
        master_item_name: str,
        supplier_pattern: Optional[str] = None,
        confidence: float = 0.85
    ):
        """
        Add or update a learned mapping.

        Args:
            invoice_pattern: Original invoice pattern
            invoice_pattern_clean: Cleaned invoice pattern
            master_item_code: Master item code to map to
            master_item_name: Master item name
            supplier_pattern: Supplier pattern (optional)
            confidence: Confidence score (0-1)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Check if mapping already exists
        cursor.execute("""
            SELECT id, times_seen, times_confirmed
            FROM learned_mappings
            WHERE invoice_pattern_clean = ?
              AND master_item_code = ?
              AND (supplier_pattern = ? OR (supplier_pattern IS NULL AND ? IS NULL))
        """, (invoice_pattern_clean, master_item_code, supplier_pattern, supplier_pattern))

        existing = cursor.fetchone()

        if existing:
            # Update existing mapping
            mapping_id, times_seen, times_confirmed = existing
            new_times_confirmed = times_confirmed + 1
            new_times_seen = times_seen + 1

            # Increase confidence with more confirmations
            new_confidence = min(0.98, confidence + (new_times_confirmed * 0.01))

            cursor.execute("""
                UPDATE learned_mappings
                SET times_seen = ?,
                    times_confirmed = ?,
                    confidence = ?,
                    last_confirmed = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (new_times_seen, new_times_confirmed, new_confidence, mapping_id))

        else:
            # Insert new mapping
            cursor.execute("""
                INSERT INTO learned_mappings
                (invoice_pattern, invoice_pattern_clean, supplier_pattern,
                 master_item_code, master_item_name, confidence)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (invoice_pattern, invoice_pattern_clean, supplier_pattern,
                  master_item_code, master_item_name, confidence))

        conn.commit()
        conn.close()

    def record_correction(
        self,
        invoice_no: str,
        line_no: str,
        invoice_item_name: str,
        supplier_name: str,
        suggested_item_code: str,
        suggested_item_name: str,
        suggested_score: float,
        corrected_item_code: str,
        corrected_item_name: str,
        correction_reason: Optional[str] = None
    ):
        """
        Record a user correction in the audit trail.

        Args:
            invoice_no: Invoice number
            line_no: Line number
            invoice_item_name: Invoice item name
            supplier_name: Supplier name
            suggested_item_code: What the system suggested
            suggested_item_name: Suggested item name
            suggested_score: System's confidence score
            corrected_item_code: What the user corrected it to
            corrected_item_name: Corrected item name
            correction_reason: Optional reason for correction
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO correction_history
            (invoice_no, line_no, invoice_item_name, supplier_name,
             suggested_item_code, suggested_item_name, suggested_score,
             corrected_item_code, corrected_item_name, correction_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (invoice_no, line_no, invoice_item_name, supplier_name,
              suggested_item_code, suggested_item_name, suggested_score,
              corrected_item_code, corrected_item_name, correction_reason))

        conn.commit()
        conn.close()

    def process_corrections_file(
        self,
        corrections_file: str,
        master_df: pd.DataFrame,
        clean_func
    ) -> int:
        """
        Process a corrections Excel file and learn from it.

        Expected columns in corrections file:
        - Invoice_No
        - Line_No
        - Invoice_Item_Name
        - Supplier_Name
        - Suggested_Item_Code (what system suggested)
        - Suggested_Item_Name
        - Final_Score
        - Corrected_Item_Code (what user says is correct)
        - Notes (optional)

        Args:
            corrections_file: Path to corrections Excel file
            master_df: Master product DataFrame
            clean_func: Function to clean text

        Returns:
            Number of corrections processed
        """
        if not os.path.exists(corrections_file):
            print(f"Corrections file not found: {corrections_file}")
            return 0

        try:
            corrections = pd.read_excel(corrections_file)
        except Exception as e:
            print(f"Error reading corrections file: {e}")
            return 0

        # Validate required columns
        required_cols = ['Invoice_Item_Name', 'Suggested_Item_Code', 'Corrected_Item_Code']
        missing = [c for c in required_cols if c not in corrections.columns]
        if missing:
            print(f"Missing required columns: {missing}")
            return 0

        # Filter only rows with corrections (where corrected != suggested)
        corrections = corrections[
            corrections['Corrected_Item_Code'].notna() &
            (corrections['Corrected_Item_Code'] != corrections['Suggested_Item_Code'])
        ].copy()

        if corrections.empty:
            print("No corrections found in file.")
            return 0

        count = 0
        for _, row in corrections.iterrows():
            invoice_name = row['Invoice_Item_Name']
            supplier_name = row.get('Supplier_Name', '')
            corrected_code = row['Corrected_Item_Code']

            # Get corrected item details from master
            master_match = master_df[master_df['Item Code'] == corrected_code]
            if master_match.empty:
                print(f"Warning: Corrected code {corrected_code} not found in master list")
                continue

            corrected_name = master_match.iloc[0]['Item Name']

            # Clean patterns
            invoice_clean = clean_func(invoice_name)
            supplier_clean = clean_func(supplier_name) if supplier_name else None

            # Record correction
            self.record_correction(
                invoice_no=row.get('Invoice_No', ''),
                line_no=row.get('Line_No', ''),
                invoice_item_name=invoice_name,
                supplier_name=supplier_name,
                suggested_item_code=row.get('Suggested_Item_Code', ''),
                suggested_item_name=row.get('Suggested_Item_Name', ''),
                suggested_score=row.get('Final_Score', 0.0),
                corrected_item_code=corrected_code,
                corrected_item_name=corrected_name,
                correction_reason=row.get('Notes', '')
            )

            # Learn mapping with high confidence
            self.add_learned_mapping(
                invoice_pattern=invoice_name,
                invoice_pattern_clean=invoice_clean,
                master_item_code=corrected_code,
                master_item_name=corrected_name,
                supplier_pattern=supplier_clean,
                confidence=0.90  # High confidence from human correction
            )

            count += 1

        print(f"Processed {count} corrections and learned new mappings.")
        return count

    def get_learning_stats(self) -> Dict:
        """Get statistics about learned mappings."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Count total mappings
        cursor.execute("SELECT COUNT(*) FROM learned_mappings")
        total_mappings = cursor.fetchone()[0]

        # Count high-confidence mappings
        cursor.execute("SELECT COUNT(*) FROM learned_mappings WHERE confidence >= 0.85")
        high_confidence = cursor.fetchone()[0]

        # Count total corrections
        cursor.execute("SELECT COUNT(*) FROM correction_history")
        total_corrections = cursor.fetchone()[0]

        # Get most recent corrections
        cursor.execute("""
            SELECT correction_date FROM correction_history
            ORDER BY correction_date DESC LIMIT 1
        """)
        last_correction = cursor.fetchone()

        conn.close()

        return {
            'total_mappings': total_mappings,
            'high_confidence_mappings': high_confidence,
            'total_corrections': total_corrections,
            'last_correction_date': last_correction[0] if last_correction else None
        }

    def export_learned_mappings(self, output_file: str):
        """Export learned mappings to Excel for review."""
        conn = sqlite3.connect(self.db_path)

        mappings = pd.read_sql_query("""
            SELECT invoice_pattern, supplier_pattern,
                   master_item_code, master_item_name,
                   confidence, times_seen, times_confirmed,
                   learned_date, last_confirmed
            FROM learned_mappings
            ORDER BY confidence DESC, times_confirmed DESC
        """, conn)

        conn.close()

        mappings.to_excel(output_file, index=False)
        print(f"Exported {len(mappings)} learned mappings to {output_file}")

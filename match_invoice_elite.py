"""
Elite Pharmaceutical Invoice Matching System
Version 2.0 - Multi-Algorithm Ensemble with Learning Engine

Features:
- 5 advanced matching algorithms (TF-IDF, Levenshtein, Jaccard, Phonetic, Component)
- Pharmaceutical-specific tokenization and abbreviation expansion
- Learning engine that improves from corrections
- Dynamic weight redistribution when MRP is missing
- Explainable AI - shows why items matched
"""

import pandas as pd
import sys
from datetime import datetime

# Import elite modules
from modules.pharmaceutical_utils import PharmaceuticalNameParser
from modules.advanced_matcher import AdvancedPharmaceuticalMatcher
from modules.learning_engine import LearningEngine

# ---------- CONFIG ----------
MASTER_FILE = "MasterListNew.xlsx"
PURCHASE_HISTORY_FILE = "PurchaseReport.xlsx"
INVOICE_FILE = "InvoiceMatchingTemplate.xlsx"
OUTPUT_FILE = "InvoiceMatchingTemplate_out.xlsx"
CORRECTIONS_FILE = "data/match_corrections.xlsx"  # For learning
LEARNED_MAPPINGS_DB = "data/learned_mappings.db"

TOP_K_CANDIDATES = 10  # Increased for better coverage
LEARNING_ENABLED = True
LEARNING_CONFIDENCE_THRESHOLD = 0.85  # Use learned mappings with 85%+ confidence
# ----------------------------


def clean(text):
    """Basic cleaner: uppercase, remove punctuation-like chars, collapse spaces."""
    if pd.isna(text):
        return ""
    s = str(text).upper()
    for ch in ["*", ",", ".", "-", "/", "(", ")", "%", "'", '"']:
        s = s.replace(ch, " ")
    s = " ".join(s.split())
    return s


def simplify_supplier(text):
    """Normalize supplier name - keep first two words."""
    s = clean(text)
    if not s:
        return ""
    parts = s.split()
    return " ".join(parts[:2])


def normalize_vat_rate(vat_raw):
    """Convert VAT to rate (0.05 = 5%)."""
    if pd.isna(vat_raw):
        return 0.0
    try:
        val = float(vat_raw)
    except (TypeError, ValueError):
        return 0.0

    if val < 0:
        return 0.0
    if val <= 1.0:
        return val
    return val / 100.0


def adjust_mrp_for_vat(mrp_invoice, vat_raw):
    """Convert invoice MRP (with VAT) to net MRP (without VAT)."""
    try:
        mrp = float(mrp_invoice)
        if mrp <= 0:
            return None
    except (TypeError, ValueError):
        return None

    vat_rate = normalize_vat_rate(vat_raw)
    if vat_rate <= 0:
        return mrp
    return mrp / (1.0 + vat_rate)


print("=" * 80)
print("ELITE PHARMACEUTICAL INVOICE MATCHING SYSTEM v2.0")
print("=" * 80)
print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

# ---- LOAD MASTER ----
print("Loading master product list...")
master = pd.read_excel(MASTER_FILE)

if "Item Name" not in master.columns or "Item Code" not in master.columns:
    raise ValueError(f"'Item Name'/'Item Code' not found in master columns: {list(master.columns)}")

master["CleanName"] = master["Item Name"].apply(clean)

# S.Rate = MRP without VAT
if "S.Rate" in master.columns:
    master["MRP_Master"] = pd.to_numeric(master["S.Rate"], errors="coerce")
else:
    master["MRP_Master"] = None

# B.Rate = actual net cost
if "B.Rate" in master.columns:
    master["B.Rate"] = pd.to_numeric(master["B.Rate"], errors="coerce")
else:
    master["B.Rate"] = None

print(f"Loaded {len(master):,} products from master list.")

# ---- LOAD PURCHASE HISTORY ----
print("Loading purchase history...")
purch_raw = pd.read_excel(PURCHASE_HISTORY_FILE)

if "Particulars" not in purch_raw.columns:
    raise ValueError(f"'Particulars' not found in purchase history columns: {list(purch_raw.columns)}")

purch = purch_raw.copy()

# Infer supplier from header rows
purch["Supplier"] = None
current_supplier = None
for idx, row in purch.iterrows():
    date_val = row.get("Date.")
    particulars = row.get("Particulars")
    bill_no = row.get("Bill No.")
    if pd.isna(particulars) and isinstance(date_val, str) and pd.isna(bill_no):
        current_supplier = date_val.strip()
    purch.at[idx, "Supplier"] = current_supplier

# Drop header rows
purch = purch.dropna(subset=["Particulars"]).copy()

# Clean fields
purch["CleanPart"] = purch["Particulars"].apply(clean)
purch["SupplierClean"] = purch["Supplier"].apply(simplify_supplier)

# Ensure P.Rate is numeric
if "P.Rate" not in purch.columns:
    raise ValueError(f"'P.Rate' not found in purchase history columns: {list(purch.columns)}")
purch["P.Rate"] = pd.to_numeric(purch["P.Rate"], errors="coerce")

# Ensure Date. is datetime
if "Date." in purch.columns:
    purch["Date."] = pd.to_datetime(purch["Date."], errors="coerce")
else:
    raise ValueError(f"'Date.' not found in purchase history columns: {list(purch.columns)}")

# Sort by date
purch_sorted = purch.sort_values("Date.")

# Last purchase indices
last_purchase_global = purch_sorted.dropna(subset=["CleanPart"]).groupby("CleanPart").tail(1)
last_purchase_global_idx = last_purchase_global.set_index("CleanPart")

last_purchase_by_supplier = (
    purch_sorted.dropna(subset=["CleanPart", "SupplierClean"])
    .groupby(["CleanPart", "SupplierClean"])
    .tail(1)
)
last_purchase_by_supplier_idx = last_purchase_by_supplier.set_index(["CleanPart", "SupplierClean"])

print(f"Loaded {len(purch):,} purchase history records.")

# ---- INITIALIZE LEARNING ENGINE ----
learning_engine = None
if LEARNING_ENABLED:
    print("\nInitializing learning engine...")
    learning_engine = LearningEngine(db_path=LEARNED_MAPPINGS_DB)

    # Process any existing corrections
    learning_engine.process_corrections_file(
        CORRECTIONS_FILE,
        master,
        clean
    )

    # Show learning stats
    stats = learning_engine.get_learning_stats()
    print(f"Learning stats:")
    print(f"  - Total learned mappings: {stats['total_mappings']}")
    print(f"  - High confidence (>=85%): {stats['high_confidence_mappings']}")
    print(f"  - Total corrections processed: {stats['total_corrections']}")
    if stats['last_correction_date']:
        print(f"  - Last correction: {stats['last_correction_date']}")

# ---- INITIALIZE ADVANCED MATCHER ----
print("\nInitializing advanced matcher...")
matcher = AdvancedPharmaceuticalMatcher(master)

# ---- LOAD INVOICE INPUT ----
print(f"\nLoading invoice from: {INVOICE_FILE}")
invoice_input = pd.read_excel(INVOICE_FILE, sheet_name="Invoice_Input")
print(f"Found {len(invoice_input)} invoice lines to process.\n")

# ---- PROCESS EACH INVOICE LINE ----
print("Processing invoice lines...")
print("-" * 80)

rows = []
stats_counters = {
    'total': 0,
    'learned': 0,
    'auto_ok': 0,
    'check': 0,
    'no_match': 0
}

for idx, inv_row in invoice_input.iterrows():
    stats_counters['total'] += 1

    inv_name = inv_row.get("Invoice_Item_Name", "")
    inv_name_clean = clean(inv_name)
    supplier = inv_row.get("Supplier_Name", "")
    supplier_clean = simplify_supplier(supplier)

    qty_raw = inv_row.get("Qty", 0)
    bonus_raw = inv_row.get("Bonus", 0)
    unit_price_raw = inv_row.get("Unit_Price", inv_row.get("Unit_Price_Invoice", ""))

    mrp_invoice_raw = inv_row.get("MRP_Invoice", None)
    vat_raw = inv_row.get("VAT_Amount_or_%", None)
    mrp_invoice_adj = adjust_mrp_for_vat(mrp_invoice_raw, vat_raw)

    # Compute effective unit price
    effective_unit_price = None
    try:
        qty_val = float(qty_raw) if not pd.isna(qty_raw) else 0.0
        bonus_val = float(bonus_raw) if not pd.isna(bonus_raw) else 0.0
        up = float(unit_price_raw)
        total_units = qty_val + bonus_val
        if qty_val > 0 and total_units > 0:
            effective_unit_price = up * qty_val / total_units
    except (TypeError, ValueError):
        effective_unit_price = None

    if not inv_name_clean:
        continue

    # ---- TRY LEARNED MAPPING FIRST ----
    best = None
    learned_match = False

    if learning_engine:
        learned = learning_engine.lookup_learned_mapping(
            inv_name_clean,
            supplier_clean,
            min_confidence=LEARNING_CONFIDENCE_THRESHOLD
        )

        if learned:
            # Use learned mapping - build result
            learned_match = True
            stats_counters['learned'] += 1

            # Get master row for learned item
            master_row = master[master['Item Code'] == learned['item_code']]
            if not master_row.empty:
                master_row = master_row.iloc[0]

                # Still compute scores for reporting
                supplier_score = 1.0 if supplier_clean else 0.5
                cost_score = 0.0
                mrp_score = 0.0

                if effective_unit_price and master_row.get('B.Rate'):
                    try:
                        inv = float(effective_unit_price)
                        last = float(master_row['B.Rate'])
                        ratio = inv / last
                        delta = abs(ratio - 1.0)
                        if delta <= 0.10:
                            cost_score = 1.0
                        elif delta <= 0.40:
                            cost_score = 0.5
                    except:
                        pass

                has_mrp = (
                    mrp_invoice_adj is not None
                    and master_row.get('MRP_Master') is not None
                    and not pd.isna(master_row.get('MRP_Master'))
                )

                if has_mrp:
                    try:
                        mi = float(mrp_invoice_adj)
                        mm = float(master_row['MRP_Master'])
                        rel_diff = abs(mi - mm) / max(mi, mm)
                        mrp_score = max(0.0, 1.0 - rel_diff * 3)
                    except:
                        pass

                best = {
                    'item_code': learned['item_code'],
                    'item_name': learned['item_name'],
                    'mrp_master': master_row.get('MRP_Master'),
                    'name_scores': {},
                    'supplier_score': supplier_score,
                    'mrp_score': mrp_score,
                    'cost_score': cost_score,
                    'final_score': learned['confidence'],
                    'last_sup': '',
                    'last_date': '',
                    'last_rate': '',
                    'has_mrp': has_mrp,
                    'match_details': f"LEARNED (seen {learned['times_seen']}x, confirmed {learned['times_confirmed']}x)"
                }

    # ---- USE ADVANCED MATCHER IF NOT LEARNED ----
    if best is None:
        best = matcher.match_item(
            inv_name,
            supplier_clean,
            effective_unit_price,
            mrp_invoice_adj,
            last_purchase_global_idx,
            last_purchase_by_supplier_idx,
            top_k=TOP_K_CANDIDATES
        )

    # ---- DETERMINE FLAG ----
    fs = best['final_score']
    if fs >= 0.80:
        flag = "AUTO_OK"
        stats_counters['auto_ok'] += 1
    elif fs >= 0.60:
        flag = "CHECK"
        stats_counters['check'] += 1
    else:
        flag = "NO_MATCH"
        stats_counters['no_match'] += 1

    # ---- MRP COMPARISON ----
    mrp_master = best.get('mrp_master', None)
    mrp_diff = None
    mrp_status = ""

    if (
        mrp_invoice_adj is not None
        and mrp_master is not None
        and not pd.isna(mrp_master)
    ):
        try:
            master_val = float(mrp_master)
            if master_val > 0:
                mrp_diff = mrp_invoice_adj - master_val
                delta_pct = abs(mrp_diff) / master_val

                if delta_pct <= 0.05:
                    mrp_status = "OK"
                elif delta_pct <= 0.10:
                    mrp_status = "CHECK"
                else:
                    mrp_status = "OVERCHARGED"
        except (TypeError, ValueError):
            mrp_status = ""

    # ---- BUILD OUTPUT ROW ----
    rows.append({
        "Invoice_No": inv_row.get("Invoice_No", ""),
        "Line_No": inv_row.get("Line_No", ""),
        "Invoice_Item_Name": inv_name,
        "Supplier_Name": supplier,
        "Qty": qty_raw,
        "Bonus": bonus_raw,
        "Unit_Price_Invoice": unit_price_raw,
        "Effective_Unit_Price": effective_unit_price,

        "MRP_Invoice": mrp_invoice_raw,
        "VAT_Amount_or_%": vat_raw,
        "MRP_Invoice_Adjusted": mrp_invoice_adj,
        "MRP_Master": mrp_master,
        "MRP_Difference": mrp_diff,
        "MRP_Status": mrp_status,

        "Suggested_Item_Code": best['item_code'],
        "Suggested_Item_Name": best['item_name'],
        "Last_Purchase_Supplier": best['last_sup'],
        "Last_Purchase_Date": best['last_date'],
        "Last_Purchase_Rate": best['last_rate'],

        "Supplier_Score": round(best['supplier_score'], 3),
        "MRP_Score": round(best['mrp_score'], 3),
        "Cost_Score": round(best['cost_score'], 3),
        "Final_Score": round(fs, 3),
        "Flag_AUTO_OK_or_CHECK": flag,
        "Match_Details": best.get('match_details', ''),
        "Learned_Match": "YES" if learned_match else "NO",
        "Comment": "",
    })

    # Progress indicator
    if (idx + 1) % 10 == 0 or (idx + 1) == len(invoice_input):
        print(f"Processed {idx + 1}/{len(invoice_input)} lines...", end='\r')

print("\n" + "-" * 80)

# ---- CREATE OUTPUT ----
match_df = pd.DataFrame(rows)

print(f"\nWriting output to: {OUTPUT_FILE}")
with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as writer:
    invoice_input.to_excel(writer, sheet_name="Invoice_Input", index=False)
    match_df.to_excel(writer, sheet_name="Match_Output", index=False)

# ---- PRINT STATISTICS ----
print("\n" + "=" * 80)
print("MATCHING STATISTICS")
print("=" * 80)
print(f"Total invoice lines:      {stats_counters['total']}")
print(f"Learned matches:          {stats_counters['learned']} ({stats_counters['learned']/stats_counters['total']*100:.1f}%)")
print(f"\nConfidence distribution:")
print(f"  AUTO_OK (>=80%):        {stats_counters['auto_ok']} ({stats_counters['auto_ok']/stats_counters['total']*100:.1f}%)")
print(f"  CHECK (60-79%):         {stats_counters['check']} ({stats_counters['check']/stats_counters['total']*100:.1f}%)")
print(f"  NO_MATCH (<60%):        {stats_counters['no_match']} ({stats_counters['no_match']/stats_counters['total']*100:.1f}%)")

automation_rate = (stats_counters['auto_ok'] / stats_counters['total'] * 100) if stats_counters['total'] > 0 else 0
print(f"\nAUTOMATION RATE: {automation_rate:.1f}%")

# MRP warnings
mrp_issues = match_df[match_df['MRP_Status'].isin(['CHECK', 'OVERCHARGED'])]
if not mrp_issues.empty:
    print(f"\nWARNING: {len(mrp_issues)} items need MRP review")

print("=" * 80)
print(f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"\nDone! Check: {OUTPUT_FILE}")
print("\nTo improve accuracy:")
print("1. Review Match_Output sheet")
print("2. Correct any wrong matches in 'Corrected_Item_Code' column")
print("3. Save to: data/match_corrections.xlsx")
print("4. Re-run this script - it will learn from your corrections!")
print("=" * 80)

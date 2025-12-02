import pandas as pd
from difflib import SequenceMatcher

# ---------- CONFIG ----------
MASTER_FILE = "MasterListNew.xlsx"          # POS master list (with B.Rate, S.Rate)
PURCHASE_HISTORY_FILE = "PurchaseReport.xlsx"  # item-level purchase report
INVOICE_FILE = "InvoiceMatchingTemplate.xlsx"
OUTPUT_FILE = "InvoiceMatchingTemplate_out.xlsx"

TOP_K_CANDIDATES = 5            # how many name matches to consider
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
    """
    Normalize supplier name for matching.
    Keep only first two words to avoid LLC / TR / CO noise.
    """
    s = clean(text)
    if not s:
        return ""
    parts = s.split()
    return " ".join(parts[:2])  # e.g. "AL MAQAM MEDICAL LLC" -> "AL MAQAM"


def normalize_vat_rate(vat_raw):
    """
    Treat VAT_Amount_or_% strictly as a percentage:
    - If NaN -> 0
    - If 0 <= x <= 1  -> treat as rate (0.05 = 5%)
    - If x > 1       -> treat as percent (5 = 5%) -> x / 100
    """
    if pd.isna(vat_raw):
        return 0.0
    try:
        val = float(vat_raw)
    except (TypeError, ValueError):
        return 0.0

    if val < 0:
        return 0.0
    if val <= 1.0:
        return val        # already a rate
    return val / 100.0    # 5 -> 0.05


def adjust_mrp_for_vat(mrp_invoice, vat_raw):
    """
    Convert invoice MRP (with VAT) to net MRP (without VAT),
    using VAT_Amount_or_% column as percentage.
    Return None if MRP is missing / invalid.
    """
    try:
        mrp = float(mrp_invoice)
        if mrp <= 0:
            return None
    except (TypeError, ValueError):
        return None

    vat_rate = normalize_vat_rate(vat_raw)
    if vat_rate <= 0:
        return mrp        # 0% VAT
    return mrp / (1.0 + vat_rate)


def cost_score(unit_price_effective, pos_brate):
    """Score [0,1] based on closeness of effective invoice cost to POS B.Rate."""
    try:
        inv = float(unit_price_effective)
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
    # beyond that -> 0
    return 0.0


def mrp_score(mrp_invoice_adj, mrp_master):
    """
    Score [0,1] based on closeness of invoice MRP (after removing VAT)
    vs master MRP (S.Rate, without VAT).

    This should ONLY be called if we actually have an invoice MRP.
    """
    try:
        mi = float(mrp_invoice_adj)
        mm = float(mrp_master)
        if mi <= 0 or mm <= 0:
            return 0.0
    except (TypeError, ValueError):
        return 0.0

    rel_diff = abs(mi - mm) / max(mi, mm)
    score = max(0.0, 1.0 - rel_diff * 3)  # linear drop
    return score


print("Loading data...")

# ---- LOAD MASTER ----
master = pd.read_excel(MASTER_FILE)

if "Item Name" not in master.columns or "Item Code" not in master.columns:
    raise ValueError(f"'Item Name'/'Item Code' not found in masterlist columns: {list(master.columns)}")

master["CleanName"] = master["Item Name"].apply(clean)

# POS: S.Rate = MRP without VAT -> use as master MRP
if "S.Rate" in master.columns:
    master["MRP_Master"] = pd.to_numeric(master["S.Rate"], errors="coerce")
else:
    master["MRP_Master"] = None

# B.Rate = actual net cost after bonuses etc
if "B.Rate" in master.columns:
    master["B.Rate"] = pd.to_numeric(master["B.Rate"], errors="coerce")
else:
    master["B.Rate"] = None

# ---- LOAD PURCHASE HISTORY ----
purch_raw = pd.read_excel(PURCHASE_HISTORY_FILE)

if "Particulars" not in purch_raw.columns:
    raise ValueError(f"'Particulars' column not found in PurchaseReport columns: {list(purch_raw.columns)}")

purch = purch_raw.copy()

# Infer supplier per row from header rows (where Date. is string, Particulars is NaN, Bill No. NaN)
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

# Ensure P.Rate exists and numeric (for last-purchase reporting)
if "P.Rate" not in purch.columns:
    raise ValueError(f"'P.Rate' column not found in PurchaseReport columns: {list(purch.columns)}")
purch["P.Rate"] = pd.to_numeric(purch["P.Rate"], errors="coerce")

# Ensure Date. is datetime
if "Date." in purch.columns:
    purch["Date."] = pd.to_datetime(purch["Date."], errors="coerce")
else:
    raise ValueError(f"'Date.' column not found in PurchaseReport columns: {list(purch.columns)}")

# Sort by date so tail(1) = latest purchase
purch_sorted = purch.sort_values("Date.")

# Last purchase per item (global)
last_purchase_global = purch_sorted.dropna(subset=["CleanPart"]).groupby("CleanPart").tail(1)
last_purchase_global_idx = last_purchase_global.set_index("CleanPart")

# Last purchase per (item, supplier)
last_purchase_by_supplier = (
    purch_sorted.dropna(subset=["CleanPart", "SupplierClean"])
    .groupby(["CleanPart", "SupplierClean"])
    .tail(1)
)
last_purchase_by_supplier_idx = last_purchase_by_supplier.set_index(["CleanPart", "SupplierClean"])

# ---- LOAD INVOICE INPUT ----
invoice_input = pd.read_excel(INVOICE_FILE, sheet_name="Invoice_Input")


def compute_scores_for_candidate(
    inv_name_clean,
    supplier_clean,
    effective_unit_price,
    mrp_invoice_adj,
    cand_row
):
    """
    Compute:
      - base name similarity
      - supplier score
      - MRP score (if invoice MRP exists)
      - cost score (using B.Rate from master)
      - final combined score (dynamic: with or without MRP)
    """
    cand_clean_name = cand_row["CleanName"]
    cand_mrp_master = cand_row.get("MRP_Master", None)
    cand_brate = cand_row.get("B.Rate", None)

    # 1) Base name similarity
    base_name_s = SequenceMatcher(None, inv_name_clean, cand_clean_name).ratio()

    # 2) Supplier via purchase history
    supp_s = 0.0

    # supplier-specific history
    last_sup_row = None
    key_sup = (cand_clean_name, supplier_clean)
    if key_sup in last_purchase_by_supplier_idx.index:
        last_sup_row = last_purchase_by_supplier_idx.loc[key_sup]
        supp_s = 1.0

    # global history
    last_global_row = None
    if cand_clean_name in last_purchase_global_idx.index:
        last_global_row = last_purchase_global_idx.loc[cand_clean_name]
        if supp_s == 0.0:
            supp_s = 0.5  # seen globally but not with this supplier

    # 3) Cost score vs POS B.Rate
    cost_s = 0.0
    if cand_brate is not None and not pd.isna(cand_brate) and effective_unit_price is not None:
        cost_s = cost_score(effective_unit_price, cand_brate)

    # 4) MRP score using VAT-adjusted invoice MRP
    has_mrp = (
        mrp_invoice_adj is not None
        and cand_mrp_master is not None
        and not pd.isna(cand_mrp_master)
    )
    if has_mrp:
        mrp_s = mrp_score(mrp_invoice_adj, cand_mrp_master)
    else:
        mrp_s = 0.0  # displayed, but NOT used in Final when no invoice MRP

    # 5) Final score: dynamic based on whether we have invoice MRP
    if has_mrp:
        # Normal: name + supplier + MRP + cost
        final = (
            0.5 * base_name_s +
            0.25 * supp_s +
            0.20 * mrp_s +
            0.05 * cost_s
        )
    else:
        # No invoice MRP: ignore MRP, renormalize other three to 100%
        final = (
            0.625 * base_name_s +   # 0.5 / 0.8
            0.3125 * supp_s +      # 0.25 / 0.8
            0.0625 * cost_s        # 0.05 / 0.8
        )

    return base_name_s, supp_s, mrp_s, cost_s, final, last_sup_row, last_global_row, has_mrp


def find_best_item(inv_name_clean, supplier_clean, effective_unit_price, mrp_invoice_adj):
    """
    From master, take top-K by raw name similarity, then re-score with
    supplier + MRP + cost to pick the final best candidate.
    """
    raw_scores = master["CleanName"].apply(
        lambda nm: SequenceMatcher(None, inv_name_clean, nm).ratio()
    )
    top_idx = raw_scores.nlargest(TOP_K_CANDIDATES).index

    best = {
        "item_code": None,
        "item_name": None,
        "mrp_master": None,
        "base_name_score": 0.0,
        "supp_score": 0.0,
        "mrp_score": 0.0,
        "cost_score": 0.0,
        "final_score": -1.0,
        "last_sup": "",
        "last_date": "",
        "last_rate": "",
        "has_mrp": False,
    }

    for idx in top_idx:
        cand_row = master.loc[idx]

        base_s, supp_s, mrp_s, cost_s, final_s, last_sup_row, last_global_row, has_mrp = compute_scores_for_candidate(
            inv_name_clean,
            supplier_clean,
            effective_unit_price,
            mrp_invoice_adj,
            cand_row
        )

        if final_s > best["final_score"]:
            best["final_score"] = final_s
            best["base_name_score"] = base_s
            best["supp_score"] = supp_s
            best["mrp_score"] = mrp_s
            best["cost_score"] = cost_s
            best["item_code"] = cand_row["Item Code"]
            best["item_name"] = cand_row["Item Name"]
            best["mrp_master"] = cand_row.get("MRP_Master", None)
            best["has_mrp"] = has_mrp

            lp_row = last_sup_row if last_sup_row is not None else last_global_row
            if lp_row is not None:
                best["last_sup"] = lp_row.get("Supplier", "")
                best["last_date"] = lp_row.get("Date.", "")
                best["last_rate"] = lp_row.get("P.Rate", "")
            else:
                best["last_sup"] = ""
                best["last_date"] = ""
                best["last_rate"] = ""

    return best


def alias_override(inv_name_clean, supplier_clean, effective_unit_price, mrp_invoice_adj):
    """
    Hard overrides for special tricky items where fuzzy can pick the wrong product.
    We use invoice text + supplier to force the correct POS item.
    """
    result = None

    def search_by_substrings(substrings):
        """Return first master row whose CleanName contains ALL substrings."""
        mask = pd.Series(True, index=master.index)
        for sub in substrings:
            mask &= master["CleanName"].str.contains(sub, na=False)
        candidates = master[mask]
        if candidates.empty:
            return None
        return candidates.iloc[0]

    def build_result(row):
        base_s, supp_s, mrp_s, cost_s, final_s, last_sup_row, last_global_row, has_mrp = compute_scores_for_candidate(
            inv_name_clean,
            supplier_clean,
            effective_unit_price,
            mrp_invoice_adj,
            row
        )
        final_s = max(final_s, 0.85)  # force high confidence for hard overrides

        lp_row = last_sup_row if last_sup_row is not None else last_global_row

        return {
            "item_code": row["Item Code"],
            "item_name": row["Item Name"],
            "mrp_master": row.get("MRP_Master", None),
            "base_name_score": base_s,
            "supp_score": supp_s,
            "mrp_score": mrp_s,
            "cost_score": cost_s,
            "final_score": final_s,
            "last_sup": lp_row.get("Supplier", "") if lp_row is not None else "",
            "last_date": lp_row.get("Date.", "") if lp_row is not None else "",
            "last_rate": lp_row.get("P.Rate", "") if lp_row is not None else "",
            "has_mrp": has_mrp,
        }

    # Example overrides – you can add more patterns here as needed.
    if ("NASAL" in inv_name_clean and "CANNULA" in inv_name_clean and "ADULT" in inv_name_clean
            and supplier_clean.startswith("AL MAQAM")):
        row = search_by_substrings(["NASAL", "OXYGEN", "CANNULA", "ADULT"])
        if row is not None:
            return build_result(row)

    if "PREGNACARE" in inv_name_clean:
        row = search_by_substrings(["PREGNACARE", "ORIGINAL", "30"])
        if row is not None:
            return build_result(row)

    if "OZANEX" in inv_name_clean:
        row = search_by_substrings(["OZANEX"])
        if row is not None:
            return build_result(row)

    return result


rows = []

for _, inv_row in invoice_input.iterrows():
    inv_name = inv_row.get("Invoice_Item_Name", "")
    inv_name_clean = clean(inv_name)
    supplier = inv_row.get("Supplier_Name", "")
    supplier_clean = simplify_supplier(supplier)
    qty_raw = inv_row.get("Qty", 0)
    bonus_raw = inv_row.get("Bonus", 0)  # NEW COLUMN, treat empty as 0
    unit_price_raw = inv_row.get("Unit_Price", inv_row.get("Unit_Price_Invoice", ""))

    mrp_invoice_raw = inv_row.get("MRP_Invoice", None)
    vat_raw = inv_row.get("VAT_Amount_or_%", None)
    mrp_invoice_adj = adjust_mrp_for_vat(mrp_invoice_raw, vat_raw)

    # compute effective unit price using Qty + Bonus
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

    # 1) Try alias override first
    best = alias_override(inv_name_clean, supplier_clean, effective_unit_price, mrp_invoice_adj)

    # 2) Otherwise use general fuzzy + scoring
    if best is None:
        best = find_best_item(inv_name_clean, supplier_clean, effective_unit_price, mrp_invoice_adj)

    fs = best["final_score"]
    if fs >= 0.8:
        flag = "AUTO_OK"
    elif fs >= 0.6:
        flag = "CHECK"
    else:
        flag = "NO_MATCH"

    # MRP comparison for reporting (ONLY if invoice MRP exists)
    mrp_master = best.get("mrp_master", None)
    mrp_diff = None
    mrp_status = ""
    if (
        mrp_invoice_adj is not None
        and mrp_master is not None
        and mrp_master != ""
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

        "Suggested_Item_Code": best["item_code"],
        "Suggested_Item_Name": best["item_name"],
        "Last_Purchase_Supplier": best["last_sup"],
        "Last_Purchase_Date": best["last_date"],
        "Last_Purchase_Rate": best["last_rate"],
        "Base_Name_Score": round(best["base_name_score"], 3),
        "Supplier_Score": round(best["supp_score"], 3),
        "MRP_Score": round(best["mrp_score"], 3),
        "Cost_Score": round(best["cost_score"], 3),
        "Final_Score": round(fs, 3),
        "Flag_AUTO_OK_or_CHECK": flag,
        "Comment": "",
    })

match_df = pd.DataFrame(rows)

with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as writer:
    invoice_input.to_excel(writer, sheet_name="Invoice_Input", index=False)
    match_df.to_excel(writer, sheet_name="Match_Output", index=False)

print(f"Done. Check: {OUTPUT_FILE}")

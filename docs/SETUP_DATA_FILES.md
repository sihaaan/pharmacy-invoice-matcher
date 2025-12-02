# Setting Up Your Data Files

This system requires 3 Excel files that contain your pharmacy's data. These files are **NOT included in the repository** for privacy/security reasons.

## Required Files

### 1. MasterListNew.xlsx
**Your POS master item list**

Location: `automation/MasterListNew.xlsx`

Required columns:
- `Item Code` - Unique POS item code
- `Item Name` - Item description
- `B.Rate` - Actual net buy rate (after bonuses)
- `S.Rate` - MRP without VAT

Example:
| Item Code | Item Name | B.Rate | S.Rate |
|-----------|-----------|--------|--------|
| 023177000001 | PANADOL TAB 500MG 24S | 12.50 | 15.00 |
| 005313190001 | FASTUM GEL 50GM | 20.89 | 31.00 |

---

### 2. PurchaseReport.xlsx
**Purchase history from your accounting/POS system**

Location: `automation/PurchaseReport.xlsx`

Required columns:
- `Date.` - Purchase date (or supplier name for header rows)
- `Particulars` - Item description
- `P.Rate` - Purchase rate
- `Bill No.` - Bill number

Special format:
- Header rows have supplier name in `Date.` column
- Item rows follow each header

Example:
| Date. | Particulars | P.Rate | Bill No. |
|-------|-------------|--------|----------|
| AL MAQAM MEDICAL | (blank) | (blank) | (blank) |
| 2025-11-01 | PANADOL TAB 500MG | 12.50 | INV001 |
| 2025-11-02 | FASTUM GEL 50GM | 20.00 | INV002 |

---

### 3. InvoiceMatchingTemplate.xlsx
**Invoice input template**

Location: `automation/InvoiceMatchingTemplate.xlsx`

Must have sheet named: `Invoice_Input`

Required columns:
- `Invoice_No` - Invoice number
- `Invoice_Date` - Invoice date
- `Supplier_Name` - Supplier name from invoice
- `Line_No` - Line number (optional)
- `Invoice_Item_Name` - Item name from invoice
- `Qty` - Quantity billed
- `Bonus` - Free/FOC quantity (leave blank if none)
- `Unit_Price` - Price per unit (billed units only)
- `MRP_Invoice` - MRP printed on invoice (with VAT)
- `VAT_Amount_or_%` - VAT percentage (e.g., 5% or 0.05)
- `Expiry_Date` - Expiry date (optional)
- `Notes` - Any notes (optional)

Example:
| Invoice_No | Supplier_Name | Invoice_Item_Name | Qty | Bonus | Unit_Price | MRP_Invoice | VAT_Amount_or_% |
|------------|---------------|-------------------|-----|-------|------------|-------------|-----------------|
| 255481 | SHARJAH DRUG STORE | PANADOL 500MG 24S | 10 | 2 | 12.00 | 15.75 | 5% |

---

## Quick Setup

1. **Export from your POS system**:
   - Master item list → Save as `MasterListNew.xlsx`
   - Purchase report → Save as `PurchaseReport.xlsx`

2. **Create invoice template**:
   - Copy the example structure above
   - Save as `InvoiceMatchingTemplate.xlsx`
   - Make sure sheet is named `Invoice_Input`

3. **Place files** in the `automation` folder:
   ```
   automation/
   ├── MasterListNew.xlsx
   ├── PurchaseReport.xlsx
   └── InvoiceMatchingTemplate.xlsx
   ```

4. **Test**:
   ```bash
   python match_invoice_elite.py
   ```

---

## Column Name Requirements

**IMPORTANT**: Column names must match EXACTLY (case-sensitive, including spaces/dots):

### MasterListNew.xlsx
- ✅ `Item Code`
- ❌ `ItemCode` or `Item_Code`
- ✅ `Item Name`
- ❌ `ItemName`
- ✅ `B.Rate`
- ❌ `BRate` or `B Rate`
- ✅ `S.Rate`
- ❌ `SRate` or `S Rate`

### PurchaseReport.xlsx
- ✅ `Date.` (with dot!)
- ❌ `Date`
- ✅ `Particulars`
- ❌ `Particular`
- ✅ `P.Rate`
- ❌ `PRate`
- ✅ `Bill No.`
- ❌ `Bill Number`

### InvoiceMatchingTemplate.xlsx
- ✅ `Invoice_Item_Name`
- ❌ `Item Name` or `Item_Name`
- ✅ `Supplier_Name`
- ❌ `Supplier`
- ✅ `Unit_Price` or `Unit_Price_Invoice`
- ❌ `Price`

---

## Troubleshooting

### "Column not found" error
Check that your column names match exactly (including dots, underscores, spaces).

### "File not found" error
Make sure files are in the correct location and named exactly as above.

### Empty results
Check that your master list has data and column names are correct.

---

## Sample Data (For Testing)

If you want to test without your real data, create minimal test files:

**MasterListNew.xlsx** (2-3 items)
**PurchaseReport.xlsx** (5-10 purchase records)
**InvoiceMatchingTemplate.xlsx** (2-3 invoice lines)

This will let you verify the system works before loading full data.

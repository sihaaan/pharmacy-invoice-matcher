"""
Helper script to compare old vs elite matcher results
and identify where improvements can be made.
"""

import pandas as pd
import sys

def compare_matchers():
    """Compare old and elite matcher results side by side."""

    print("=" * 80)
    print("INVOICE MATCHER COMPARISON TOOL")
    print("=" * 80)

    # Check if both output files exist
    try:
        # You'll need to run both scripts and rename outputs to compare
        # For now, just show elite results
        elite = pd.read_excel('InvoiceMatchingTemplate_out.xlsx', sheet_name='Match_Output')
    except FileNotFoundError:
        print("\nError: Could not find InvoiceMatchingTemplate_out.xlsx")
        print("Please run the matcher first:")
        print("  python match_invoice_elite.py")
        return

    print(f"\nAnalyzing {len(elite)} invoice lines...\n")

    # Overall stats
    print("=" * 80)
    print("CONFIDENCE DISTRIBUTION")
    print("=" * 80)

    flags = elite['Flag_AUTO_OK_or_CHECK'].value_counts()
    total = len(elite)

    auto_ok = flags.get('AUTO_OK', 0)
    check = flags.get('CHECK', 0)
    no_match = flags.get('NO_MATCH', 0)

    print(f"\nAUTO_OK (>=80%):  {auto_ok:3d} ({auto_ok/total*100:5.1f}%) - Safe to auto-accept")
    print(f"CHECK (60-79%):   {check:3d} ({check/total*100:5.1f}%) - Review recommended")
    print(f"NO_MATCH (<60%):  {no_match:3d} ({no_match/total*100:5.1f}%) - Needs correction")

    print(f"\nAUTOMATION RATE: {auto_ok/total*100:.1f}%")

    # MRP issues
    print("\n" + "=" * 80)
    print("MRP STATUS")
    print("=" * 80)

    mrp_status = elite['MRP_Status'].value_counts()
    ok_count = mrp_status.get('OK', 0)
    check_count = mrp_status.get('CHECK', 0)
    overcharged = mrp_status.get('OVERCHARGED', 0)

    print(f"\nOK:           {ok_count:3d} - MRP matches (within 5%)")
    print(f"CHECK:        {check_count:3d} - MRP differs 5-10%")
    print(f"OVERCHARGED:  {overcharged:3d} - MRP differs >10% [WARNING]")

    if overcharged > 0:
        print("\n[WARNING] Review OVERCHARGED items for potential overpricing!")

    # Items needing attention
    print("\n" + "=" * 80)
    print("ITEMS NEEDING ATTENTION")
    print("=" * 80)

    needs_review = elite[elite['Flag_AUTO_OK_or_CHECK'].isin(['CHECK', 'NO_MATCH'])]

    if needs_review.empty:
        print("\nAll items matched with high confidence!")
    else:
        print(f"\n{len(needs_review)} items need review:\n")

        for idx, row in needs_review.iterrows():
            invoice_name = row['Invoice_Item_Name']
            matched_name = row['Suggested_Item_Name']
            score = row['Final_Score']
            flag = row['Flag_AUTO_OK_or_CHECK']
            match_details = row.get('Match_Details', '')

            print(f"{idx+1}. [{flag}] Score: {score:.3f}")
            print(f"   Invoice: {invoice_name}")
            print(f"   Matched: {matched_name}")
            if match_details:
                print(f"   Details: {match_details}")
            print()

    # Learning opportunities
    print("=" * 80)
    print("LEARNING RECOMMENDATIONS")
    print("=" * 80)

    learned_count = (elite.get('Learned_Match', pd.Series(['NO']*len(elite))) == 'YES').sum()
    print(f"\nCurrently using {learned_count} learned patterns.")

    if learned_count == 0:
        print("\nTIP: After reviewing matches, create corrections file:")
        print("   1. Add 'Corrected_Item_Code' column to Match_Output")
        print("   2. Fill in correct codes for wrong matches")
        print("   3. Save to: data/match_corrections.xlsx")
        print("   4. Re-run: python match_invoice_elite.py")
        print("\n   The system will learn and improve!")
    else:
        print(f"\nSystem has learned {learned_count} patterns!")
        print("   Continue correcting to improve further.")

    # Supplier breakdown
    print("\n" + "=" * 80)
    print("BY SUPPLIER")
    print("=" * 80)

    supplier_stats = elite.groupby('Supplier_Name').agg({
        'Flag_AUTO_OK_or_CHECK': lambda x: (x == 'AUTO_OK').sum(),
        'Invoice_Item_Name': 'count'
    }).rename(columns={
        'Flag_AUTO_OK_or_CHECK': 'AUTO_OK',
        'Invoice_Item_Name': 'Total'
    })

    supplier_stats['Rate'] = (supplier_stats['AUTO_OK'] / supplier_stats['Total'] * 100).round(1)
    supplier_stats = supplier_stats.sort_values('Rate', ascending=False)

    print()
    for supplier, row in supplier_stats.iterrows():
        supplier_short = supplier[:40] if len(supplier) > 40 else supplier
        auto_ok = int(row['AUTO_OK'])
        total = int(row['Total'])
        rate = float(row['Rate'])
        print(f"{supplier_short:40s} | {auto_ok:2d}/{total:2d} ({rate:5.1f}%)")

    print("\n" + "=" * 80)
    print("EXPORT OPTIONS")
    print("=" * 80)
    print("\nTo export for review:")
    print("  1. Open InvoiceMatchingTemplate_out.xlsx")
    print("  2. Review Match_Output sheet")
    print("  3. Focus on CHECK and NO_MATCH items")
    print("\nTo see learned patterns:")
    print("  python -c \"from modules.learning_engine import LearningEngine;")
    print("             engine = LearningEngine();")
    print("             engine.export_learned_mappings('patterns.xlsx')\"")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    try:
        compare_matchers()
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()

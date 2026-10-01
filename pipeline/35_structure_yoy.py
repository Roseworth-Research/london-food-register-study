"""
Step 35 -- balance-sheet structure year by year, 2018-2025.

Same shape metrics as step 34, but per financial year, so the series shows
the crisis arriving on the balance sheets: cash positions through the
support-scheme years (grants and Bounce Back Loans landed as cash), the
long-term-creditor fingerprint (a BBLS is a long-term liability on a company
that previously had none), and the equity erosion after support ended.

Cross-sections, not a panel: the filing population changes composition every
year (entrants join, exits leave), and each table prints its n so nobody
mistakes a composition shift for a balance-sheet movement. Shares and
medians only.

Output: out/structure_yoy.csv + log tables per SIC.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import config
import db
from ch_api import setup_logging

log = setup_logging("35_structure_yoy")

SICS = ("56101", "56102", "56103", "47240")


def main() -> int:
    con = db.connect(read_only=True, wait_seconds=600)
    df = con.execute(
        """
        SELECT a.company_number, a.financial_year, a.equity, a.net_assets,
               a.weak_net_assets, a.creditors_within_one_year,
               a.creditors_after_one_year, a.cash, a.current_assets,
               c.sic_primary, c.format
        FROM accounts a JOIN companies c USING (company_number)
        WHERE c.sic_primary IN ('56101','56102','56103','47240')
          AND a.financial_year BETWEEN 2018 AND 2025
        """
    ).df()
    con.close()

    df["eq_val"] = df.equity.fillna(
        df.net_assets.where(~df.weak_net_assets.fillna(False)))
    df["net_current"] = df.current_assets - df.creditors_within_one_year
    df["cash_share"] = np.where(
        (df.current_assets > 0) & df.cash.notna(),
        df.cash / df.current_assets, np.nan)
    df["has_longterm"] = df.creditors_after_one_year.fillna(0) > 0

    rows = []
    for sic in SICS:
        s_all = df[df.sic_primary == sic]
        log.info("")
        log.info("=== %s ===", sic)
        log.info("  %-5s %7s %11s %11s %10s %12s", "year", "n",
                 "neg equity", "neg wk cap", "cash/CA", "long-term cr")
        for year, s in s_all.groupby("financial_year"):
            eqs = s.eq_val.dropna()
            nc = s.net_current.dropna()
            row = {
                "sic": sic, "financial_year": int(year), "n": len(s),
                "pct_negative_equity": round(100 * (eqs < 0).mean(), 1) if len(eqs) else None,
                "pct_negative_working_capital": round(100 * (nc < 0).mean(), 1) if len(nc) else None,
                "median_cash_share": round(s.cash_share.median(), 3),
                "pct_with_longterm_creditors": round(100 * s.has_longterm.mean(), 1),
            }
            rows.append(row)
            log.info("  %-5d %7s %10.1f%% %10.1f%% %10.2f %11.1f%%",
                     year, f"{len(s):,}", row["pct_negative_equity"] or 0,
                     row["pct_negative_working_capital"] or 0,
                     row["median_cash_share"] or 0,
                     row["pct_with_longterm_creditors"])

    pd.DataFrame(rows).to_csv(config.OUT / "structure_yoy.csv", index=False)
    log.info("")
    log.info("Cross-sections; composition changes yearly; n printed on every "
             "row. Long-term creditors = any creditors_after_one_year > 0 -- "
             "the Bounce Back Loan fingerprint from FY2020 onward.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

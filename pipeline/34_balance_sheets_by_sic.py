"""
Step 34 -- balance-sheet structure by SIC code, and the analysis the review
called the missing confirmatory piece: survival with TIME ZERO AT FIRST
ACCOUNTS.

Everything here is per SIC code first (56101 / 56102 / 56103 / 47240), with
the counter/service binary as the secondary summary -- the review's ordering.
Medians and shares only. No means (small-base distortion), and no growth
figures (H2 covered growth; this is structure).

Three reports:

1. STRUCTURE AT LATEST ACCOUNTS, by SIC. Balance-sheet shape, not size:
   share with negative equity (balance-sheet insolvent), share with negative
   net current assets, median creditors-to-current-assets, median cash share,
   median employees. Equity preferred; weak working-capital tag excluded.

2. TIME ZERO AT FIRST ACCOUNTS. The 25%/13.6% insolvency figures were
   "shares to date" -- this is the survival version done properly: the clock
   starts at each company's FIRST filed accounts date, so every company in
   the frame demonstrably existed and filed. Kaplan-Meier from that date,
   events = register exit, by SIC. This kills the pre-deadline-exit
   composition problem by construction.

3. DOES THE FIRST BALANCE SHEET PREDICT DEATH? First-accounts equity sign
   vs subsequent 3-year register survival, by format. If negative first
   equity predicts exit, the balance sheet carries real signal; if not, the
   register's financials are decoration.

Output: out/balance_sheet_structure.csv, out/first_accounts_survival.csv,
and the log.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import config
import db
import survival
from ch_api import setup_logging

log = setup_logging("34_balance_sheets_by_sic")

SICS = ("56101", "56102", "56103", "47240")


def best_equity(df: pd.DataFrame) -> pd.Series:
    eq = df.equity.copy()
    fallback = df.net_assets.where(~df.weak_net_assets.fillna(False))
    return eq.fillna(fallback)


def structure(con) -> None:
    df = con.execute(
        """
        SELECT a.*, c.sic_primary, c.format
        FROM accounts a JOIN companies c USING (company_number)
        WHERE c.sic_primary IN ('56101','56102','56103','47240')
        QUALIFY row_number() OVER (
            PARTITION BY a.company_number ORDER BY a.made_up_to DESC) = 1
        """
    ).df()
    df["eq_val"] = best_equity(df)
    df["net_current"] = df.current_assets - df.creditors_within_one_year
    df["cred_ratio"] = np.where(
        (df.current_assets > 0) & df.creditors_within_one_year.notna(),
        df.creditors_within_one_year / df.current_assets, np.nan)
    df["cash_share"] = np.where(
        (df.current_assets > 0) & df.cash.notna(),
        df.cash / df.current_assets, np.nan)

    rows = []
    log.info("1. STRUCTURE AT LATEST FILED ACCOUNTS, by SIC")
    log.info("   %-7s %7s %10s %10s %9s %9s %7s", "sic", "n",
             "neg equity", "neg wk cap", "cred/CA", "cash/CA", "med emp")
    for sic in SICS:
        s = df[df.sic_primary == sic]
        eqs = s["eq_val"].dropna()
        nc = s.net_current.dropna()
        row = {
            "sic": sic, "n": len(s),
            "n_equity": len(eqs),
            "pct_negative_equity": round(100 * (eqs < 0).mean(), 1),
            "pct_negative_working_capital": round(100 * (nc < 0).mean(), 1),
            "median_creditors_to_current_assets": round(
                s.cred_ratio.median(), 2),
            "median_cash_share": round(s.cash_share.median(), 2),
            "median_employees": s.employees.median(),
        }
        rows.append(row)
        log.info("   %-7s %7s %9.1f%% %9.1f%% %9.2f %9.2f %7s",
                 sic, f"{len(s):,}", row["pct_negative_equity"],
                 row["pct_negative_working_capital"],
                 row["median_creditors_to_current_assets"],
                 row["median_cash_share"],
                 row["median_employees"])
    pd.DataFrame(rows).to_csv(
        config.OUT / "balance_sheet_structure.csv", index=False)


def first_accounts_survival(con) -> None:
    df = con.execute(
        f"""
        WITH first_acc AS (
            SELECT company_number, min(made_up_to) AS first_made_up
            FROM accounts GROUP BY 1
        )
        SELECT c.sic_primary, c.format, c.died, f.first_made_up,
               CAST(date_diff('day', CAST(f.first_made_up AS DATE),
                    COALESCE(c.died, DATE '{config.OBSERVATION_DATE}')) AS INTEGER)
                   AS days_from_first,
               (c.outcome IN ('dead','failing')) AS event
        FROM companies c JOIN first_acc f USING (company_number)
        WHERE c.sic_primary IN ('56101','56102','56103','47240')
          AND CAST(f.first_made_up AS DATE) >= DATE '2018-01-01'
        """
    ).df()
    df = df[df.days_from_first >= 0]

    log.info("")
    log.info("2. SURVIVAL WITH TIME ZERO AT FIRST ACCOUNTS (the confirmatory frame)")
    log.info("   %-7s %8s %12s %12s", "sic", "n", "3y from acc", "5y from acc")
    rows = []
    kms = {}
    for sic in SICS:
        s = df[df.sic_primary == sic]
        km = survival.kaplan_meier(s.days_from_first.tolist(), s.event.tolist())
        kms[sic] = (s, km)
        rows.append({
            "sic": sic, "n": len(s),
            "surv_3y_from_first_accounts": round(km.survival_at(1095), 4),
            "surv_5y_from_first_accounts": round(km.survival_at(1825), 4),
        })
        log.info("   %-7s %8s %11.1f%% %11.1f%%", sic, f"{len(s):,}",
                 100 * km.survival_at(1095), 100 * km.survival_at(1825))
    a = df[df.format == "counter"]; b = df[df.format == "service"]
    lr = survival.logrank_test(a.days_from_first, a.event,
                               b.days_from_first, b.event)
    km_a = survival.kaplan_meier(a.days_from_first.tolist(), a.event.tolist())
    km_b = survival.kaplan_meier(b.days_from_first.tolist(), b.event.tolist())
    log.info("   counter vs service, 3y from first accounts: %.1f%% vs %.1f%% "
             "(gap %+.1f pp, p=%.2g)",
             100 * km_a.survival_at(1095), 100 * km_b.survival_at(1095),
             100 * (km_a.survival_at(1095) - km_b.survival_at(1095)), lr["p"])
    pd.DataFrame(rows).to_csv(
        config.OUT / "first_accounts_survival.csv", index=False)


def balance_sheet_predicts(con) -> None:
    df = con.execute(
        f"""
        WITH first_acc AS (
            SELECT company_number, min(made_up_to) AS first_made_up
            FROM accounts GROUP BY 1
        ),
        first_row AS (
            SELECT a.company_number, a.equity, a.net_assets, a.weak_net_assets
            FROM accounts a JOIN first_acc f
              ON f.company_number = a.company_number
             AND f.first_made_up = a.made_up_to
        )
        SELECT c.format, c.sic_primary,
               COALESCE(r.equity, CASE WHEN NOT r.weak_net_assets
                                       THEN r.net_assets END) AS eq_val,
               CAST(date_diff('day', CAST(f.first_made_up AS DATE),
                    COALESCE(c.died, DATE '{config.OBSERVATION_DATE}')) AS INTEGER)
                   AS days_from_first,
               (c.outcome IN ('dead','failing')) AS event
        FROM companies c
        JOIN first_acc f USING (company_number)
        JOIN first_row r USING (company_number)
        WHERE c.sic_primary IN ('56101','56102','56103','47240')
          AND CAST(f.first_made_up AS DATE) >= DATE '2018-01-01'
        """
    ).df()
    df = df[(df.days_from_first >= 0) & df.eq_val.notna()]

    log.info("")
    log.info("3. DOES THE FIRST BALANCE SHEET PREDICT REGISTER EXIT?")
    for fmt in ("counter", "service"):
        s = df[df.format == fmt]
        neg = s[s.eq_val < 0]; pos = s[s.eq_val >= 0]
        km_n = survival.kaplan_meier(neg.days_from_first.tolist(), neg.event.tolist())
        km_p = survival.kaplan_meier(pos.days_from_first.tolist(), pos.event.tolist())
        lr = survival.logrank_test(neg.days_from_first, neg.event,
                                   pos.days_from_first, pos.event)
        log.info("   %-8s first equity < 0 (n=%s): 3y %5.1f%%   "
                 ">= 0 (n=%s): 3y %5.1f%%   gap %+5.1f pp  p=%.2g",
                 fmt, f"{len(neg):,}", 100 * km_n.survival_at(1095),
                 f"{len(pos):,}", 100 * km_p.survival_at(1095),
                 100 * (km_n.survival_at(1095) - km_p.survival_at(1095)),
                 lr["p"])


def main() -> int:
    con = db.connect(read_only=True, wait_seconds=600)
    structure(con)
    first_accounts_survival(con)
    balance_sheet_predicts(con)
    con.close()
    log.info("")
    log.info("Notes for print: shares and medians only; equity preferred with "
             "the weak tag excluded; 'survival' is REGISTER survival; the "
             "time-zero-at-first-accounts frame conditions on having filed, "
             "which is its purpose and its selection, both stated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

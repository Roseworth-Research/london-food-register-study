"""
Step 36 -- accounting framework, growth rates and employment, year by year.

Three questions from the author, answered with the guards stated:

A. FRS 105 vs FRS 102. The register does not record the framework directly;
   the snapshot's latest accounts type is the proxy: MICRO ENTITY -> FRS 105;
   TOTAL EXEMPTION FULL / TOTAL EXEMPTION SMALL / UNAUDITED ABRIDGED / SMALL
   -> FRS 102 (Section 1A). Live-register field, latest filing only -- both
   caveats print. Framework tracks company SIZE by definition, so
   differences here describe the micro/small boundary, not causal effects.

B. Year-on-year equity growth among filers: consecutive-year pairs, opening
   base above GBP 1,000, winsorised at the 1st/99th percentiles. Median
   (the house rule) AND the winsorised mean (requested), labelled, with n.

C. Employment among filers, per year and SIC: companies disclosing, total
   employees, mean and median per company. Filers only -- the caption says
   so -- and 'average number of employees during the period' is the
   statutory figure companies themselves disclose.

Output: out/framework_split.csv, out/equity_growth_yoy.csv,
out/employees_yoy.csv
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import config
import db
import survival
from ch_api import setup_logging

log = setup_logging("36_frameworks_growth")

FRS105 = {"MICRO ENTITY"}
FRS102 = {"TOTAL EXEMPTION FULL", "TOTAL EXEMPTION SMALL",
          "UNAUDITED ABRIDGED", "SMALL"}


def framework_split(con) -> None:
    df = con.execute(
        f"""
        WITH first_acc AS (
            SELECT company_number, min(made_up_to) AS first_made_up
            FROM accounts GROUP BY 1
        ),
        latest AS (
            SELECT a.*, row_number() OVER (
                PARTITION BY a.company_number ORDER BY a.made_up_to DESC) rn
            FROM accounts a
        )
        SELECT c.company_number, c.format, c.accounts_category,
               l.equity, l.net_assets, l.weak_net_assets, l.cash,
               l.current_assets, l.employees,
               CAST(date_diff('day', CAST(f.first_made_up AS DATE),
                    COALESCE(c.died, DATE '{config.OBSERVATION_DATE}')) AS INTEGER)
                   AS days_from_first,
               (c.outcome IN ('dead','failing')) AS event
        FROM companies c
        JOIN latest l ON l.company_number = c.company_number AND l.rn = 1
        JOIN first_acc f ON f.company_number = c.company_number
        WHERE c.sic_primary IN ('56101','56102','56103','47240')
          AND c.accounts_category IS NOT NULL
        """
    ).df()
    df["framework"] = np.select(
        [df.accounts_category.isin(FRS105), df.accounts_category.isin(FRS102)],
        ["FRS105_micro", "FRS102_small"], default="other")
    df["eq_val"] = df.equity.fillna(
        df.net_assets.where(~df.weak_net_assets.fillna(False)))
    df["cash_share"] = np.where(
        (df.current_assets > 0) & df.cash.notna(),
        df.cash / df.current_assets, np.nan)

    rows = []
    log.info("A. FRAMEWORK SPLIT (proxy: latest accounts type; live-register field)")
    log.info("   %-14s %-8s %7s %11s %9s %8s %8s %12s",
             "framework", "format", "n", "neg equity", "cash/CA",
             "mean emp", "med emp", "3y from acc")
    for (fw, fmt), s in df.groupby(["framework", "format"]):
        if fw == "other" or fmt not in ("counter", "service") or len(s) < 200:
            continue
        eligible = s[s.days_from_first >= 0]
        km = survival.kaplan_meier(
            eligible.days_from_first.tolist(), eligible.event.tolist())
        row = {
            "framework": fw, "format": fmt, "n": len(s),
            "pct_negative_equity": round(100 * (s.eq_val.dropna() < 0).mean(), 1),
            "median_cash_share": round(s.cash_share.median(), 2),
            "mean_employees": round(s.employees.mean(), 2),
            "median_employees": s.employees.median(),
            "surv_3y_from_first_accounts": round(km.survival_at(1095), 4),
        }
        rows.append(row)
        log.info("   %-14s %-8s %7s %10.1f%% %9.2f %8.2f %8s %11.1f%%",
                 fw, fmt, f"{len(s):,}", row["pct_negative_equity"],
                 row["median_cash_share"], row["mean_employees"],
                 row["median_employees"],
                 100 * row["surv_3y_from_first_accounts"])
    pd.DataFrame(rows).to_csv(config.OUT / "framework_split.csv", index=False)


def growth_yoy(con) -> None:
    df = con.execute(
        """
        SELECT a.company_number, a.financial_year,
               COALESCE(a.equity, CASE WHEN NOT a.weak_net_assets
                                       THEN a.net_assets END) AS eq_val,
               c.format
        FROM accounts a JOIN companies c USING (company_number)
        WHERE c.sic_primary IN ('56101','56102','56103','47240')
          AND a.financial_year BETWEEN 2018 AND 2025
          AND c.format IN ('counter','service')
        """
    ).df().dropna(subset=["eq_val"])
    df = df.sort_values(["company_number", "financial_year"])
    df["prev_year"] = df.groupby("company_number").financial_year.shift()
    df["prev_eq"] = df.groupby("company_number").eq_val.shift()
    pairs = df[(df.financial_year == df.prev_year + 1) & (df.prev_eq > 1000)].copy()
    pairs["growth"] = (pairs.eq_val - pairs.prev_eq) / pairs.prev_eq
    lo, hi = pairs.growth.quantile([0.01, 0.99])
    pairs["growth_w"] = pairs.growth.clip(lo, hi)

    rows = []
    log.info("")
    log.info("B. EQUITY GROWTH YEAR ON YEAR, filers with opening base > GBP 1,000")
    log.info("   %-5s %-8s %7s %10s %14s", "year", "format", "pairs",
             "median", "winsor. mean")
    for (year, fmt), s in pairs.groupby(["financial_year", "format"]):
        row = {
            "financial_year": int(year), "format": fmt, "pairs": len(s),
            "median_growth_pct": round(100 * s.growth.median(), 1),
            "winsorised_mean_growth_pct": round(100 * s.growth_w.mean(), 1),
        }
        rows.append(row)
        log.info("   %-5d %-8s %7s %9.1f%% %13.1f%%",
                 year, fmt, f"{len(s):,}", row["median_growth_pct"],
                 row["winsorised_mean_growth_pct"])
    pd.DataFrame(rows).to_csv(config.OUT / "equity_growth_yoy.csv", index=False)


def employees_yoy(con) -> None:
    df = con.execute(
        """
        SELECT a.financial_year, a.employees, c.sic_primary
        FROM accounts a JOIN companies c USING (company_number)
        WHERE c.sic_primary IN ('56101','56102','56103','47240')
          AND a.financial_year BETWEEN 2018 AND 2025
          AND a.employees IS NOT NULL AND a.employees BETWEEN 0 AND 5000
        """
    ).df()
    rows = []
    log.info("")
    log.info("C. EMPLOYMENT AMONG FILERS (disclosed average staff numbers)")
    log.info("   %-5s %-7s %9s %12s %9s %8s", "year", "sic",
             "disclosing", "total staff", "mean", "median")
    for (year, sic), s in df.groupby(["financial_year", "sic_primary"]):
        rows.append({
            "financial_year": int(year), "sic": sic, "disclosing": len(s),
            "total_employees": int(s.employees.sum()),
            "mean_employees": round(s.employees.mean(), 2),
            "median_employees": s.employees.median(),
        })
        log.info("   %-5d %-7s %9s %12s %9.2f %8s",
                 year, sic, f"{len(s):,}", f"{int(s.employees.sum()):,}",
                 s.employees.mean(), s.employees.median())
    pd.DataFrame(rows).to_csv(config.OUT / "employees_yoy.csv", index=False)


def main() -> int:
    con = db.connect(read_only=True, wait_seconds=600)
    framework_split(con)
    growth_yoy(con)
    employees_yoy(con)
    con.close()
    log.info("")
    log.info("Captions everywhere: filers only; framework is a proxy from the "
             "latest filing type; framework tracks company size by definition.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

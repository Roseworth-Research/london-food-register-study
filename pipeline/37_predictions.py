"""
Step 37 -- what can honestly be PREDICTED from this data?

Two exercises, both labelled projections/models, never forecasts of fact:

1. EXIT PREDICTION FROM PUBLIC FILINGS. Discrete-time logistic model
   predicting register exit within 3 years of a company's FIRST accounts,
   from what the filing shows: equity sign, cash share, working-capital
   sign, disclosed staff, format, era. Train on first-accounts years
   2018-2021, evaluate on 2022 (companies whose 3-year window closed inside
   the observation). Reported as AUC and risk-decile exit rates. If the AUC
   is modest, that IS the finding: public micro-accounts barely predict
   survival, and anyone selling "risk scores" built on them should be read
   accordingly.

2. REGISTER-STOCK PROJECTION 2026-2028. Actuarial projection, assumptions
   printed: entry continues at the 2025 rate (scenario band +/-10%), cohorts
   die along the observed cost-of-living-era survival curve, existing stock
   ages along the same curve. Projects the counter and service stock of the
   register -- companies, not shops -- three years out.

Output: out/exit_prediction.csv, out/stock_projection.csv
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import config
import db
import survival
from ch_api import setup_logging

log = setup_logging("37_predictions")


def fit_logit(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    beta = np.zeros(X.shape[1])
    for _ in range(30):
        mu = 1 / (1 + np.exp(-(X @ beta)))
        W = np.maximum(mu * (1 - mu), 1e-9)
        z = X @ beta + (y - mu) / W
        XtW = X.T * W
        new = np.linalg.solve(XtW @ X + 1e-8 * np.eye(X.shape[1]), XtW @ z)
        if np.max(np.abs(new - beta)) < 1e-10:
            return new
        beta = new
    return beta


def auc(scores: np.ndarray, y: np.ndarray) -> float:
    order = np.argsort(scores)
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(1, len(scores) + 1)
    pos = y == 1
    n1, n0 = pos.sum(), (~pos).sum()
    return (ranks[pos].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)


def exit_prediction(con) -> None:
    df = con.execute(
        f"""
        WITH first_acc AS (
            SELECT company_number, min(made_up_to) AS first_made_up
            FROM accounts GROUP BY 1
        ),
        first_row AS (
            SELECT a.company_number,
                   COALESCE(a.equity, CASE WHEN NOT a.weak_net_assets
                                           THEN a.net_assets END) AS eq_val,
                   a.cash, a.current_assets, a.creditors_within_one_year,
                   a.employees
            FROM accounts a JOIN first_acc f
              ON f.company_number = a.company_number
             AND f.first_made_up = a.made_up_to
        )
        SELECT c.company_number, c.format, c.birth_era,
               year(CAST(f.first_made_up AS DATE)) AS acc_year,
               r.eq_val, r.cash, r.current_assets,
               r.creditors_within_one_year, r.employees,
               CAST(date_diff('day', CAST(f.first_made_up AS DATE),
                    COALESCE(c.died, DATE '{config.OBSERVATION_DATE}')) AS INTEGER)
                   AS days_from_first,
               (c.outcome IN ('dead','failing')) AS event
        FROM companies c
        JOIN first_acc f USING (company_number)
        JOIN first_row r USING (company_number)
        WHERE c.sic_primary IN ('56101','56102','56103','47240')
          AND c.format IN ('counter','service')
        """
    ).df()
    df = df[df.days_from_first >= 0]
    # Outcome: exited within 3 years of first accounts. Companies censored
    # before 3 years without exiting cannot be labelled -- drop, and say so.
    df["exit_3y"] = (df.event & (df.days_from_first <= 1095)).astype(int)
    df = df[(df.exit_3y == 1) | (df.days_from_first > 1095)]

    df["neg_eq"] = (df.eq_val < 0).astype(float).where(df.eq_val.notna())
    df["cash_share"] = np.where(
        (df.current_assets > 0) & df.cash.notna(),
        df.cash / df.current_assets, np.nan)
    df["neg_wc"] = np.where(
        df.current_assets.notna() & df.creditors_within_one_year.notna(),
        (df.current_assets < df.creditors_within_one_year).astype(float), np.nan)
    df["staff"] = df.employees.clip(0, 100)
    model_df = df.dropna(subset=["neg_eq", "cash_share", "neg_wc", "staff"])

    train = model_df[model_df.acc_year.between(2018, 2021)]
    test = model_df[model_df.acc_year == 2022]
    log.info("1. EXIT-WITHIN-3-YEARS-OF-FIRST-ACCOUNTS MODEL")
    log.info("   train n=%s (2018-21 first accounts), test n=%s (2022), "
             "labelled-only frame", f"{len(train):,}", f"{len(test):,}")

    def design(d):
        return np.column_stack([
            d.neg_eq, d.cash_share, d.neg_wc, np.log1p(d.staff),
            (d.format == "counter").astype(float),
            np.ones(len(d)),
        ])

    beta = fit_logit(design(train), train.exit_3y.values.astype(float))
    names = ["neg_equity", "cash_share", "neg_working_capital",
             "log_staff", "counter", "intercept"]
    for n_, b in zip(names, beta):
        log.info("   %-20s %+ .4f  (odds %.3f)", n_, b, np.exp(b))
    scores = 1 / (1 + np.exp(-(design(test) @ beta)))
    a = auc(scores, test.exit_3y.values)
    log.info("   AUC on held-out 2022 first-accounts cohort: %.3f", a)
    test = test.assign(score=scores)
    test["decile"] = pd.qcut(test.score, 10, labels=False, duplicates="drop")
    dec = test.groupby("decile").agg(n=("exit_3y", "size"),
                                     exit_rate=("exit_3y", "mean"))
    log.info("   risk deciles (1=lowest predicted risk): exit rates %s",
             ", ".join(f"{100*r:.0f}%" for r in dec.exit_rate))
    dec.to_csv(config.OUT / "exit_prediction.csv")


def stock_projection(con) -> None:
    log.info("")
    log.info("2. REGISTER-STOCK PROJECTION 2026-2028 (assumptions printed)")
    rows = []
    for fmt in ("counter", "service"):
        alive = con.execute(
            f"""
            SELECT lifespan_days FROM companies
            WHERE format = '{fmt}' AND outcome IN ('alive','closing')
            """
        ).df().lifespan_days.values
        entry_2025 = con.execute(
            f"""
            SELECT count(*) FROM companies
            WHERE format = '{fmt}' AND year(born) = 2025
            """
        ).fetchone()[0]
        cohort = con.execute(
            f"""
            SELECT lifespan_days, (outcome IN ('dead','failing')) AS event
            FROM companies
            WHERE format = '{fmt}' AND birth_era = 'cost_of_living'
              AND lifespan_days >= 0
            """
        ).df()
        km = survival.kaplan_meier(cohort.lifespan_days.tolist(),
                                   cohort.event.tolist())

        def s(d: float) -> float:
            return km.survival_at(min(d, 1825))

        stock_now = len(alive)
        for horizon in (1, 2, 3):
            h = horizon * 365
            aged = sum(s(d + h) / max(s(d), 1e-9) for d in alive)
            new = 0.0
            for j in range(horizon):
                mid = h - j * 365 - 182
                new += entry_2025 * s(mid)
            for scen, mult in (("entry -10%", 0.9), ("entry flat", 1.0),
                               ("entry +10%", 1.1)):
                rows.append({
                    "format": fmt, "year": 2025 + horizon, "scenario": scen,
                    "projected_stock": int(aged + mult * new),
                })
        log.info("   %-8s stock now %s; 2025 entry %s/yr; projections:",
                 fmt, f"{stock_now:,}", f"{entry_2025:,}")
        for r in [x for x in rows if x["format"] == fmt and x["scenario"] == "entry flat"]:
            log.info("     %d: %s (flat-entry scenario)",
                     r["year"], f"{r['projected_stock']:,}")
    pd.DataFrame(rows).to_csv(config.OUT / "stock_projection.csv", index=False)
    log.info("   Assumptions: entry at the 2025 rate (+/-10%% band); mortality "
             "along the observed cost-of-living survival curve, capped at the "
             "5-year point; companies, not shops; a projection, not a forecast.")


def main() -> int:
    con = db.connect(read_only=True, wait_seconds=600)
    exit_prediction(con)
    stock_projection(con)
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

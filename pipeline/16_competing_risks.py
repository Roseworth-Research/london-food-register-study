"""
Step 16 -- reclassify exits correctly, and analyse them as competing risks.

This step exists because external review found two errors in step 7 and step
10, both of which changed published numbers. Both are fixed here, and the
superseded figures are recorded rather than quietly replaced.

**Error 1: the strike-off classifier conflated voluntary and registrar-led exits.**
Companies House uses GAZ1 and GAZ2 for a strike-off the registrar initiates,
and GAZ1(A) and GAZ2(A) for the gazette notices that follow a DS01 application
by the directors themselves. The original rule matched on the prefix "GAZ1",
so "GAZ1(A)" matched it too, and the priority order then let the registrar
label win over the voluntary one. Every director-initiated strike-off with a
gazette notice was therefore mislabelled. Of 5,514 companies sampled from the
cached filing histories, 2,452 carried a DS01 and 4,769 carried an (A)-suffixed
notice -- so the mislabelling was not marginal.

**Error 2: strike-off was treated as censoring in a Kaplan-Meier fit.**
It is not censoring, it is a competing event: a struck-off company cannot go on
to become insolvent. Treating it as censoring inflates estimated insolvency
risk, and because counter formats are struck off far more often than service
formats the bias is not symmetric between the two groups being compared. The
correct estimator is the cumulative incidence function; see survival.py.

**And one more thing the review was right about: equal follow-up.** Companies
incorporated in 2025 have not had three years in which to fail. Any three-year
statistic must be restricted to companies incorporated early enough to have
been observable for three years, and that restriction is applied here
explicitly rather than left implicit in the data.

Nothing here re-fetches anything. Every filing history was cached to disk by
step 7, so reclassification is free and the observation stays frozen.
"""

from __future__ import annotations

import datetime as dt
import json
import sys

import pandas as pd

import config
import db
import survival
from ch_api import setup_logging

log = setup_logging("16_competing_risks")

RAW = config.DATA_RAW / "life_history" / "filing-history"

# The classifier itself lives in exit_rules.py, shared with step 7 so the
# pipeline holds exactly one classification.
#
# History, because both bugs changed published numbers: the first version here
# checked the insolvency indicators before the members'-voluntary test, and
# every MVL filing trips those indicators (the category is "insolvency", LIQ13
# sat in the compulsory set, form 600 in the CVL set). The MVL branch was
# unreachable -- 0 MVLs in 60,265 classified exits, while 134 companies in the
# cached histories had filed a declaration of solvency. All 134 solvent
# wind-ups were counted as failures, 121 of them on the service side of the
# comparison (audit finding B1). The shared module tests the declaration of
# solvency first, which is the statutory distinction.
from exit_rules import classify


def reclassify() -> pd.DataFrame:
    # The cache now holds EVERY cohort company's filing history, living and
    # dead (the live pull completed 18 Aug 2026). Exit classification must
    # only ever see exits: a living company that survived an old insolvency
    # procedure, or once entered strike-off and withdrew, is not an exit and
    # must not enter company_exit_v2, or downstream event definitions would
    # count survivors as deaths.
    con = db.connect(read_only=True, wait_seconds=600)
    exits = {
        r[0]
        for r in con.execute(
            f"""
            SELECT company_number FROM companies
            WHERE (died IS NOT NULL AND died >= DATE '{config.STUDY_START}')
               OR outcome IN ('failing', 'closing')
            """
        ).fetchall()
    }
    con.close()
    log.info("Classifying %s in-scope exits (cache holds all companies)",
             f"{len(exits):,}")

    rows = []
    for group in RAW.iterdir():
        if not group.is_dir():
            continue
        for path in group.glob("*.json"):
            if path.stem not in exits:
                continue
            try:
                filings = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            route, family = classify(filings)
            rows.append((path.stem, route, family, len(filings)))
    frame = pd.DataFrame(rows, columns=["company_number", "exit_route",
                                        "exit_family", "n_filings"])
    log.info("Reclassified %s companies from cached filing histories",
             f"{len(frame):,}")
    return frame


def main() -> int:
    if not RAW.exists():
        log.error("No cached filing histories at %s. Run 07_life_history.py first.", RAW)
        return 1

    frame = reclassify()
    con = db.connect()
    con.execute("DROP TABLE IF EXISTS company_exit_v2")
    con.execute(
        """
        CREATE TABLE company_exit_v2 (
            company_number VARCHAR PRIMARY KEY,
            exit_route     VARCHAR,
            exit_family    VARCHAR,
            n_filings      INTEGER
        )
        """
    )
    con.register("_v2", frame)
    con.execute("INSERT INTO company_exit_v2 SELECT * FROM _v2")
    con.unregister("_v2")

    # Write the corrected route back onto the master table. Step 7 used to do
    # this with its own (withdrawn, GAZ1-prefix) classifier -- audit finding
    # M5: the wrong labels sat on companies.exit_route ready for any export.
    # This is now the only writer of exit_route, so 11_exports and everything
    # else reading the column reproduces the corrected classification.
    con.execute(
        """
        UPDATE companies SET exit_route = (
            SELECT e.exit_route FROM company_exit_v2 e
            WHERE e.company_number = companies.company_number
        )
        """
    )
    log.info("companies.exit_route rewritten from the corrected classification")

    log.info("")
    log.info("--- corrected exit routes, by format ---")
    log.info("  %-9s %-32s %8s", "format", "exit route", "n")
    for fmt, route, n in con.execute(
        """
        SELECT c.format, e.exit_route, count(*) AS n
        FROM companies c JOIN company_exit_v2 e USING (company_number)
        GROUP BY 1,2 ORDER BY 1, 3 DESC
        """
    ).fetchall():
        log.info("  %-9s %-32s %8s", fmt, route, f"{n:,}")

    # ---- competing risks, on an equal-follow-up cohort --------------------
    #
    # Three-year figures require three years of potential observation. Only
    # companies incorporated on or before this date qualify.
    horizon_days = 1095
    cutoff = config.OBSERVATION_DATE - dt.timedelta(days=horizon_days)
    log.info("")
    log.info("Equal follow-up: three-year figures use only companies "
             "incorporated on or before %s", cutoff)

    df = con.execute(
        f"""
        SELECT c.format, c.sic_primary, c.lifespan_days,
               CASE
                   WHEN e.exit_family = 'insolvency' THEN 1
                   WHEN e.exit_family IN ('voluntary_dissolution',
                                          'registrar_dissolution',
                                          'solvent_winding_up') THEN 2
                   WHEN c.outcome = 'failing' THEN 1
                   WHEN c.outcome = 'dead' THEN 2
                   ELSE 0
               END AS cause
        FROM companies c
        LEFT JOIN company_exit_v2 e USING (company_number)
        WHERE c.born >= DATE '{config.STUDY_START}'
          AND c.born <= DATE '{cutoff}'
          AND c.lifespan_days >= 0
        """
    ).fetch_df()
    con.close()

    log.info("Cohort with a full three years of potential observation: %s companies",
             f"{len(df):,}")

    log.info("")
    log.info("=" * 78)
    log.info("CUMULATIVE INCIDENCE AT THREE YEARS  (competing risks, Aalen-Johansen)")
    log.info("=" * 78)
    log.info("  %-9s %7s %14s %16s %12s", "format", "n",
             "insolvency", "dissolution", "still live")

    fits = {}
    for fmt in ("counter", "service"):
        sub = df[df.format == fmt]
        fit = survival.cumulative_incidence(sub.lifespan_days, sub.cause, n_causes=2)
        fits[fmt] = (sub, fit)
        ins = survival.cif_at(fit.get(1, {}), horizon_days)
        dis = survival.cif_at(fit.get(2, {}), horizon_days)
        log.info("  %-9s %7s %13.2f%% %15.1f%% %11.1f%%",
                 fmt, f"{len(sub):,}", 100 * ins, 100 * dis, 100 * (1 - ins - dis))

    c_sub, _ = fits["counter"]
    s_sub, _ = fits["service"]
    test = survival.grays_test_approx(
        c_sub.lifespan_days, c_sub.cause, s_sub.lifespan_days, s_sub.cause,
        cause=1, horizon=horizon_days,
    )
    log.info("")
    log.info("  Difference in three-year insolvency incidence (counter - service): "
             "%+.2f pp, 95%% bootstrap CI [%+.2f, %+.2f]",
             100 * test["difference"], 100 * test["ci_low"], 100 * test["ci_high"])

    log.info("")
    log.info("  By SIC code:")
    log.info("  %-7s %7s %14s %16s", "sic", "n", "insolvency", "dissolution")
    for sic in ("47240", "56102", "56103", "56101"):
        sub = df[df.sic_primary == sic]
        if len(sub) < config.MIN_CELL_SIZE:
            continue
        fit = survival.cumulative_incidence(sub.lifespan_days, sub.cause, n_causes=2)
        log.info("  %-7s %7s %13.2f%% %15.1f%%", sic, f"{len(sub):,}",
                 100 * survival.cif_at(fit.get(1, {}), horizon_days),
                 100 * survival.cif_at(fit.get(2, {}), horizon_days))

    log.info("")
    log.info("SUPERSEDED: the earlier Kaplan-Meier figures treating strike-off as")
    log.info("censoring (counter 98.3%%, service 96.3%% 'insolvency-free survival')")
    log.info("are withdrawn. They overstated insolvency risk, unequally between")
    log.info("the two groups. The cumulative incidence figures above replace them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

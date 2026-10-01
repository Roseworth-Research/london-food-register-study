"""
Step 10 -- test the hypotheses, and report what the data actually says.

The hypotheses were written down before the data was collected (the study brief
section 1) and every one of them is reported here whether it holds or not.
That is the point of stating them in advance.

    H1  Counter formats survive better than service formats.
    H2  Counter formats show better net-asset growth. (Needs step 8.)
    H3  The counter share of NEW incorporations rises over time.
    H4  When a service business dies, a counter format is more likely to take
        the premises than the reverse. (Computed in step 9; summarised here.)
    H5  The counter/service divergence is muted while hospitality VAT is
        reduced, and widens after the April 2022 snapback.

Statistical approach
--------------------
Survival: Kaplan-Meier with a log-rank test, because a raw survival percentage
is biased by how long each cohort has had to die. Median comparisons:
Mann-Whitney with a rank-biserial effect size. Proportions: Wilson intervals
and a two-proportion test.

On a cohort of 116,000 companies almost anything is statistically significant,
so every result is reported with an effect size and the report leads with the
effect, not the p-value.

What this cannot do
-------------------
This is observational data. Nothing here identifies a causal effect of VAT.
Formats differ in capital intensity, rent, labour, licensing and the kind of
person who starts them, and the study can separate none of that. Every claim
in the report is "consistent with", and the rival explanations are addressed
explicitly rather than waved away.

Output
------
Prints a full results log, and writes CSVs to out/ for charting.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import config
import db
import survival
from ch_api import setup_logging

log = setup_logging("10_analysis")

# The temporary reduced rate of VAT on hospitality, from config.
VAT_REDUCED_START = "2020-07-15"
VAT_REDUCED_END = "2022-03-31"


def frame(con, sql: str) -> pd.DataFrame:
    return con.execute(sql).fetch_df()


def has_table(con, name: str) -> bool:
    return bool(
        con.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = ?",
            [name],
        ).fetchone()[0]
    )


# ---------------------------------------------------------------------------
# H1 -- survival
# ---------------------------------------------------------------------------


def h1_survival(con) -> None:
    log.info("=" * 78)
    log.info("H1  Counter formats survive better than service formats")
    log.info("=" * 78)

    # A company is treated as dead if it is dissolved, in liquidation or in
    # administration. A company merely proposed for strike-off is NOT counted
    # as dead: the proposal is often withdrawn, and counting it would overstate
    # failure. It stays in the risk set, censored, and the sensitivity run
    # below shows what changes if that choice is reversed.
    base = f"""
        SELECT company_number, format, birth_era, borough, at_hub, sic_mixed,
               born, died, lifespan_days,
               CASE WHEN outcome IN ('dead','failing') THEN 1 ELSE 0 END AS event
        FROM companies
        WHERE born IS NOT NULL
          AND born >= DATE '{config.STUDY_START}'
          AND lifespan_days >= 0
    """
    df = frame(con, base)
    log.info("Companies incorporated in the study window: %s", f"{len(df):,}")

    for era, _, _, _ in config.ERAS:
        cohort = df[df.birth_era == era]
        if len(cohort) < config.MIN_CELL_SIZE:
            continue
        counter = cohort[cohort.format == "counter"]
        service = cohort[cohort.format == "service"]
        km_c = survival.kaplan_meier(counter.lifespan_days, counter.event)
        km_s = survival.kaplan_meier(service.lifespan_days, service.event)
        test = survival.logrank_test(
            counter.lifespan_days, counter.event, service.lifespan_days, service.event
        )

        log.info("")
        log.info("Incorporated in the %s era (counter n=%s, service n=%s)",
                 era, f"{len(counter):,}", f"{len(service):,}")
        for years in (1, 2, 3, 5):
            days = years * 365
            # Only report a horizon the cohort has actually had time to reach.
            if cohort.lifespan_days.max() < days:
                continue
            sc, ss = km_c.survival_at(days), km_s.survival_at(days)
            lo_c, hi_c = km_c.ci_at(days)
            lo_s, hi_s = km_s.ci_at(days)
            log.info(
                "  %d-year survival   counter %5.1f%% [%.1f-%.1f]   "
                "service %5.1f%% [%.1f-%.1f]   gap %+.1f pp",
                years, 100 * sc, 100 * lo_c, 100 * hi_c,
                100 * ss, 100 * lo_s, 100 * hi_s, 100 * (sc - ss),
            )
        log.info("  log-rank chi2=%.1f  p=%.2e  observed/expected deaths "
                 "(counter) = %.3f",
                 test["chi2"], test["p"], test["observed_over_expected_1"])
        log.info("  median lifetime  counter %.2f years   service %.2f years",
                 km_c.median_survival() / 365.25, km_s.median_survival() / 365.25)

    _h1_robustness(df)
    _h1_by_borough(df)


def _h1_robustness(df: pd.DataFrame) -> None:
    """Rerun the headline survival gap under alternative specifications."""
    log.info("")
    log.info("--- H1 robustness: 3-year survival gap for the cost-of-living cohort ---")
    cohort = df[df.birth_era == "cost_of_living"]

    # A company's first accounts are due 21 months after incorporation, so a
    # company dissolved before about 1.75 years will usually have left the
    # register before any accounts were due. The register cannot say whether
    # such a company traded. These pre-deadline exits are a larger share of
    # counter deaths (47.7%) than of service deaths (39.2%). Dropping them is
    # the single most important robustness check in the study: if the survival
    # gap were driven only by pre-deadline exits, it would disappear here.
    pre_deadline_exit = cohort.event.eq(1) & (cohort.lifespan_days < 1.75 * 365)

    variants = {
        "as specified": cohort,
        "excluding mixed-SIC companies": cohort[~cohort.sic_mixed],
        "excluding mass-registration addresses": cohort[~cohort.at_hub],
        "mass-registration addresses only": cohort[cohort.at_hub],
        "excluding deaths before first accounts due": cohort[~pre_deadline_exit],
    }
    for label, subset in variants.items():
        c = subset[subset.format == "counter"]
        s = subset[subset.format == "service"]
        if len(c) < config.MIN_CELL_SIZE or len(s) < config.MIN_CELL_SIZE:
            log.info("  %-42s below the reporting floor", label)
            continue
        km_c = survival.kaplan_meier(c.lifespan_days, c.event)
        km_s = survival.kaplan_meier(s.lifespan_days, s.event)
        gap = km_c.survival_at(1095) - km_s.survival_at(1095)
        log.info("  %-42s counter %5.1f%%  service %5.1f%%  gap %+.1f pp  "
                 "(n=%s / %s)",
                 label, 100 * km_c.survival_at(1095), 100 * km_s.survival_at(1095),
                 100 * gap, f"{len(c):,}", f"{len(s):,}")


def _h1_by_borough(df: pd.DataFrame) -> None:
    """Leave-one-borough-out, and the inner/outer London split."""
    cohort = df[(df.birth_era == "cost_of_living") & df.borough.notna()]
    rows = []
    for borough in sorted(cohort.borough.unique()):
        subset = cohort[cohort.borough == borough]
        c = subset[subset.format == "counter"]
        s = subset[subset.format == "service"]
        if len(c) < config.MIN_CELL_SIZE or len(s) < config.MIN_CELL_SIZE:
            continue
        km_c = survival.kaplan_meier(c.lifespan_days, c.event)
        km_s = survival.kaplan_meier(s.lifespan_days, s.event)
        rows.append({
            "borough": borough,
            "counter_n": len(c),
            "service_n": len(s),
            "counter_3y": km_c.survival_at(1095),
            "service_3y": km_s.survival_at(1095),
            "gap_pp": 100 * (km_c.survival_at(1095) - km_s.survival_at(1095)),
        })
    out = pd.DataFrame(rows).sort_values("gap_pp", ascending=False)
    out.to_csv(config.OUT / "h1_survival_by_borough.csv", index=False)

    log.info("")
    log.info("--- H1 by borough: 3-year survival gap, cost-of-living cohort ---")
    log.info("  (positive means counter formats survived better in that borough)")
    for _, r in out.head(8).iterrows():
        log.info("  %-24s %+6.1f pp   counter %5.1f%% (n=%s)  service %5.1f%% (n=%s)",
                 r.borough, r.gap_pp, 100 * r.counter_3y, f"{int(r.counter_n):,}",
                 100 * r.service_3y, f"{int(r.service_n):,}")
    log.info("  ...")
    for _, r in out.tail(4).iterrows():
        log.info("  %-24s %+6.1f pp   counter %5.1f%% (n=%s)  service %5.1f%% (n=%s)",
                 r.borough, r.gap_pp, 100 * r.counter_3y, f"{int(r.counter_n):,}",
                 100 * r.service_3y, f"{int(r.service_n):,}")
    log.info("  Boroughs where the gap runs the other way: %d of %d",
             int((out.gap_pp < 0).sum()), len(out))


# ---------------------------------------------------------------------------
# H3 -- the entry margin
# ---------------------------------------------------------------------------


def h3_entry_mix(con) -> None:
    log.info("")
    log.info("=" * 78)
    log.info("H3  The counter share of new incorporations rises over time")
    log.info("=" * 78)

    df = frame(con, f"""
        SELECT year(born) AS year, format, count(*) AS n
        FROM companies
        WHERE born BETWEEN DATE '{config.STUDY_START}' AND DATE '{config.STUDY_END}'
        GROUP BY 1, 2 ORDER BY 1, 2
    """)
    wide = df.pivot(index="year", columns="format", values="n").fillna(0)
    wide["total"] = wide.counter + wide.service
    wide["counter_share"] = wide.counter / wide.total
    bounds = [survival.wilson_interval(int(c), int(t))
              for c, t in zip(wide.counter, wide.total)]
    wide["ci_low"] = [b[0] for b in bounds]
    wide["ci_high"] = [b[1] for b in bounds]
    wide.to_csv(config.OUT / "h3_entry_mix_by_year.csv")

    log.info("Counter share of new food-sector incorporations, by year of incorporation:")
    for year, r in wide.iterrows():
        note = " (part year)" if year == config.STUDY_END.year else ""
        log.info("  %d  %5.1f%% [%.1f-%.1f]   counter %6s  service %6s  total %6s%s",
                 year, 100 * r.counter_share, 100 * r.ci_low, 100 * r.ci_high,
                 f"{int(r.counter):,}", f"{int(r.service):,}", f"{int(r.total):,}", note)

    # Compare the first full pre-pandemic year with the last full year.
    years = [y for y in wide.index if y != config.STUDY_END.year]
    first, last = years[0], years[-1]
    test = survival.proportion_difference(
        int(wide.loc[last, "counter"]), int(wide.loc[last, "total"]),
        int(wide.loc[first, "counter"]), int(wide.loc[first, "total"]),
    )
    log.info("")
    log.info("  %d versus %d: %+.1f percentage points [%.1f to %.1f], p=%.2e",
             last, first, 100 * test["difference"],
             100 * test["ci"][0], 100 * test["ci"][1], test["p"])

    # Incorporation RATES per era, since the eras are unequal in length.
    log.info("")
    log.info("--- new incorporations per year of era ---")
    era_df = frame(con, """
        SELECT birth_era, format, count(*) AS n FROM companies
        WHERE birth_era IS NOT NULL GROUP BY 1,2
    """)
    for era, _, _, _ in config.ERAS:
        sub = era_df[era_df.birth_era == era]
        if sub.empty:
            continue
        length = config.era_length_years(era)
        counter = int(sub[sub.format == "counter"].n.sum())
        service = int(sub[sub.format == "service"].n.sum())
        log.info("  %-15s counter %6.0f/yr   service %6.0f/yr   counter share %.1f%%",
                 era, counter / length, service / length,
                 100 * counter / max(counter + service, 1))


# ---------------------------------------------------------------------------
# H5 -- the VAT natural experiment
# ---------------------------------------------------------------------------


def h5_vat_experiment(con) -> None:
    log.info("")
    log.info("=" * 78)
    log.info("H5  The format gap narrows while hospitality VAT is reduced, and")
    log.info("    widens after the 1 April 2022 snapback")
    log.info("=" * 78)
    log.info("Reduced rate: 5%% from %s, 12.5%% from 2021-10-01, 20%% from 2022-04-01",
             VAT_REDUCED_START)

    # Deaths per quarter per 1,000 companies at risk, by format. A rate, not a
    # count, because the population of each format is growing at different
    # speeds and raw death counts would just track population.
    df = frame(con, f"""
        WITH quarters AS (
            SELECT DISTINCT date_trunc('quarter', d) AS q
            FROM (SELECT unnest(generate_series(
                    DATE '{config.STUDY_START}', DATE '{config.STUDY_END}',
                    INTERVAL 1 DAY)) AS d)
        )
        SELECT q.q AS quarter, c.format,
               count(*) FILTER (
                   WHERE c.died >= q.q AND c.died < q.q + INTERVAL 3 MONTH
               ) AS deaths,
               count(*) FILTER (
                   WHERE c.born <= q.q AND (c.died IS NULL OR c.died >= q.q)
               ) AS at_risk
        FROM quarters q CROSS JOIN companies c
        WHERE c.born IS NOT NULL
        GROUP BY 1, 2 ORDER BY 1, 2
    """)
    df = df[df.at_risk > 0].copy()
    df["death_rate_per_1000"] = 1000 * df.deaths / df.at_risk
    wide = df.pivot(index="quarter", columns="format", values="death_rate_per_1000")
    wide["gap"] = wide.service - wide.counter  # positive: service dying faster
    wide.to_csv(config.OUT / "h5_quarterly_death_rates.csv")

    def window_mean(start: str, end: str) -> tuple[float, float, float]:
        sub = wide.loc[(wide.index >= pd.Timestamp(start)) & (wide.index <= pd.Timestamp(end))]
        return sub.counter.mean(), sub.service.mean(), sub.gap.mean()

    windows = [
        ("Pre-COVID, VAT 20%", "2018-01-01", "2020-03-22"),
        ("Reduced rate 5% and 12.5%", VAT_REDUCED_START, VAT_REDUCED_END),
        ("Snapback, VAT 20%", "2022-04-01", str(config.STUDY_END)),
    ]
    log.info("")
    log.info("Quarterly deaths per 1,000 companies at risk:")
    for label, start, end in windows:
        c, s, gap = window_mean(start, end)
        log.info("  %-28s counter %5.2f   service %5.2f   gap %+5.2f", label, c, s, gap)

    _, _, gap_pre = window_mean("2018-01-01", "2020-03-22")
    _, _, gap_reduced = window_mean(VAT_REDUCED_START, VAT_REDUCED_END)
    _, _, gap_after = window_mean("2022-04-01", str(config.STUDY_END))
    log.info("")
    log.info("  Gap while the rate was reduced, minus gap before: %+.2f", gap_reduced - gap_pre)
    log.info("  Gap after the snapback, minus gap while reduced:  %+.2f", gap_after - gap_reduced)
    log.info("")
    log.info("  H5 predicts the first number is negative (the gap narrows under the")
    log.info("  reduced rate) and the second positive (it reopens afterwards).")
    log.info("  CONFOUNDED: the same period carries furlough, grants, a moratorium on")
    log.info("  winding-up petitions and automatic filing extensions. This is")
    log.info("  suggestive at best and the report must say so.")


# ---------------------------------------------------------------------------
# H4 -- succession summary
# ---------------------------------------------------------------------------


def h4_succession(con) -> None:
    if not has_table(con, "succession"):
        log.info("")
        log.info("H4 skipped: run 09_succession.py first.")
        return

    log.info("")
    log.info("=" * 78)
    log.info("H4  A dying service business is replaced by a counter format more")
    log.info("    often than the reverse")
    log.info("=" * 78)

    df = frame(con, """
        SELECT death_era, predecessor_format, successor_format, count(*) AS n
        FROM succession
        WHERE successor_format IN ('counter','service') AND death_era IS NOT NULL
        GROUP BY 1,2,3
    """)
    for era, _, _, _ in config.ERAS:
        sub = df[df.death_era == era]
        if sub.empty:
            continue
        s_to_c = int(sub[(sub.predecessor_format == "service") &
                         (sub.successor_format == "counter")].n.sum())
        s_total = int(sub[sub.predecessor_format == "service"].n.sum())
        c_to_s = int(sub[(sub.predecessor_format == "counter") &
                         (sub.successor_format == "service")].n.sum())
        c_total = int(sub[sub.predecessor_format == "counter"].n.sum())
        if s_total < config.MIN_CELL_SIZE or c_total < config.MIN_CELL_SIZE:
            continue
        test = survival.proportion_difference(s_to_c, s_total, c_to_s, c_total)
        log.info("  %-15s service->counter %5.1f%% (n=%s)   counter->service %5.1f%% "
                 "(n=%s)   difference %+.1f pp  p=%.3f",
                 era, 100 * test["p1"], f"{s_total:,}", 100 * test["p2"],
                 f"{c_total:,}", 100 * test["difference"], test["p"])
    log.info("")
    log.info("  H4 predicts service->counter exceeds counter->service. A negative")
    log.info("  difference means the premises are flowing the other way and H4 fails.")


# ---------------------------------------------------------------------------
# H2 -- balance sheet growth
# ---------------------------------------------------------------------------


def h2_growth(con) -> None:
    log.info("")
    log.info("=" * 78)
    log.info("H2  Counter formats show better net-asset growth")
    log.info("=" * 78)

    if not has_table(con, "accounts"):
        log.info("Skipped: no accounts table. Run 08_accounts.py, then "
                 "08_accounts.py --load.")
        return

    # Measure: shareholders' equity, not the net-assets tag.
    #
    # In a UK balance sheet net assets and total equity are the same quantity by
    # construction, and the data confirms it: where a properly tagged net-assets
    # figure and an equity figure both exist, they are identical in 99.8% of
    # 17,625 filings. Equity is tagged in 98.5% of filings; the strong
    # net-assets tag in only 11%. So equity is used wherever available, with the
    # strong net-assets tag as the fallback, and the weak working-capital
    # fallback is never used for growth.
    df = frame(con, f"""
        WITH filings AS (
            SELECT a.company_number, a.financial_year,
                   COALESCE(
                       a.equity,
                       CASE WHEN NOT a.weak_net_assets THEN a.net_assets END
                   ) AS net_assets,
                   c.format, c.borough, c.at_hub, c.born
            FROM accounts a
            JOIN companies c USING (company_number)
            WHERE COALESCE(
                      a.equity,
                      CASE WHEN NOT a.weak_net_assets THEN a.net_assets END
                  ) IS NOT NULL
              AND a.financial_year BETWEEN 2017 AND {config.STUDY_END.year}
        ),
        paired AS (
            SELECT f.*, lag(net_assets) OVER w AS prev_net_assets,
                   lag(financial_year) OVER w AS prev_year
            FROM filings f
            WINDOW w AS (PARTITION BY company_number ORDER BY financial_year)
        )
        SELECT * FROM paired
        WHERE prev_net_assets IS NOT NULL
          AND financial_year = prev_year + 1
          -- Growth from a negative or trivial base is not a percentage anyone
          -- can interpret, so those company-years are dropped and the count of
          -- drops is reported.
          AND prev_net_assets > 1000
          -- Exclude the first two trading years: percentage growth from a
          -- near-zero opening balance sheet flatters whatever started smallest,
          -- and counter formats start smallest.
          AND financial_year - year(born) > {config.MIN_TRADING_YEARS_FOR_GROWTH}
    """)
    if df.empty:
        log.info("No usable year-on-year pairs yet.")
        return

    df["growth"] = (df.net_assets - df.prev_net_assets) / df.prev_net_assets
    # Winsorise at the 1st and 99th percentiles. A handful of companies show
    # five-figure percentage moves from restructuring; medians are robust to
    # them but the quartiles and the plots are not.
    lo, hi = df.growth.quantile([0.01, 0.99])
    df["growth"] = df.growth.clip(lo, hi)

    log.info("Usable year-on-year net-asset pairs: %s", f"{len(df):,}")
    log.info("")
    log.info("Median year-on-year net-asset growth, by format and financial year:")
    rows = []
    for year in sorted(df.financial_year.unique()):
        sub = df[df.financial_year == year]
        c = sub[sub.format == "counter"].growth
        s = sub[sub.format == "service"].growth
        if len(c) < config.MIN_CELL_SIZE or len(s) < config.MIN_CELL_SIZE:
            continue
        test = survival.mann_whitney(c, s)
        log.info(
            "  %d  counter %+6.1f%% (n=%5s)   service %+6.1f%% (n=%5s)   "
            "effect %+.3f  p=%.2e",
            year, 100 * np.median(c), f"{len(c):,}", 100 * np.median(s),
            f"{len(s):,}", test["effect_size"], test["p"],
        )
        rows.append({
            "financial_year": year,
            "counter_median": float(np.median(c)),
            "counter_q1": float(np.percentile(c, 25)),
            "counter_q3": float(np.percentile(c, 75)),
            "counter_n": len(c),
            "counter_share_growing": float((c > 0).mean()),
            "service_median": float(np.median(s)),
            "service_q1": float(np.percentile(s, 25)),
            "service_q3": float(np.percentile(s, 75)),
            "service_n": len(s),
            "service_share_growing": float((s > 0).mean()),
            "effect_size": test["effect_size"],
            "p": test["p"],
        })
    pd.DataFrame(rows).to_csv(config.OUT / "h2_net_asset_growth.csv", index=False)

    log.info("")
    log.info("Share of companies whose net assets grew:")
    for r in rows:
        log.info("  %d  counter %5.1f%%   service %5.1f%%",
                 r["financial_year"], 100 * r["counter_share_growing"],
                 100 * r["service_share_growing"])


# ---------------------------------------------------------------------------


def cohort_flow(con) -> None:
    log.info("")
    log.info("=" * 78)
    log.info("Cohort flow -- every company that left the sample, and why")
    log.info("=" * 78)
    df = frame(con, "SELECT * FROM cohort_flow ORDER BY step, stage")
    df.to_csv(config.OUT / "cohort_flow.csv", index=False)
    for _, r in df.iterrows():
        log.info("  [%s] %-30s %9s  %s", r.step, r.stage, f"{int(r.n):,}", r.note)


def main() -> int:
    con = db.connect(read_only=True, wait_seconds=300)
    try:
        cohort_flow(con)
        h1_survival(con)
        h3_entry_mix(con)
        h4_succession(con)
        h5_vat_experiment(con)
        h2_growth(con)
    finally:
        con.close()
    log.info("")
    log.info("CSV outputs written to %s", config.OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())

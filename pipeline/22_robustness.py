"""
Step 22 -- test the study's own stated weaknesses with data rather than words.

Four of the limitations listed in the study's assessment can be evaluated directly from
what we already hold. Doing so is cheap and it converts "we acknowledge this
risk" into "we measured this risk and here is how big it is", which is the
difference between a caveat and a finding.

  1. **The 6.9% of exits we could not classify.** They are large relative to
     the insolvency counts, so in principle they could overturn the insolvency
     comparison. Tested by assigning all of them to insolvency, then all to
     dissolution -- the two worst cases -- and seeing whether the conclusion
     survives both.

  2. **Independence assumed in the bootstrap.** Companies cluster: several at
     one address, one operator running a group. Tested by re-running the
     bootstrap resampling *addresses* rather than companies, which is the
     standard correction and widens the interval honestly.

  3. **Small event counts.** Some published rates rest on very few events.
     Tested by printing the exact numerator and denominator for every rate and
     an exact binomial (Clopper-Pearson) interval, then flagging any cell that
     should be suppressed.

  4. **The FSA snapshot is current, not historical.** A premises that closed
     years ago is invisible, so match rates for older dissolutions should be
     lower. Tested by plotting match rate against year of dissolution: the
     slope is the size of the bias.
"""

from __future__ import annotations

import sys

import numpy as np
from scipy import stats

import config
import db
import survival
from ch_api import setup_logging

log = setup_logging("22_robustness")


def clopper_pearson(k: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    """Exact binomial interval. Correct where the normal approximation is not."""
    if n == 0:
        return (float("nan"), float("nan"))
    lo = 0.0 if k == 0 else stats.beta.ppf(alpha / 2, k, n - k + 1)
    hi = 1.0 if k == n else stats.beta.ppf(1 - alpha / 2, k + 1, n - k)
    return (float(lo), float(hi))


def cluster_bootstrap(df, cause: int = 1, horizon: float = 1095,
                      n_boot: int = 400, seed: int = 7) -> dict:
    """Bootstrap that resamples ADDRESSES, not companies.

    Resampling companies assumes each is an independent observation. They are
    not: one operator can register several, and companies at one address share
    whatever is true of that address. Resampling whole clusters propagates that
    dependence into the interval instead of ignoring it.
    """
    rng = np.random.default_rng(seed)
    groups = {}
    for key, dur, cz in zip(df.cluster, df.lifespan_days, df.cause):
        groups.setdefault(key, []).append((dur, cz))
    keys = list(groups)

    out = []
    for _ in range(n_boot):
        picked = rng.integers(0, len(keys), len(keys))
        dur, cz = [], []
        for i in picked:
            for d, c in groups[keys[i]]:
                dur.append(d); cz.append(c)
        fit = survival.cumulative_incidence(np.array(dur), np.array(cz))
        out.append(survival.cif_at(fit.get(cause, {}), horizon))
    out = np.array(out)
    return {"mean": float(out.mean()),
            "ci_low": float(np.percentile(out, 2.5)),
            "ci_high": float(np.percentile(out, 97.5)),
            "clusters": len(keys)}


def main() -> int:
    con = db.connect(read_only=True, wait_seconds=600)
    horizon = 1095
    cutoff = config.OBSERVATION_DATE - __import__("datetime").timedelta(days=horizon)

    base = con.execute(f"""
        SELECT c.company_number, c.format, c.sic_primary, c.lifespan_days,
               COALESCE(NULLIF(t.best_key,''), 'solo_'||c.company_number) AS cluster,
               CASE
                   WHEN e.exit_family = 'insolvency' THEN 1
                   WHEN e.exit_family IN ('voluntary_dissolution','registrar_dissolution',
                                          'solvent_winding_up') THEN 2
                   WHEN e.exit_family = 'unknown' THEN 9
                   WHEN c.outcome = 'failing' THEN 1
                   WHEN c.outcome = 'dead' THEN 2
                   ELSE 0
               END AS cause
        FROM companies c
        LEFT JOIN company_exit_v2 e USING (company_number)
        LEFT JOIN company_tier t USING (company_number)
        WHERE c.born >= DATE '{config.STUDY_START}' AND c.born <= DATE '{cutoff}'
          AND c.lifespan_days >= 0
    """).fetch_df()

    n_unknown = int((base.cause == 9).sum())
    log.info("Equal-follow-up cohort: %s companies; unclassified exits: %s (%.2f%%)",
             f"{len(base):,}", f"{n_unknown:,}", 100 * n_unknown / len(base))

    # ---- 1. worst-case treatment of unclassified exits --------------------
    log.info("")
    log.info("=" * 82)
    log.info("1. THE UNCLASSIFIED EXITS -- does the conclusion survive both worst cases?")
    log.info("=" * 82)
    scenarios = {
        "unclassified censored (as published)": 0,
        "ALL unclassified = insolvency": 1,
        "ALL unclassified = dissolution": 2,
    }
    for label, assign in scenarios.items():
        df = base.copy()
        df.loc[df.cause == 9, "cause"] = assign
        res = {}
        for fmt in ("counter", "service"):
            sub = df[df.format == fmt]
            fit = survival.cumulative_incidence(sub.lifespan_days, sub.cause)
            res[fmt] = survival.cif_at(fit.get(1, {}), horizon)
        gap = 100 * (res["counter"] - res["service"])
        log.info("  %-38s counter %5.2f%%  service %5.2f%%  gap %+.2f pp",
                 label, 100 * res["counter"], 100 * res["service"], gap)
    log.info("")
    log.info("  The sign of the gap is what matters. If it holds in all three rows,")
    log.info("  the unclassified exits cannot overturn the finding.")

    # ---- 2. clustered bootstrap ------------------------------------------
    log.info("")
    log.info("=" * 82)
    log.info("2. CLUSTERING -- resampling addresses instead of companies")
    log.info("=" * 82)
    clean = base[base.cause != 9]
    for fmt in ("counter", "service"):
        sub = clean[clean.format == fmt]
        naive = survival.cumulative_incidence(sub.lifespan_days, sub.cause)
        point = survival.cif_at(naive.get(1, {}), horizon)
        cb = cluster_bootstrap(sub, n_boot=300)
        log.info("  %-9s point %5.3f%%   clustered 95%% CI [%.3f%%, %.3f%%]   "
                 "(%s companies in %s address clusters)",
                 fmt, 100 * point, 100 * cb["ci_low"], 100 * cb["ci_high"],
                 f"{len(sub):,}", f"{cb['clusters']:,}")
    log.info("")
    log.info("  Compare with the naive interval published earlier: [-0.26, -0.09] pp")
    log.info("  on the difference. If the clustered intervals still separate the two")
    log.info("  formats, dependence between companies does not explain the result.")

    # ---- 3. exact counts and intervals -----------------------------------
    log.info("")
    log.info("=" * 82)
    log.info("3. EVENT COUNTS -- every rate with its numerator and an exact interval")
    log.info("=" * 82)
    log.info("  %-8s %9s %9s %9s   %-22s", "sic", "n", "insolv", "rate", "95% exact CI")
    for sic, n, ins in con.execute("""
        SELECT c.sic_primary, count(*),
               sum(CASE WHEN e.exit_family='insolvency' THEN 1 ELSE 0 END)
        FROM companies c LEFT JOIN company_exit_v2 e USING (company_number)
        WHERE c.born >= DATE '2018-01-01' GROUP BY 1 ORDER BY 1
    """).fetchall():
        lo, hi = clopper_pearson(int(ins), int(n))
        flag = "  <-- below reporting floor" if ins < config.MIN_CELL_SIZE else ""
        log.info("  %-8s %9s %9s %8.2f%%   [%.2f%%, %.2f%%]%s",
                 sic, f"{n:,}", f"{ins:,}", 100 * ins / n, 100 * lo, 100 * hi, flag)

    log.info("")
    log.info("  Conditional on having filed accounts (the figure worth publishing):")
    log.info("  %-8s %9s %9s %9s   %-22s", "sic", "filers", "insolv", "rate", "95% exact CI")
    for sic, n, ins in con.execute("""
        SELECT c.sic_primary, count(*),
               sum(CASE WHEN e.exit_family='insolvency' THEN 1 ELSE 0 END)
        FROM companies c
        JOIN filing_footprint f USING (company_number)
        LEFT JOIN company_exit_v2 e USING (company_number)
        WHERE f.n_accounts > 0 GROUP BY 1 ORDER BY 1
    """).fetchall():
        lo, hi = clopper_pearson(int(ins), int(n))
        log.info("  %-8s %9s %9s %8.2f%%   [%.2f%%, %.2f%%]",
                 sic, f"{n:,}", f"{ins:,}", 100 * ins / n, 100 * lo, 100 * hi)

    # ---- 4. is the FSA snapshot biased against old dissolutions? ----------
    log.info("")
    log.info("=" * 82)
    log.info("4. FSA SNAPSHOT BIAS -- premises match rate by year the company left")
    log.info("=" * 82)
    log.info("  A premises that closed years ago is not in a current FSA snapshot, so")
    log.info("  match rates should fall for older exits. The slope IS the bias.")
    log.info("")
    log.info("  %-8s %9s %11s %9s", "year", "exits", "matched", "rate")
    for yr, n, m in con.execute("""
        SELECT year(c.died) AS y, count(*),
               sum(CASE WHEN t.tier='A_premises_confirmed' THEN 1 ELSE 0 END)
        FROM companies c JOIN company_tier t USING (company_number)
        WHERE c.died IS NOT NULL AND year(c.died) BETWEEN 2018 AND 2025
        GROUP BY 1 ORDER BY 1
    """).fetchall():
        log.info("  %-8s %9s %11s %8.1f%%", yr, f"{n:,}", f"{m:,}", 100 * m / n)

    still_live = con.execute("""
        SELECT count(*), sum(CASE WHEN t.tier='A_premises_confirmed' THEN 1 ELSE 0 END)
        FROM companies c JOIN company_tier t USING (company_number)
        WHERE c.outcome = 'alive'
    """).fetchone()
    log.info("  %-8s %9s %11s %8.1f%%", "live", f"{still_live[0]:,}",
             f"{still_live[1]:,}", 100 * still_live[1] / still_live[0])

    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

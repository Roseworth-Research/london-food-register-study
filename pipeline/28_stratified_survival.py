"""
Step 28 -- does the format survival gap survive stratification?

External review, correctly: "group A outlives group B" carries no weight
until composition is addressed -- formation year, geography and address type
all differ between formats and all plausibly drive survival on their own.

Two checks, both deliberately simple enough to verify by hand:

1. STRATIFIED LOG-RANK. The log-rank observed/expected machinery run
   separately inside each stratum (birth era x address type x inner/outer
   London) and pooled. Within a stratum, every company shares era, address
   type and broad geography, so the comparison is format against format
   among peers. If the pooled statistic survives, the gap is not an artefact
   of any of those compositions.

2. DISCRETE-TIME HAZARD MODEL. Person-period expansion (one row per company
   per year at risk, up to five), logistic regression via plain
   Newton-Raphson on numpy -- no modelling library, nothing hidden. Format
   coefficient adjusted for era, address type and inner/outer, reported as
   an odds ratio with its standard error.

Language rule stands: this measures survival ON THE REGISTER.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import config
import db
from ch_api import setup_logging

log = setup_logging("28_stratified_survival")

INNER_LONDON = {
    "Camden", "City of London", "Greenwich", "Hackney",
    "Hammersmith and Fulham", "Islington", "Kensington and Chelsea",
    "Lambeth", "Lewisham", "Southwark", "Tower Hamlets", "Wandsworth",
    "Westminster", "Haringey", "Newham",
}


def load(con) -> pd.DataFrame:
    df = con.execute(
        f"""
        SELECT format, lifespan_days,
               (outcome IN ('dead','failing')) AS event,
               birth_era, at_hub,
               borough
        FROM companies
        WHERE born >= DATE '{config.STUDY_START}'
          AND birth_era IS NOT NULL AND lifespan_days >= 0
          AND format IN ('counter','service') AND borough IS NOT NULL
        """
    ).df()
    df["zone"] = np.where(df.borough.isin(INNER_LONDON), "inner", "outer")
    return df


def stratified_logrank(df: pd.DataFrame) -> None:
    obs = exp = var = 0.0
    used = skipped = 0
    for (_era, _hub, _zone), sub in df.groupby(["birth_era", "at_hub", "zone"]):
        a = sub[sub.format == "counter"]
        b = sub[sub.format == "service"]
        if len(a) < 25 or len(b) < 25:
            skipped += 1
            continue
        used += 1
        d1, e1 = a.lifespan_days.values.astype(float), a.event.values.astype(int)
        d2, e2 = b.lifespan_days.values.astype(float), b.event.values.astype(int)
        times = np.unique(np.concatenate([d1[e1 == 1], d2[e2 == 1]]))
        for t in times:
            n1 = float(np.sum(d1 >= t)); n2 = float(np.sum(d2 >= t))
            n = n1 + n2
            if n <= 1:
                continue
            o1 = float(np.sum((d1 == t) & (e1 == 1)))
            o = o1 + float(np.sum((d2 == t) & (e2 == 1)))
            if o == 0:
                continue
            obs += o1
            exp += o * n1 / n
            var += o * (n1 / n) * (1 - n1 / n) * ((n - o) / (n - 1))
    chi2 = (obs - exp) ** 2 / var
    # Normal-approximation p for chi2(1): p = erfc(sqrt(chi2/2))
    from math import erfc, sqrt
    p = erfc(sqrt(chi2 / 2))
    log.info("STRATIFIED LOG-RANK  (%d strata used, %d too small)", used, skipped)
    log.info("  observed counter deaths %.0f  expected %.0f  O/E = %.3f",
             obs, exp, obs / exp)
    log.info("  chi2 = %.1f   p = %.3g", chi2, p)


def discrete_time_model(df: pd.DataFrame) -> None:
    # Person-period expansion: year k covers days (k-1)*365 .. k*365.
    frames = []
    for k in range(1, 6):
        at_risk = df[df.lifespan_days >= (k - 1) * 365].copy()
        if at_risk.empty:
            continue
        at_risk["event_k"] = (
            (at_risk.lifespan_days < k * 365) & at_risk.event
        ).astype(int)
        at_risk["year_k"] = k
        frames.append(at_risk)
    pp = pd.concat(frames, ignore_index=True)

    y = pp.event_k.values.astype(float)
    cols = ["counter", "hub", "inner"]
    X = [
        (pp.format == "counter").astype(float).values,
        pp.at_hub.astype(float).values,
        (pp.zone == "inner").astype(float).values,
    ]
    for era in ("covid", "revival", "cost_of_living"):
        cols.append(f"era_{era}")
        X.append((pp.birth_era == era).astype(float).values)
    for k in range(2, 6):
        cols.append(f"year_{k}")
        X.append((pp.year_k == k).astype(float).values)
    cols.append("intercept")
    X.append(np.ones(len(pp)))
    X = np.column_stack(X)

    beta = np.zeros(X.shape[1])
    for _ in range(25):
        eta = X @ beta
        mu = 1 / (1 + np.exp(-eta))
        W = mu * (1 - mu)
        z = eta + (y - mu) / np.maximum(W, 1e-9)
        XtW = X.T * W
        beta_new = np.linalg.solve(XtW @ X, XtW @ z)
        if np.max(np.abs(beta_new - beta)) < 1e-10:
            beta = beta_new
            break
        beta = beta_new
    cov = np.linalg.inv((X.T * (mu * (1 - mu))) @ X)
    se = np.sqrt(np.diag(cov))

    log.info("")
    log.info("DISCRETE-TIME HAZARD MODEL  (%s person-years, %s events)",
             f"{len(pp):,}", f"{int(y.sum()):,}")
    log.info("  %-16s %9s %8s %9s", "term", "coef", "se", "odds")
    for name, b, s in zip(cols, beta, se):
        log.info("  %-16s %9.4f %8.4f %9.3f", name, b, s, np.exp(b))
    b_c = beta[cols.index("counter")]
    s_c = se[cols.index("counter")]
    log.info("")
    log.info("  Counter format, adjusted: odds ratio %.3f  [%.3f, %.3f]",
             np.exp(b_c), np.exp(b_c - 1.96 * s_c), np.exp(b_c + 1.96 * s_c))


def main() -> int:
    con = db.connect(read_only=True, wait_seconds=600)
    df = load(con)
    con.close()
    log.info("Cohort: %s companies (%s counter, %s service)",
             f"{len(df):,}",
             f"{(df.format == 'counter').sum():,}",
             f"{(df.format == 'service').sum():,}")
    stratified_logrank(df)
    discrete_time_model(df)
    log.info("")
    log.info("Reading: if the stratified O/E stays materially above 1 and the "
             "adjusted odds ratio stays materially above 1, the format gap is "
             "not explained by era, address type or inner/outer geography. "
             "Unmeasured composition (capital, founder experience) remains, "
             "and the report says so.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
Step 26 -- the rank-reversal experiment.

The question this answers, decided in the pre-registered decision gate: does the borough
picture CHANGE when the register is read carefully, or was Hackney-vs-Newham
a one-off? Three readings of the same data, per metric:

  A  as registered      every company at its registered address (the naive
                        reading every closure map uses)
  B  single-company     only companies at addresses holding one cohort
                        company -- where a registration plausibly reflects
                        one business at one place
  C  premises-confirmed only companies matched to an FSA food establishment
                        (Tier A) -- operationally grounded, and SELECTED:
                        matching correlates with having traded, so this
                        column is labelled as a subset, never as the truth

Metrics ranked, London's 33 local authorities only, with n-floors:

  pre_deadline_share    share of deaths since 2018 that occurred before
                        first accounts were due (< 638 days, no accounts
                        evidence)  [floor: 200 deaths]
  survival_3y           3-year Kaplan-Meier register survival, companies
                        incorporated in the cost-of-living era
                        [floor: 150 at-risk companies]

Outputs: per-metric rankings under A/B/C, Spearman and Kendall rank
correlations between readings, counts of boroughs moving >=1/3/5/10 places,
and the concentration attribution -- how much of the A->B movement traces to
the top multi-company addresses. Written to out/rank_reversal.csv and the
log; the the pre-registered decision gate gate reads the summary at the bottom.
"""

from __future__ import annotations

import sys
from itertools import combinations

import pandas as pd

import config
import db
import survival
from ch_api import setup_logging

log = setup_logging("26_rank_reversal")

LONDON_33 = {
    "Barking and Dagenham", "Barnet", "Bexley", "Brent", "Bromley", "Camden",
    "City of London", "Croydon", "Ealing", "Enfield", "Greenwich", "Hackney",
    "Hammersmith and Fulham", "Haringey", "Harrow", "Havering", "Hillingdon",
    "Hounslow", "Islington", "Kensington and Chelsea", "Kingston upon Thames",
    "Lambeth", "Lewisham", "Merton", "Newham", "Redbridge",
    "Richmond upon Thames", "Southwark", "Sutton", "Tower Hamlets",
    "Waltham Forest", "Wandsworth", "Westminster",
}

DEATH_FLOOR = 200
SURV_FLOOR = 150

POPULATIONS = {
    "A_as_registered": "TRUE",
    "B_single_company": "c.companies_at_address = 1",
    "C_premises_confirmed": (
        "EXISTS (SELECT 1 FROM company_tier t "
        "WHERE t.company_number = c.company_number "
        "AND t.tier = 'A_premises_confirmed')"
    ),
}


def spearman(a: list[float], b: list[float]) -> float:
    """Spearman rank correlation, no ties expected at these sample sizes."""
    n = len(a)
    ra = {v: i for i, v in enumerate(sorted(a))}
    rb = {v: i for i, v in enumerate(sorted(b))}
    d2 = sum((ra[x] - rb[y]) ** 2 for x, y in zip(a, b))
    return 1 - 6 * d2 / (n * (n * n - 1))


def kendall(a: list[float], b: list[float]) -> float:
    conc = disc = 0
    for (i, j) in combinations(range(len(a)), 2):
        s = (a[i] - a[j]) * (b[i] - b[j])
        if s > 0:
            conc += 1
        elif s < 0:
            disc += 1
    pairs = len(a) * (len(a) - 1) / 2
    return (conc - disc) / pairs


def pre_deadline_by_borough(con, where: str) -> pd.DataFrame:
    return con.execute(
        f"""
        SELECT c.borough,
               count(*) AS deaths,
               sum(CASE WHEN c.accounts_last_made_up IS NULL
                         AND NOT EXISTS (SELECT 1 FROM accounts a
                                         WHERE a.company_number = c.company_number)
                         AND c.lifespan_days < 638 THEN 1 ELSE 0 END) AS pre_deadline
        FROM companies c
        WHERE c.outcome = 'dead' AND c.died >= DATE '{config.STUDY_START}'
          AND c.borough IS NOT NULL AND ({where})
        GROUP BY 1
        """
    ).df()


def survival_3y_by_borough(con, where: str) -> pd.DataFrame:
    rows = []
    frame = con.execute(
        f"""
        SELECT c.borough, c.lifespan_days,
               (c.outcome IN ('dead', 'failing')) AS event
        FROM companies c
        WHERE c.born >= DATE '2022-04-01' AND c.birth_era = 'cost_of_living'
          AND c.lifespan_days >= 0 AND c.borough IS NOT NULL AND ({where})
        """
    ).df()
    for borough, sub in frame.groupby("borough"):
        if len(sub) < SURV_FLOOR:
            continue
        km = survival.kaplan_meier(sub.lifespan_days.tolist(), sub.event.tolist())
        s3 = km.survival_at(1095)
        if s3 is not None:
            rows.append({"borough": borough, "n": len(sub), "survival_3y": s3})
    return pd.DataFrame(rows)


def rank_table(series: dict[str, pd.Series]) -> pd.DataFrame:
    """Boroughs present in every reading, ranked 1 = highest value."""
    common = set.intersection(*(set(s.index) for s in series.values()))
    out = pd.DataFrame(index=sorted(common))
    for name, s in series.items():
        out[name] = s.reindex(out.index)
        out[f"rank_{name}"] = out[name].rank(ascending=False, method="min").astype(int)
    return out


def movement(out: pd.DataFrame, frm: str, to: str) -> dict:
    moves = (out[f"rank_{frm}"] - out[f"rank_{to}"]).abs()
    return {
        "moved_1plus": int((moves >= 1).sum()),
        "moved_3plus": int((moves >= 3).sum()),
        "moved_5plus": int((moves >= 5).sum()),
        "moved_10plus": int((moves >= 10).sum()),
        "max_move": int(moves.max()),
        "spearman": round(spearman(out[frm].tolist(), out[to].tolist()), 3),
        "kendall": round(kendall(out[frm].tolist(), out[to].tolist()), 3),
    }


def main() -> int:
    con = db.connect(read_only=True, wait_seconds=600)
    all_rows = []

    for metric in ("pre_deadline_share", "survival_3y"):
        series = {}
        for pop, where in POPULATIONS.items():
            if metric == "pre_deadline_share":
                df = pre_deadline_by_borough(con, where)
                df = df[df.borough.isin(LONDON_33) & (df.deaths >= DEATH_FLOOR)]
                series[pop] = (df.set_index("borough").pre_deadline
                               / df.set_index("borough").deaths)
            else:
                df = survival_3y_by_borough(con, where)
                df = df[df.borough.isin(LONDON_33)]
                series[pop] = df.set_index("borough").survival_3y

        out = rank_table(series)
        log.info("")
        log.info("=" * 88)
        log.info("METRIC: %s   (%d boroughs pass every floor in every reading)",
                 metric, len(out))
        log.info("=" * 88)
        top = out.sort_values("rank_A_as_registered")
        log.info("  %-24s %6s %6s %6s", "borough",
                 "A rank", "B rank", "C rank")
        for borough, r in top.iterrows():
            flag = ""
            if abs(r.rank_A_as_registered - r.rank_B_single_company) >= 3:
                flag = "  <- moves"
            log.info("  %-24s %6d %6d %6d%s", borough,
                     r.rank_A_as_registered, r.rank_B_single_company,
                     r.rank_C_premises_confirmed, flag)

        for frm, to in (("A_as_registered", "B_single_company"),
                        ("A_as_registered", "C_premises_confirmed"),
                        ("B_single_company", "C_premises_confirmed")):
            m = movement(out, frm, to)
            log.info("  %s -> %s : moved>=1: %d  >=3: %d  >=5: %d  >=10: %d  "
                     "max: %d  spearman: %.3f  kendall: %.3f",
                     frm[0], to[0], m["moved_1plus"], m["moved_3plus"],
                     m["moved_5plus"], m["moved_10plus"], m["max_move"],
                     m["spearman"], m["kendall"])
            all_rows.append({"metric": metric, "from": frm, "to": to, **m})

        out.assign(metric=metric).to_csv(
            config.OUT / f"rank_reversal_{metric}.csv")

    # Attribution: how concentrated is the A->B difference? The companies
    # removed between the readings are exactly those at multi-company
    # addresses; count how many addresses account for half of them.
    removed = con.execute(
        f"""
        SELECT c.address_key, count(*) AS n
        FROM companies c
        WHERE c.outcome = 'dead' AND c.died >= DATE '{config.STUDY_START}'
          AND c.borough IS NOT NULL AND c.companies_at_address > 1
        GROUP BY 1 ORDER BY n DESC
        """
    ).df()
    total_removed = int(removed.n.sum())
    cum, k = 0, 0
    for n in removed.n:
        cum += int(n)
        k += 1
        if cum >= total_removed / 2:
            break
    log.info("")
    log.info("ATTRIBUTION: %s dead companies sit at multi-company addresses; "
             "half of them at just %s addresses (of %s such addresses).",
             f"{total_removed:,}", f"{k:,}", f"{len(removed):,}")

    pd.DataFrame(all_rows).to_csv(config.OUT / "rank_reversal.csv", index=False)
    log.info("")
    log.info("Gate summary written to out/rank_reversal.csv. the pre-registered decision gate "
             "decides: generalises -> the flip leads; small -> methods note.")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

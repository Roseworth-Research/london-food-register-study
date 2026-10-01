"""
Step 42 -- one canonical row per London borough, for the borough pages.

Every per-borough quantity a public page may show, computed in one place, for
the 33 London local authorities only (the neighbouring authorities that some
postcode districts reach into are excluded), keyed by ONS GSS code and by the
exact borough name the rest of the study uses.

Two readings are carried side by side wherever a rate is ranked, because the
study's central finding is that the ranking is unstable between them:

  A  as registered -- every cohort company at its registered office
  B  single-company addresses -- addresses holding exactly one cohort company

The premises-confirmed reading (C) is carried for completeness and must always
be labelled a selected subset.

Every rate carries its denominator and a publishable flag set by the same
floors the rank-reversal experiment uses (step 26): 200 deaths for the
pre-deadline share, 150 companies at risk for three-year survival. Counts are
publishable at 10 or more (config.MIN_CELL_SIZE).

Writes out/borough_sheets.csv.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

import config
import db
from ch_api import setup_logging

log = setup_logging("42_borough_sheets")

# ONS LAD (December 2023) codes, verified 1 October 2026 against the ONS
# Local_Authority_Districts_December_2023_Boundaries_UK_BUC service.
GSS = {
    "City of London": "E09000001", "Barking and Dagenham": "E09000002",
    "Barnet": "E09000003", "Bexley": "E09000004", "Brent": "E09000005",
    "Bromley": "E09000006", "Camden": "E09000007", "Croydon": "E09000008",
    "Ealing": "E09000009", "Enfield": "E09000010", "Greenwich": "E09000011",
    "Hackney": "E09000012", "Hammersmith and Fulham": "E09000013",
    "Haringey": "E09000014", "Harrow": "E09000015", "Havering": "E09000016",
    "Hillingdon": "E09000017", "Hounslow": "E09000018", "Islington": "E09000019",
    "Kensington and Chelsea": "E09000020", "Kingston upon Thames": "E09000021",
    "Lambeth": "E09000022", "Lewisham": "E09000023", "Merton": "E09000024",
    "Newham": "E09000025", "Redbridge": "E09000026",
    "Richmond upon Thames": "E09000027", "Southwark": "E09000028",
    "Sutton": "E09000029", "Tower Hamlets": "E09000030",
    "Waltham Forest": "E09000031", "Wandsworth": "E09000032",
    "Westminster": "E09000033",
}

# Reuse step 26's definitions rather than restating them.
_spec = importlib.util.spec_from_file_location("rr", Path(__file__).with_name("26_rank_reversal.py"))
rr = importlib.util.module_from_spec(_spec)
sys.modules["rr"] = rr
_spec.loader.exec_module(rr)

READINGS = {"A": rr.POPULATIONS["A_as_registered"],
            "B": rr.POPULATIONS["B_single_company"],
            "C": rr.POPULATIONS["C_premises_confirmed"]}


def survival_all(con, where: str) -> pd.DataFrame:
    """Three-year survival for every borough, floor applied later, not here."""
    frame = con.execute(
        f"""
        SELECT c.borough, c.lifespan_days, (c.outcome IN ('dead', 'failing')) AS event
        FROM companies c
        WHERE c.born >= DATE '2022-04-01' AND c.birth_era = 'cost_of_living'
          AND c.lifespan_days >= 0 AND c.borough IS NOT NULL AND ({where})
        """
    ).df()
    rows = []
    for borough, sub in frame.groupby("borough"):
        km = rr.survival.kaplan_meier(sub.lifespan_days.tolist(), sub.event.tolist())
        rows.append({"borough": borough, "n": len(sub), "s3": km.survival_at(1095)})
    return pd.DataFrame(rows).set_index("borough")


def main() -> int:
    con = db.connect(read_only=True, wait_seconds=600)
    out = pd.DataFrame({"borough": list(GSS)}).set_index("borough")
    out.insert(0, "gss_code", [GSS[b] for b in out.index])

    counts = con.execute(
        """
        SELECT borough,
               count(*) AS cohort_all,
               sum(CASE WHEN companies_at_address = 1 THEN 1 ELSE 0 END) AS cohort_single,
               sum(CASE WHEN companies_at_address = 1 AND year(born) BETWEEN 2018 AND 2025 THEN 1 ELSE 0 END) AS formed_2018_2025,
               sum(CASE WHEN companies_at_address = 1 AND year(died) BETWEEN 2018 AND 2025 THEN 1 ELSE 0 END) AS removed_2018_2025,
               sum(CASE WHEN companies_at_address = 1 AND year(born) BETWEEN 2023 AND 2025 AND format = 'counter' THEN 1 ELSE 0 END) AS new_counter_2023_2025,
               sum(CASE WHEN companies_at_address = 1 AND year(born) BETWEEN 2023 AND 2025 AND format IN ('counter', 'service') THEN 1 ELSE 0 END) AS new_food_2023_2025
        FROM companies WHERE borough IS NOT NULL GROUP BY 1
        """
    ).df().set_index("borough")
    out = out.join(counts)
    out["net_2018_2025"] = out.formed_2018_2025 - out.removed_2018_2025
    # Share of the borough's register sitting at addresses that hold more than
    # one cohort company: the quantity that drives the rank instability.
    out["shared_address_share"] = 1 - out.cohort_single / out.cohort_all
    out["counter_share_new_2023_2025"] = out.new_counter_2023_2025 / out.new_food_2023_2025

    for r, where in READINGS.items():
        pdl = rr.pre_deadline_by_borough(con, where).set_index("borough")
        out[f"pre_deadline_deaths_{r}"] = pdl.deaths
        out[f"pre_deadline_share_{r}"] = pdl.pre_deadline / pdl.deaths
        sv = survival_all(con, where)
        out[f"survival_3y_n_{r}"] = sv.n
        out[f"survival_3y_{r}"] = sv.s3

    # Ranks only among boroughs passing the floor in BOTH readings A and B,
    # exactly as step 26 does, so the ranks here equal the published ones.
    for metric, nfield, floor in (("pre_deadline_share", "pre_deadline_deaths", rr.DEATH_FLOOR),
                                  ("survival_3y", "survival_3y_n", rr.SURV_FLOOR)):
        ok = pd.Series(True, index=out.index)
        for r in READINGS:
            ok &= out[f"{nfield}_{r}"].fillna(0) >= floor
        out[f"{metric}_ranked"] = ok
        for r in READINGS:
            out[f"{metric}_rank_{r}"] = (out[f"{metric}_{r}"].where(ok)
                                         .rank(ascending=False, method="min").astype("Int64"))
        out[f"{metric}_rank_move_AB"] = (out[f"{metric}_rank_A"] - out[f"{metric}_rank_B"]).abs()
        out[f"{metric}_publishable_B"] = out[f"{nfield}_B"].fillna(0) >= floor

    out["counts_publishable"] = out.formed_2018_2025 >= config.MIN_CELL_SIZE
    out = out.reset_index()
    out.to_csv(config.OUT / "borough_sheets.csv", index=False, float_format="%.4f")
    log.info("33 boroughs written to out/borough_sheets.csv")
    log.info("pre-deadline ranked: %d | survival ranked: %d | survival publishable (B): %d",
             out.pre_deadline_share_ranked.sum(), out.survival_3y_ranked.sum(),
             out.survival_3y_publishable_B.sum())
    log.info("pre-deadline rank leaders, B: %s",
             ", ".join(out.sort_values("pre_deadline_share_rank_B").borough.head(3)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

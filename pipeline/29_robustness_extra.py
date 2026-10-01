"""
Step 29 -- the remaining robustness battery, in one place.

1. PREMISES-CONFIRMED SURVIVAL. The counter/service comparison re-run on
   FSA-matched (Tier A) companies only. Reported as operationally grounded
   and SELECTED -- matching correlates with having traded and survived long
   enough to be inspected -- never as "more accurate".

2. DEFINITION SENSITIVITY. The counter/service binary is noisy in one known
   direction: 56102 (unlicensed restaurants and cafes) contains
   counter-service cafes. Re-run the headline under: 56102 reassigned to
   counter (the extreme reading); 56102 dropped; 47240 dropped.

3. ERA-BOUNDARY SENSITIVITY. Cost-of-living cohort start shifted a quarter
   either side of 1 April 2022.

Every run: 3-year KM register survival, cost-of-living-era incorporations,
gap and log-rank p. Written to out/robustness_extra.csv.
"""

from __future__ import annotations

import sys

import pandas as pd

import config
import db
import survival
from ch_api import setup_logging

log = setup_logging("29_robustness_extra")


def km_gap(con, label, where_extra="TRUE", counter_expr=None,
           born_from="2022-04-01") -> dict:
    counter_expr = counter_expr or "format = 'counter'"
    df = con.execute(
        f"""
        SELECT ({counter_expr}) AS is_counter, lifespan_days,
               (outcome IN ('dead','failing')) AS event
        FROM companies c
        WHERE born >= DATE '{born_from}'
          AND lifespan_days >= 0
          AND sic_primary IN ('56101','56102','56103','47240')
          AND ({where_extra})
        """
    ).df()
    a = df[df.is_counter]
    b = df[~df.is_counter]
    km_a = survival.kaplan_meier(a.lifespan_days.tolist(), a.event.tolist())
    km_b = survival.kaplan_meier(b.lifespan_days.tolist(), b.event.tolist())
    lr = survival.logrank_test(a.lifespan_days, a.event, b.lifespan_days, b.event)
    row = {
        "run": label,
        "counter_n": len(a), "service_n": len(b),
        "counter_3y": round(km_a.survival_at(1095), 4),
        "service_3y": round(km_b.survival_at(1095), 4),
        "gap_pp": round(100 * (km_a.survival_at(1095) - km_b.survival_at(1095)), 2),
        "p": lr["p"],
    }
    log.info("  %-46s counter %5.1f%% (n=%6s)  service %5.1f%% (n=%6s)  gap %+5.1f pp  p=%.2g",
             label, 100 * row["counter_3y"], f"{row['counter_n']:,}",
             100 * row["service_3y"], f"{row['service_n']:,}",
             row["gap_pp"], row["p"])
    return row


def main() -> int:
    con = db.connect(read_only=True, wait_seconds=600)
    rows = []

    log.info("3-year register survival, cost-of-living incorporations, under "
             "alternative specifications")
    log.info("")
    rows.append(km_gap(con, "baseline (as specified)"))
    rows.append(km_gap(
        con, "premises-confirmed only [SELECTED subset]",
        where_extra=("EXISTS (SELECT 1 FROM company_tier t "
                     "WHERE t.company_number = c.company_number "
                     "AND t.tier = 'A_premises_confirmed')")))
    rows.append(km_gap(
        con, "56102 reassigned to counter (extreme reading)",
        counter_expr="sic_primary IN ('56103','47240','56102')"))
    rows.append(km_gap(
        con, "56102 dropped entirely",
        where_extra="sic_primary <> '56102'"))
    rows.append(km_gap(
        con, "47240 dropped entirely",
        where_extra="sic_primary <> '47240'"))
    rows.append(km_gap(con, "era start a quarter earlier (2022-01-01)",
                       born_from="2022-01-01"))
    rows.append(km_gap(con, "era start a quarter later (2022-07-01)",
                       born_from="2022-07-01"))

    pd.DataFrame(rows).to_csv(config.OUT / "robustness_extra.csv", index=False)
    log.info("")
    log.info("Written to out/robustness_extra.csv. Reading guide: the finding "
             "holds if the gap stays negative and material in every row except "
             "possibly the extreme 56102 reassignment, which deliberately "
             "destroys the definition being tested.")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

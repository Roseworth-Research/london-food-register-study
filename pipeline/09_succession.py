"""
Step 9 -- succession: when a food business dies, what opens in its place?

This is the study's original contribution. Everyone can count restaurant
closures. The question nobody has asked of this dataset is what was
incorporated NEXT at the same premises, and whether the replacement is
systematically a counter format rather than a service format. That is
hypothesis H4, and it is where the thesis stops being an argument about
aggregate rates and becomes an argument about specific dining rooms becoming
specific hatches.

Matching rule
-------------
For each cohort company that died at a non-hub address, the successor is the
earliest company incorporated at the same normalised address inside a window
around the death:

    from  death date minus 12 months
    to    death date plus 36 months

The window opens BEFORE the death on purpose. A company's dissolution date is
not the date it stopped trading. A voluntary strike-off completes roughly three
months after the DS01 is filed, and a liquidation can run for years. The new
tenant is usually incorporated while the old company is still formally on the
register. Anchoring strictly on the dissolution date would systematically miss
the real successor and match the one after it.

The window is a judgement, so step 10 reruns the headline transition matrix at
(-6, +24) and (-18, +60) months and publishes all three. If the pattern only
appears at one window it is not a pattern.

What counts as a successor
--------------------------
Any company at the address, in any industry, incorporated in the window and
after the predecessor. Cohort companies (the four food SIC codes) are complete
-- living and dead, from the register pull. Non-food companies come from the
live bulk snapshot only, so a nail bar that opened and then closed is invisible.
That asymmetry undercounts non-food succession and is stated wherever these
figures appear.

What this is not
----------------
A registered office is not a trading address. A succession pair is evidence
consistent with a premises handover, not proof of one. Mass-registration
addresses are excluded (step 5) precisely because at those addresses the
inference is certainly false. Even after that exclusion the report says
"consistent with", never "shows".

Outputs
-------
`succession`         one row per dead cohort company: its successor or none
`succession_matrix`  the transition counts by era, format and successor type
"""

from __future__ import annotations

import sys

import config
import db
from ch_api import setup_logging

log = setup_logging("09_succession")

WINDOW_BEFORE_DAYS = 365
WINDOW_AFTER_DAYS = 1095

# Broad industry buckets for non-food successors, so the report can say what
# actually replaced the restaurants rather than quoting SIC codes at readers.
# Only the first two digits are matched, which is coarse but honest.
INDUSTRY_BUCKETS = {
    "47": "Retail (shops)",
    "56": "Food and drink service",
    "96": "Personal services (hair, beauty, laundry)",
    "68": "Property",
    "62": "IT and software",
    "70": "Management consultancy",
    "43": "Construction trades",
    "41": "Construction",
    "45": "Motor trades",
    "49": "Transport",
    "53": "Post and courier",
    "82": "Business support",
    "86": "Health",
    "85": "Education",
    "93": "Sports and recreation",
    "46": "Wholesale",
    "10": "Food manufacturing",
    "55": "Accommodation",
    "99": "Dormant or unclassified",
}

CREATE_SQL = """
        CREATE TABLE succession (
            predecessor_number   VARCHAR PRIMARY KEY,
            predecessor_name     VARCHAR,
            predecessor_format   VARCHAR,
            predecessor_sic      VARCHAR,
            death_date           DATE,
            death_era            VARCHAR,
            lifespan_years       DOUBLE,
            borough              VARCHAR,
            address_key          VARCHAR,
            companies_at_address INTEGER,
            successor_number     VARCHAR,
            successor_name       VARCHAR,
            successor_sic        VARCHAR,
            successor_sic_text   VARCHAR,
            successor_born       DATE,
            successor_format     VARCHAR,  -- counter / service / non_food
            successor_industry   VARCHAR,  -- readable bucket for non-food
            gap_days             INTEGER,  -- successor incorporation minus death
            transition           VARCHAR   -- e.g. 'service->counter', 'went_dark'
        )
"""


def main() -> int:
    con = db.connect()

    # The candidate pool: every company observed at a cohort address, whether
    # it is in the food cohort or not. Cohort companies carry a real format;
    # everything else is non_food with an industry bucket.
    con.execute("DROP VIEW IF EXISTS occupant_pool")
    con.execute(
        """
        CREATE VIEW occupant_pool AS
        SELECT
            c.address_key,
            c.company_number,
            c.company_name,
            c.sic_primary          AS sic,
            NULL                   AS sic_text,
            c.born,
            c.format               AS format
        FROM companies c
        WHERE c.address_key <> '' AND c.born IS NOT NULL
        UNION ALL
        SELECT
            o.address_key,
            o.company_number,
            o.company_name,
            o.sic_primary,
            o.sic_text,
            try_strptime(o.incorporated, '%d/%m/%Y')::DATE AS born,
            'non_food'
        FROM address_occupants o
        WHERE NOT o.in_cohort
          AND o.address_key <> ''
          AND try_strptime(o.incorporated, '%d/%m/%Y') IS NOT NULL
        """
    )

    log.info("Matching successors (window: death -%d days to +%d days)",
             WINDOW_BEFORE_DAYS, WINDOW_AFTER_DAYS)

    con.execute("DROP TABLE IF EXISTS succession")
    con.execute(CREATE_SQL)
    con.execute(
        f"""
        INSERT INTO succession
        WITH dead AS (
            SELECT * FROM companies
            WHERE outcome = 'dead'
              AND died IS NOT NULL
              AND died >= DATE '{config.STUDY_START}'
              AND address_key <> ''
              AND NOT at_hub
        ),
        matched AS (
            SELECT
                d.company_number AS predecessor_number,
                p.company_number AS successor_number,
                p.company_name   AS successor_name,
                p.sic            AS successor_sic,
                p.sic_text       AS successor_sic_text,
                p.born           AS successor_born,
                p.format         AS successor_format,
                date_diff('day', d.died, p.born) AS gap_days,
                row_number() OVER (
                    PARTITION BY d.company_number ORDER BY p.born, p.company_number
                ) AS rn
            FROM dead d
            JOIN occupant_pool p
              ON p.address_key = d.address_key
             AND p.company_number <> d.company_number
             AND p.born > d.born
             AND p.born BETWEEN d.died - INTERVAL {WINDOW_BEFORE_DAYS} DAY
                            AND d.died + INTERVAL {WINDOW_AFTER_DAYS} DAY
        )
        SELECT
            d.company_number,
            d.company_name,
            d.format,
            d.sic_primary,
            d.died,
            d.death_era,
            d.lifespan_years,
            d.borough,
            d.address_key,
            d.companies_at_address,
            m.successor_number,
            m.successor_name,
            m.successor_sic,
            m.successor_sic_text,
            m.successor_born,
            m.successor_format,
            CASE
                WHEN m.successor_format IN ('counter', 'service') THEN 'Food and drink service'
                WHEN m.successor_sic IS NULL THEN NULL
                ELSE COALESCE(
                    (SELECT b.label FROM (VALUES {_bucket_values()}) AS b(prefix, label)
                     WHERE b.prefix = substr(m.successor_sic, 1, 2)),
                    'Other')
            END AS successor_industry,
            CAST(m.gap_days AS INTEGER),
            CASE
                WHEN m.successor_number IS NULL THEN 'went_dark'
                WHEN m.successor_format = 'non_food' THEN d.format || '->non_food'
                ELSE d.format || '->' || m.successor_format
            END AS transition
        FROM dead d
        LEFT JOIN matched m
               ON m.predecessor_number = d.company_number AND m.rn = 1
        """
    )

    total = con.execute("SELECT count(*) FROM succession").fetchone()[0]
    with_successor = con.execute(
        "SELECT count(*) FROM succession WHERE successor_number IS NOT NULL"
    ).fetchone()[0]
    log.info(
        "Dead cohort companies at real (non-hub) addresses since %s: %s",
        config.STUDY_START, f"{total:,}",
    )
    log.info(
        "  with an identifiable successor: %s (%.1f%%); went dark: %s (%.1f%%)",
        f"{with_successor:,}", 100 * with_successor / max(total, 1),
        f"{total - with_successor:,}", 100 * (total - with_successor) / max(total, 1),
    )

    log.info("--- transition matrix, all eras ---")
    for transition, n in con.execute(
        "SELECT transition, count(*) FROM succession GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall():
        log.info("  %-24s %7s  (%.1f%%)", transition, f"{n:,}", 100 * n / max(total, 1))

    log.info("--- food-to-food transitions only, by era of death ---")
    rows = con.execute(
        """
        SELECT death_era, predecessor_format,
               sum(CASE WHEN successor_format = 'counter' THEN 1 ELSE 0 END) AS to_counter,
               sum(CASE WHEN successor_format = 'service' THEN 1 ELSE 0 END) AS to_service,
               count(*) AS n
        FROM succession
        WHERE successor_format IN ('counter','service') AND death_era IS NOT NULL
        GROUP BY 1,2 ORDER BY 1,2
        """
    ).fetchall()
    for era, fmt, to_counter, to_service, n in rows:
        if n < config.MIN_CELL_SIZE:
            log.info("  %-15s %-8s n=%s below the reporting floor, suppressed", era, fmt, n)
            continue
        log.info("  %-15s %-8s -> counter %5s (%4.1f%%)  -> service %5s (%4.1f%%)  n=%s",
                 era, fmt, f"{to_counter:,}", 100 * to_counter / n,
                 f"{to_service:,}", 100 * to_service / n, f"{n:,}")

    log.info("--- what replaced a food business, when it was not food ---")
    for industry, n in con.execute(
        """
        SELECT successor_industry, count(*) FROM succession
        WHERE successor_format = 'non_food' AND successor_industry IS NOT NULL
        GROUP BY 1 ORDER BY 2 DESC LIMIT 15
        """
    ).fetchall():
        log.info("  %-42s %6s", industry, f"{n:,}")

    log.info("--- median years a business lasted before being replaced ---")
    for fmt, era, med, n in con.execute(
        """
        SELECT predecessor_format, death_era, median(lifespan_years), count(*)
        FROM succession WHERE death_era IS NOT NULL
        GROUP BY 1,2 ORDER BY 1,2
        """
    ).fetchall():
        log.info("  %-8s %-15s %.1f years  n=%s", fmt, era, med, f"{n:,}")

    db.append_flow(
        con,
        [
            ("09", "succession_predecessors", total,
             "Cohort deaths since 2018 at non-hub addresses, eligible for succession matching"),
            ("09", "succession_matched", with_successor,
             "Deaths with an identifiable successor incorporated at the same address"),
            ("09", "succession_went_dark", total - with_successor,
             "No successor observed in the window; note non-food successors are live-only"),
        ],
    )
    con.close()
    return 0


def _bucket_values() -> str:
    """Render the industry bucket map as a SQL VALUES list."""
    return ", ".join(f"('{k}', '{v}')" for k, v in INDUSTRY_BUCKETS.items())


if __name__ == "__main__":
    sys.exit(main())

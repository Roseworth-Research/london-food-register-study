"""
Step 11 -- plain-numbers exports.

Everything a person would want to look at in a spreadsheet or drop into a
chart, written to out/ as CSV. No statistics here, no interpretation: just the
counts, so that anyone can check a figure quoted in the report against the
table it came from.

Cells below the reporting floor (config.MIN_CELL_SIZE) are kept in these files
because they are public-record counts, not portfolio figures -- the floor in
the study brief governs client data. But any borough-level cell with a
small n is flagged so it does not get charted as if it were solid.
"""

from __future__ import annotations

import sys

import config
import db
from ch_api import setup_logging

log = setup_logging("11_exports")

EXPORTS: dict[str, str] = {
    # --- openings ---------------------------------------------------------
    "openings_by_year_format": """
        SELECT year(born) AS year, format, count(*) AS companies
        FROM companies WHERE born IS NOT NULL
        GROUP BY 1,2 ORDER BY 1,2
    """,
    "openings_by_year_sic": """
        SELECT year(born) AS year, sic_primary, format, count(*) AS companies
        FROM companies WHERE born IS NOT NULL
        GROUP BY 1,2,3 ORDER BY 1,2
    """,
    "openings_by_borough_era": """
        SELECT borough, birth_era, format, count(*) AS companies
        FROM companies
        WHERE borough IS NOT NULL AND birth_era IS NOT NULL
        GROUP BY 1,2,3 ORDER BY 1,2,3
    """,
    # --- closures ---------------------------------------------------------
    "closures_by_year_format": """
        SELECT year(died) AS year, format, count(*) AS companies
        FROM companies WHERE died IS NOT NULL
        GROUP BY 1,2 ORDER BY 1,2
    """,
    "closures_by_borough_era": """
        SELECT borough, death_era, format, count(*) AS companies
        FROM companies
        WHERE borough IS NOT NULL AND death_era IS NOT NULL
        GROUP BY 1,2,3 ORDER BY 1,2,3
    """,
    # --- the current state of the register --------------------------------
    "outcomes_by_format": """
        SELECT outcome, format, sic_primary, count(*) AS companies
        FROM companies GROUP BY 1,2,3 ORDER BY 1,2,3
    """,
    "outcomes_by_borough": """
        SELECT borough, format, outcome, count(*) AS companies
        FROM companies WHERE borough IS NOT NULL
        GROUP BY 1,2,3 ORDER BY 1,2,3
    """,
    # --- how long they lasted ---------------------------------------------
    "lifespan_summary": """
        SELECT death_era, format, count(*) AS died,
               round(median(lifespan_years), 2)              AS median_years,
               round(quantile_cont(lifespan_years, 0.25), 2) AS q1_years,
               round(quantile_cont(lifespan_years, 0.75), 2) AS q3_years,
               round(min(lifespan_years), 2)                 AS min_years,
               round(max(lifespan_years), 2)                 AS max_years
        FROM companies
        WHERE died IS NOT NULL AND death_era IS NOT NULL
        GROUP BY 1,2 ORDER BY 1,2
    """,
    "lifespan_buckets": """
        SELECT format, death_era,
               CASE
                   WHEN lifespan_years < 1  THEN 'under 1 year'
                   WHEN lifespan_years < 2  THEN '1 to 2 years'
                   WHEN lifespan_years < 3  THEN '2 to 3 years'
                   WHEN lifespan_years < 5  THEN '3 to 5 years'
                   WHEN lifespan_years < 10 THEN '5 to 10 years'
                   ELSE '10 years or more'
               END AS bucket,
               count(*) AS companies
        FROM companies WHERE died IS NOT NULL AND death_era IS NOT NULL
        GROUP BY 1,2,3 ORDER BY 1,2,3
    """,
    # --- net churn: openings minus closures, the high-street scorecard -----
    "net_churn_by_borough_year": """
        WITH b AS (
            SELECT borough, year(born) AS year, format, count(*) AS opened
            FROM companies WHERE borough IS NOT NULL AND born IS NOT NULL
            GROUP BY 1,2,3
        ),
        d AS (
            SELECT borough, year(died) AS year, format, count(*) AS closed
            FROM companies WHERE borough IS NOT NULL AND died IS NOT NULL
            GROUP BY 1,2,3
        )
        SELECT COALESCE(b.borough, d.borough) AS borough,
               COALESCE(b.year, d.year)       AS year,
               COALESCE(b.format, d.format)   AS format,
               COALESCE(b.opened, 0)          AS opened,
               COALESCE(d.closed, 0)          AS closed,
               COALESCE(b.opened, 0) - COALESCE(d.closed, 0) AS net
        FROM b FULL OUTER JOIN d
          ON b.borough = d.borough AND b.year = d.year AND b.format = d.format
        ORDER BY 1,2,3
    """,
    # --- succession -------------------------------------------------------
    "succession_matrix": """
        SELECT death_era, predecessor_format, successor_format,
               successor_industry, count(*) AS n
        FROM succession GROUP BY 1,2,3,4 ORDER BY 1,2,3,5 DESC
    """,
    "succession_by_borough": """
        SELECT borough, death_era, transition, count(*) AS n
        FROM succession WHERE borough IS NOT NULL
        GROUP BY 1,2,3 ORDER BY 1,2,3
    """,
    "succession_gap_days": """
        SELECT predecessor_format, successor_format,
               count(*) AS n,
               round(median(gap_days))                  AS median_gap_days,
               round(quantile_cont(gap_days, 0.25))     AS q1_gap_days,
               round(quantile_cont(gap_days, 0.75))     AS q3_gap_days
        FROM succession WHERE successor_number IS NOT NULL
        GROUP BY 1,2 ORDER BY 1,2
    """,
    # --- who is opening what, at former food premises ---------------------
    "successor_industries": """
        SELECT predecessor_format, successor_industry, count(*) AS n
        FROM succession
        WHERE successor_format = 'non_food' AND successor_industry IS NOT NULL
        GROUP BY 1,2 ORDER BY 1, 3 DESC
    """,
    "successor_sic_detail": """
        SELECT successor_sic, any_value(successor_sic_text) AS description,
               count(*) AS n
        FROM succession
        WHERE successor_format = 'non_food' AND successor_sic IS NOT NULL
        GROUP BY 1 ORDER BY 3 DESC LIMIT 60
    """,
    # --- geography and provenance -----------------------------------------
    "cohort_by_borough": """
        SELECT borough, format, count(*) AS companies,
               sum(CASE WHEN outcome = 'alive' THEN 1 ELSE 0 END) AS still_trading,
               sum(CASE WHEN at_hub THEN 1 ELSE 0 END) AS at_agent_address
        FROM companies WHERE borough IS NOT NULL
        GROUP BY 1,2 ORDER BY 1,2
    """,
    "cohort_flow": "SELECT * FROM cohort_flow ORDER BY step, stage",
}

# Exports that need a table produced by a later or longer-running step.
OPTIONAL = {
    "succession_matrix": "succession",
    "succession_by_borough": "succession",
    "succession_gap_days": "succession",
    "successor_industries": "succession",
    "successor_sic_detail": "succession",
    "exit_routes_by_format": "company_exit",
    "exit_routes_by_era": "company_exit",
}

EXPORTS["exit_routes_by_format"] = """
    SELECT c.format, c.sic_primary, c.exit_route, count(*) AS n
    FROM companies c WHERE c.exit_route IS NOT NULL
    GROUP BY 1,2,3 ORDER BY 1,2,4 DESC
"""
EXPORTS["exit_routes_by_era"] = """
    SELECT c.death_era, c.format, c.exit_route, count(*) AS n
    FROM companies c WHERE c.exit_route IS NOT NULL AND c.death_era IS NOT NULL
    GROUP BY 1,2,3 ORDER BY 1,2,4 DESC
"""


def main() -> int:
    con = db.connect(read_only=True, wait_seconds=300)
    existing = {
        r[0]
        for r in con.execute(
            "SELECT table_name FROM information_schema.tables"
        ).fetchall()
    }

    written = skipped = 0
    for name, sql in EXPORTS.items():
        needs = OPTIONAL.get(name)
        if needs and needs not in existing:
            log.info("  %-28s skipped (needs table '%s')", name, needs)
            skipped += 1
            continue
        try:
            frame = con.execute(sql).fetch_df()
        except Exception as e:
            log.warning("  %-28s failed: %s", name, e)
            skipped += 1
            continue
        path = config.OUT / f"{name}.csv"
        frame.to_csv(path, index=False)
        log.info("  %-28s %6s rows  ->  %s", name, f"{len(frame):,}", path.name)
        written += 1

    con.close()
    log.info("")
    log.info("%d exports written, %d skipped, in %s", written, skipped, config.OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())

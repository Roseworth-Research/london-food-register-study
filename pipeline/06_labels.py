"""
Step 6 -- build the master company table: one row per business, fully labelled.

Everything the analysis needs about WHO a company is lands here. Later steps
add what it DID (filings, charges, ownership, accounts) and what happened to
its premises (succession).

The register pull in step 3 is the authoritative spine because it contains the
dead as well as the living. The bulk snapshot from step 1 is joined on top for
the handful of fields the search API does not return -- the care-of agent, the
accounts reference dates and the mortgage charge counts -- and as a
cross-check: any company in the snapshot that the register walk missed is
reported, because a gap there would mean the district walk was incomplete.

Labels applied
--------------
  format          counter or service (from SIC; see config.py for why)
  outcome         alive / failing / closing / dead
  born, died      incorporation and cessation dates
  birth_era       which of the four eras the company was incorporated in
  death_era       which era it died in, if it died
  lifespan_days   died - born, or (snapshot date - born) if still alive
  censored        TRUE when still alive at the snapshot date, so survival
                  analysis treats it as right-censored rather than as a
                  company that lived exactly that long and stopped
  borough         from the full-postcode lookup in step 4
  at_hub          registered at a mass-registration address (step 5)
  young           less than two full trading years, excluded from growth stats

On the difference between dying and failing
-------------------------------------------
A dissolved company is not necessarily a failed business. Owners retire,
restructure, or sell. `outcome` records what the register says; the exit
route -- solvent strike-off versus insolvent liquidation -- is derived from
filing history in step 7 and written back into this table as `exit_route`.
Until then it is NULL, and no count of "closures" should be published without
it.
"""

from __future__ import annotations

import sys

import config
import db
from ch_api import setup_logging

log = setup_logging("06_labels")

CREATE_SQL = """
        CREATE TABLE companies (
            company_number    VARCHAR PRIMARY KEY,
            company_name      VARCHAR,
            company_type      VARCHAR,
            status_raw        VARCHAR,
            outcome           VARCHAR,   -- alive / failing / closing / dead
            exit_route        VARCHAR,   -- filled by step 7 from filing history
            sic_primary       VARCHAR,
            sic_all           VARCHAR,
            format            VARCHAR,   -- counter / service
            sic_mixed         BOOLEAN,   -- carries both format codes; drop in sensitivity runs
            born              DATE,
            died              DATE,
            birth_era         VARCHAR,
            death_era         VARCHAR,
            lifespan_days     INTEGER,
            lifespan_years    DOUBLE,
            censored          BOOLEAN,   -- still alive at the snapshot date
            postcode          VARCHAR,
            postcode_district VARCHAR,
            borough           VARCHAR,
            borough_method    VARCHAR,   -- how the borough was resolved (step 4)
            address_key       VARCHAR,
            addr1             VARCHAR,
            addr2             VARCHAR,
            companies_at_address INTEGER,
            at_hub            BOOLEAN,   -- mass-registration address (step 5)
            care_of           VARCHAR,
            young             BOOLEAN,   -- under two trading years at death or snapshot
            in_snapshot       BOOLEAN,   -- also present in the live bulk file
            accounts_last_made_up VARCHAR,
            accounts_category VARCHAR,
            charges_total     INTEGER,
            charges_outstanding INTEGER,
            source            VARCHAR    -- register walk, or snapshot only
        )
"""

ERA_CASE = " ".join(
    f"WHEN {{col}} BETWEEN DATE '{start}' AND DATE '{end}' THEN '{name}'"
    for name, start, end, _ in config.ERAS
)


def era_sql(column: str) -> str:
    return f"CASE {ERA_CASE.format(col=column)} ELSE NULL END"


def main() -> int:
    con = db.connect()

    for table in ("companies_register", "postcode_borough", "address_hubs"):
        exists = con.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = ?",
            [table],
        ).fetchone()[0]
        if not exists:
            log.error("Table %s is missing. Run the earlier steps first.", table)
            return 1

    con.execute("DROP TABLE IF EXISTS companies")
    con.execute(CREATE_SQL)

    con.execute(
        f"""
        INSERT INTO companies
        SELECT
            r.company_number,
            r.company_name,
            r.company_type,
            r.status_raw,
            -- The advanced-search API reports a company in strike-off
            -- proceedings simply as 'active'; the detail sits in a field the
            -- search does not return. The bulk snapshot does carry it, so
            -- where the register says the company is ALIVE and the snapshot
            -- says 'Active - Proposal to Strike off', the snapshot detail wins.
            --
            -- The guard on r.status_group = 'alive' matters. An earlier version
            -- let the snapshot's 'closing' override ANY register status, which
            -- silently relabelled 2,211 companies that were in strike-off
            -- proposal in the March snapshot and then actually died before the
            -- August register pull. The register, being later, is authoritative
            -- for them: they are dead, not closing. Found during count
            -- reconciliation in external review (corrections log #9).
            CASE
                WHEN r.status_group = 'alive' AND l.status_group = 'closing'
                    THEN 'closing'
                ELSE r.status_group
            END                                                     AS outcome,
            NULL                                                    AS exit_route,
            r.sic_primary,
            r.sic_all,
            r.format,
            r.sic_mixed,
            r.date_of_creation                                      AS born,
            r.date_of_cessation                                     AS died,
            {era_sql('r.date_of_creation')}                         AS birth_era,
            {era_sql('r.date_of_cessation')}                        AS death_era,
            -- Register-sourced companies are observed to the August walk, so
            -- survivors are censored at OBSERVATION_DATE. Using SNAPSHOT_DATE
            -- here while counting register-walk deaths was audit finding B2:
            -- events after every censoring time, wrong risk sets.
            CAST(
                date_diff('day', r.date_of_creation,
                          COALESCE(r.date_of_cessation, DATE '{config.OBSERVATION_DATE}'))
                AS INTEGER)                                         AS lifespan_days,
            date_diff('day', r.date_of_creation,
                      COALESCE(r.date_of_cessation, DATE '{config.OBSERVATION_DATE}')) / 365.25
                                                                    AS lifespan_years,
            r.date_of_cessation IS NULL                             AS censored,
            r.postcode,
            r.postcode_district,
            pb.borough,
            pb.method                                               AS borough_method,
            r.address_key,
            r.addr1,
            r.addr2,
            COALESCE(h.companies_at_key, 0)                         AS companies_at_address,
            COALESCE(h.is_hub, FALSE)                               AS at_hub,
            COALESCE(l.care_of, '')                                 AS care_of,
            date_diff('day', r.date_of_creation,
                      COALESCE(r.date_of_cessation, DATE '{config.OBSERVATION_DATE}'))
                < {config.MIN_TRADING_YEARS_FOR_GROWTH} * 365       AS young,
            l.company_number IS NOT NULL                            AS in_snapshot,
            l.accounts_last_made_up,
            l.accounts_category,
            COALESCE(l.charges_total, 0),
            COALESCE(l.charges_outstanding, 0),
            'register'                                              AS source
        FROM companies_register r
        LEFT JOIN postcode_borough pb ON pb.postcode = r.postcode
        LEFT JOIN address_hubs   h  ON h.address_key = r.address_key
        LEFT JOIN companies_live l  ON l.company_number = r.company_number
        """
    )

    from_register = con.execute("SELECT count(*) FROM companies").fetchone()[0]
    log.info("From the register walk: %s companies", f"{from_register:,}")

    # The register walk is a snapshot of TODAY's registered offices; the bulk
    # file is a snapshot of March's. Registered offices move constantly -- of
    # twelve missing companies sampled on 2026-08-16, eleven had relocated out
    # of London between the two dates, several from formation-agent addresses
    # to their owners' home counties. A company that traded in London during
    # the study window belongs in the cohort whether or not it is registered
    # here today, so the two sources are unioned rather than intersected.
    #
    # Only companies in a genuine London district are added: the step 1
    # postcode-area filter was deliberately generous and admitted Hertfordshire
    # and Surrey addresses that the borough lookup correctly rejects.
    con.execute(
        f"""
        INSERT INTO companies
        SELECT
            l.company_number, l.company_name, 'ltd', l.status_raw, l.status_group,
            NULL, l.sic_primary, l.sic_all, l.format, l.sic_mixed,
            l.incorporated, NULL,
            {era_sql('l.incorporated')}, NULL,
            -- Snapshot-only companies were last observed alive on the
            -- SNAPSHOT date (their registered office left London before the
            -- August walk, so the walk never saw them). Censoring them in
            -- March is per-source honesty, not the B2 bug: within this
            -- source there are no events after the censoring date.
            CAST(date_diff('day', l.incorporated, DATE '{config.SNAPSHOT_DATE}') AS INTEGER),
            date_diff('day', l.incorporated, DATE '{config.SNAPSHOT_DATE}') / 365.25,
            TRUE,
            l.postcode, l.postcode_district, pb.borough, pb.method,
            l.address_key, l.addr1, l.addr2,
            COALESCE(h.companies_at_key, 0), COALESCE(h.is_hub, FALSE),
            l.care_of,
            date_diff('day', l.incorporated, DATE '{config.SNAPSHOT_DATE}')
                < {config.MIN_TRADING_YEARS_FOR_GROWTH} * 365,
            TRUE,
            l.accounts_last_made_up, l.accounts_category,
            COALESCE(l.charges_total, 0), COALESCE(l.charges_outstanding, 0),
            'snapshot_only'
        FROM companies_live l
        JOIN postcode_districts d
          ON d.district = l.postcode_district AND d.is_london
        LEFT JOIN postcode_borough pb ON pb.postcode = l.postcode
        LEFT JOIN address_hubs    h  ON h.address_key = l.address_key
        WHERE NOT EXISTS (
            SELECT 1 FROM companies c WHERE c.company_number = l.company_number
        )
        """
    )
    added = con.execute(
        "SELECT count(*) FROM companies WHERE source = 'snapshot_only'"
    ).fetchone()[0]
    excluded = con.execute(
        """
        SELECT count(*) FROM companies_live l
        WHERE NOT EXISTS (SELECT 1 FROM companies c WHERE c.company_number = l.company_number)
        """
    ).fetchone()[0]
    total = con.execute("SELECT count(*) FROM companies").fetchone()[0]
    log.info(
        "Added from the bulk snapshot alone: %s (registered office moved out of "
        "London between March and August, or missed by the location search)",
        f"{added:,}",
    )
    log.info(
        "Left out: %s snapshot companies whose postcode district is not in a "
        "London borough (the step 1 area filter was deliberately generous)",
        f"{excluded:,}",
    )
    log.info("Master table built: %s companies", f"{total:,}")

    log.info("--- outcome by format ---")
    for outcome, fmt, n in con.execute(
        "SELECT outcome, format, count(*) FROM companies GROUP BY 1,2 ORDER BY 1,2"
    ).fetchall():
        log.info("  %-8s %-8s %8s", outcome, fmt, f"{n:,}")

    log.info("--- births per era, per year of era (rate, not count) ---")
    for era, fmt, n in con.execute(
        "SELECT birth_era, format, count(*) FROM companies "
        "WHERE birth_era IS NOT NULL GROUP BY 1,2 ORDER BY 1,2"
    ).fetchall():
        log.info("  %-15s %-8s %7s  (%6.0f/yr)", era, fmt, f"{n:,}",
                 n / config.era_length_years(era))

    log.info("--- deaths per era, per year of era ---")
    for era, fmt, n in con.execute(
        "SELECT death_era, format, count(*) FROM companies "
        "WHERE death_era IS NOT NULL GROUP BY 1,2 ORDER BY 1,2"
    ).fetchall():
        log.info("  %-15s %-8s %7s  (%6.0f/yr)", era, fmt, f"{n:,}",
                 n / config.era_length_years(era))

    log.info("--- median lifespan of companies that died, by era of death ---")
    for era, fmt, n, med in con.execute(
        """
        SELECT death_era, format, count(*), median(lifespan_years)
        FROM companies WHERE died IS NOT NULL AND death_era IS NOT NULL
        GROUP BY 1,2 ORDER BY 1,2
        """
    ).fetchall():
        log.info("  %-15s %-8s n=%-6s median %.1f years", era, fmt, f"{n:,}", med)

    unresolved = con.execute(
        "SELECT count(*) FROM companies WHERE borough IS NULL"
    ).fetchone()[0]
    log.info("Companies without a resolved borough: %s (%.2f%%)",
             f"{unresolved:,}", 100 * unresolved / max(total, 1))

    db.append_flow(
        con,
        [
            ("06", "master_companies", total,
             "One row per London cohort company, living and dead, fully labelled"),
            ("06", "from_register_walk", from_register,
             "Found by the August 2026 register walk; includes all dissolved companies"),
            ("06", "from_snapshot_only", added,
             "In the March 2026 bulk file only; registered office moved before August"),
            ("06", "snapshot_outside_london", excluded,
             "Snapshot companies whose district is not in a London borough; excluded"),
            ("06", "borough_unresolved", unresolved,
             "No borough; excluded from borough-level analysis only"),
        ],
    )
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

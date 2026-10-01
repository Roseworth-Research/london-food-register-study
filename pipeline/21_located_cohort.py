"""
Step 21 -- where was each company actually located, and can we place it at all?

This step replaces "the registered office as it stands today" with the best
available estimate of where a company was while it was trading, and then sorts
the cohort into three honest tiers of geographic confidence.

Why it is needed
----------------
Two findings from steps 18 and 20 make the current registered office unusable
for neighbourhood analysis:

  * **72.0%** of companies with an address history are registered somewhere
    different today from where they were before their exit began, and for
    companies that reached insolvency it is **87.8%** -- because entering
    liquidation moves the registered office to the practitioner.
  * **31.6%** of the cohort sits at a mass-registration address: an
    accountant, a formation agent, a virtual office. Those companies are not
    in that neighbourhood in any meaningful sense. Leaving them in dilutes
    every borough figure, and concentrates them wherever the agents happen to
    be.

Best-known address
------------------
For each company, in order of preference:

  1. the address held immediately before the first insolvency or strike-off
     filing (from AD01 filings, step 20);
  2. the earliest address on record;
  3. the current registered office.

Three tiers of confidence
-------------------------
  **A -- premises-confirmed.** The company matches a Food Standards Agency
  food establishment on any of its known addresses. We know roughly where it
  was and we have independent evidence it traded: a hygiene rating cannot be
  held without operating.

  **B -- located, unconfirmed.** An ordinary address that resolves to a
  borough, with no FSA match. It is somewhere real, but it may be a home
  address, a premises the FSA lists differently, or a company that never
  opened.

  **C -- unlocated.** The best-known address is a mass-registration address.
  The borough is the agent's, not the business's. **These companies are
  excluded from every geographic figure and reported separately as a known
  unknown**, because pretending to know where they are would be worse than
  admitting we do not.
"""

from __future__ import annotations

import sys

import config
import db
from ch_api import setup_logging

log = setup_logging("21_located_cohort")


def main() -> int:
    con = db.connect(wait_seconds=600)

    for t in ("address_history", "fsa_establishments", "address_hubs"):
        if not con.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name=?", [t]
        ).fetchone()[0]:
            log.error("Missing table %s -- run the earlier steps first.", t)
            return 1

    log.info("Building best-known address for every company")
    con.execute("DROP TABLE IF EXISTS company_location")
    con.execute("""
        CREATE TABLE company_location AS
        WITH best AS (
            SELECT
                c.company_number,
                c.format, c.sic_primary, c.outcome, c.born, c.died,
                c.lifespan_days, c.birth_era, c.death_era,
                -- Preference order: pre-exit, then earliest, then current.
                COALESCE(NULLIF(a.pre_exit_key,''), NULLIF(a.first_key,''),
                         NULLIF(c.address_key,'')) AS best_key,
                COALESCE(NULLIF(a.pre_exit_postcode,''), NULLIF(a.first_postcode,''),
                         NULLIF(c.postcode,'')) AS best_postcode,
                CASE
                    WHEN NULLIF(a.pre_exit_key,'') IS NOT NULL THEN 'pre_exit'
                    WHEN NULLIF(a.first_key,'')    IS NOT NULL THEN 'first_known'
                    ELSE 'current'
                END AS address_source,
                c.address_key AS current_key
            FROM companies c
            LEFT JOIN address_history a USING (company_number)
        )
        SELECT b.*,
               h.is_hub                       AS best_is_hub,
               COALESCE(h.companies_at_key,0) AS companies_at_best,
               pb.borough                     AS best_borough
        FROM best b
        LEFT JOIN address_hubs h ON h.address_key = b.best_key
        LEFT JOIN postcode_borough pb ON pb.postcode = b.best_postcode
    """)

    log.info("Matching every known address against FSA premises")
    con.execute("DROP TABLE IF EXISTS company_premises")
    con.execute("""
        CREATE TABLE company_premises AS
        SELECT DISTINCT c.company_number, f.fhrsid, f.business_type
        FROM companies c
        LEFT JOIN address_history a USING (company_number)
        -- Candidate address keys live in their own table since step 39: an
        -- establishment has several (the two registers order address lines
        -- differently), and holding them as rows of the establishment table
        -- meant anything counting rows counted each premises several times.
        JOIN fsa_address_keys k
          ON k.address_key = c.address_key
          OR k.address_key = a.pre_exit_key
          OR k.address_key = a.first_key
        JOIN fsa_establishments f ON f.fhrsid = k.fhrsid
    """)

    con.execute("DROP TABLE IF EXISTS company_tier")
    con.execute("""
        CREATE TABLE company_tier AS
        SELECT l.*,
               p.company_number IS NOT NULL AS premises_confirmed,
               CASE
                   WHEN p.company_number IS NOT NULL           THEN 'A_premises_confirmed'
                   WHEN COALESCE(l.best_is_hub,FALSE)          THEN 'C_unlocated'
                   WHEN l.best_borough IS NOT NULL             THEN 'B_located_unconfirmed'
                   ELSE 'C_unlocated'
               END AS tier
        FROM company_location l
        LEFT JOIN (SELECT DISTINCT company_number FROM company_premises) p
               USING (company_number)
    """)

    total = con.execute("SELECT count(*) FROM company_tier").fetchone()[0]
    log.info("")
    log.info("=" * 84)
    log.info("WHERE THE COHORT ACTUALLY IS")
    log.info("=" * 84)
    for tier, n in con.execute(
        "SELECT tier, count(*) FROM company_tier GROUP BY 1 ORDER BY 1"
    ).fetchall():
        log.info("  %-24s %8s  (%5.1f%%)", tier, f"{n:,}", 100 * n / total)

    log.info("")
    log.info("  Address used, by source:")
    for src, n in con.execute(
        "SELECT address_source, count(*) FROM company_tier GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall():
        log.info("    %-14s %8s  (%5.1f%%)", src, f"{n:,}", 100 * n / total)

    moved = con.execute("""
        SELECT count(*) FROM company_tier
        WHERE address_source <> 'current' AND best_key <> current_key
    """).fetchone()[0]
    log.info("  Companies now placed somewhere other than their current "
             "registered office: %s", f"{moved:,}")

    # ---- Tier A: the overview that can actually be trusted ----------------
    log.info("")
    log.info("=" * 84)
    log.info("TIER A -- PREMISES-CONFIRMED COMPANIES")
    log.info("Matched to an FSA food establishment: we know roughly where they were,")
    log.info("and a hygiene rating is independent evidence they traded.")
    log.info("=" * 84)
    a_total = con.execute(
        "SELECT count(*) FROM company_tier WHERE tier='A_premises_confirmed'"
    ).fetchone()[0]
    log.info("  companies: %s (%.1f%% of cohort)", f"{a_total:,}", 100 * a_total / total)

    log.info("")
    log.info("  %-9s %9s %10s %11s %12s", "format", "n", "dissolved", "insolvent", "median yrs")
    for fmt, n, dis, ins, med in con.execute("""
        SELECT t.format, count(*),
               sum(CASE WHEN t.outcome='dead' THEN 1 ELSE 0 END),
               sum(CASE WHEN e.exit_family='insolvency' THEN 1 ELSE 0 END),
               median(t.lifespan_days)/365.25
        FROM company_tier t LEFT JOIN company_exit_v2 e USING (company_number)
        WHERE t.tier='A_premises_confirmed' GROUP BY 1 ORDER BY 1
    """).fetchall():
        log.info("  %-9s %9s %9s (%2.0f%%) %8s (%4.1f%%) %11.1f",
                 fmt, f"{n:,}", f"{dis:,}", 100*dis/n, f"{ins:,}", 100*ins/n, med)

    log.info("")
    log.info("  Regulator's classification of the premises, by company SIC:")
    for sic, btype, n in con.execute("""
        SELECT t.sic_primary, p.business_type, count(DISTINCT t.company_number) AS n
        FROM company_tier t JOIN company_premises p USING (company_number)
        WHERE t.tier='A_premises_confirmed'
        GROUP BY 1,2 QUALIFY row_number() OVER (PARTITION BY t.sic_primary ORDER BY n DESC) <= 3
        ORDER BY t.sic_primary, n DESC
    """).fetchall():
        log.info("    %-7s %-38s %7s", sic, btype[:38], f"{n:,}")

    log.info("")
    log.info("  Top boroughs (Tier A only):")
    for b, n, ins, med in con.execute("""
        SELECT t.best_borough, count(*),
               sum(CASE WHEN e.exit_family='insolvency' THEN 1 ELSE 0 END),
               median(t.lifespan_days)/365.25
        FROM company_tier t LEFT JOIN company_exit_v2 e USING (company_number)
        WHERE t.tier='A_premises_confirmed' AND t.best_borough IS NOT NULL
        GROUP BY 1 ORDER BY 2 DESC LIMIT 10
    """).fetchall():
        log.info("    %-24s %6s companies  insolvent %5.2f%%  median %.1f yrs",
                 b[:24], f"{n:,}", 100*ins/n, med)

    # ---- Tier C: the known unknown ----------------------------------------
    log.info("")
    log.info("=" * 84)
    log.info("TIER C -- UNLOCATED COMPANIES")
    log.info("Best-known address is a mass-registration address. The borough on the")
    log.info("register is the agent's, not the business's. Excluded from all geography.")
    log.info("=" * 84)
    c_total = con.execute(
        "SELECT count(*) FROM company_tier WHERE tier='C_unlocated'"
    ).fetchone()[0]
    log.info("  companies: %s (%.1f%% of cohort)", f"{c_total:,}", 100 * c_total / total)

    log.info("")
    log.info("  Largest addresses holding unlocated cohort companies:")
    for key, n, at_key in con.execute("""
        SELECT t.best_key, count(*) AS n, any_value(t.companies_at_best)
        FROM company_tier t WHERE t.tier='C_unlocated' AND t.best_key<>''
        GROUP BY 1 ORDER BY 2 DESC LIMIT 8
    """).fetchall():
        log.info("    %5s cohort companies  (%s companies of all kinds)  %s",
                 f"{n:,}", f"{at_key:,}", key[:46])

    log.info("")
    log.info("  How Tier C differs from Tier A -- why it cannot simply be folded in:")
    for tier, n, dis, ins, never in con.execute("""
        SELECT t.tier, count(*),
               sum(CASE WHEN t.outcome='dead' THEN 1 ELSE 0 END),
               sum(CASE WHEN e.exit_family='insolvency' THEN 1 ELSE 0 END),
               sum(CASE WHEN f.n_accounts=0 THEN 1 ELSE 0 END)
        FROM company_tier t
        LEFT JOIN company_exit_v2 e USING (company_number)
        LEFT JOIN filing_footprint f USING (company_number)
        GROUP BY 1 ORDER BY 1
    """).fetchall():
        log.info("    %-24s n=%8s  dissolved %4.1f%%  insolvent %5.2f%%  never filed %s",
                 tier, f"{n:,}", 100*dis/n, 100*ins/n, f"{never:,}")

    db.append_flow(con, [
        ("21", "tier_a_premises_confirmed", a_total,
         "Matched to an FSA food establishment on a known address"),
        ("21", "tier_c_unlocated", c_total,
         "Best-known address is a mass-registration address; excluded from geography"),
        ("21", "relocated_from_current", moved,
         "Placed at a different address from today's registered office"),
    ])
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

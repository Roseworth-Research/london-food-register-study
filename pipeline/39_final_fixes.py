"""
Step 39 -- the two structural fixes external review identified, applied
together because the second changes numbers the first also touches.

FIX A: the premises table counted address keys, not establishments.
---------------------------------------------------------------------
Step 18 deliberately builds several candidate address keys per establishment,
because the two registers structure addresses differently and matching on one
line alone finds almost nothing. That is correct for MATCHING and wrong for
COUNTING: the table held 231,089 rows describing 70,470 establishments, and
anything that counted rows inflated by a factor of roughly three.

The fix separates the two jobs rather than abandoning either. One row per
establishment in `fsa_establishments`; the candidate keys move to
`fsa_address_keys`, which the matching joins through. No data is lost and no
match is weakened; only the counting changes. Rebuilt in place from the data
already held, so no re-fetch from the FSA is required.

FIX B: companies in live insolvency proceedings had no event date.
---------------------------------------------------------------------
A company that has entered liquidation but has not yet been dissolved carries
no cessation date on the register, and the pipeline was timing its exit at the
observation date -- months or years after the event actually occurred. 1,436
companies were affected, and unevenly: 1,146 service formats against 290
counter, which is precisely the comparison the study turns on. The event time
is now the date of the first insolvency-category filing, read from the cached
filing history, which is when the company demonstrably stopped being an
ordinary going concern.

Both fixes report before-and-after so the effect on published figures is
visible rather than silent.
"""

from __future__ import annotations

import json
import sys

import pandas as pd

import config
import db
from ch_api import setup_logging

log = setup_logging("39_final_fixes")

RAW = config.DATA_RAW / "life_history" / "filing-history"


def fix_a(con) -> None:
    log.info("=" * 78)
    log.info("FIX A -- one row per establishment")
    log.info("=" * 78)
    before = con.execute(
        "SELECT count(*), count(DISTINCT fhrsid) FROM fsa_establishments").fetchone()
    log.info("  before: %s rows describing %s establishments",
             f"{before[0]:,}", f"{before[1]:,}")

    cols = {r[0] for r in con.execute("DESCRIBE fsa_establishments").fetchall()}
    if "address_key" not in cols:
        # Already normalised by an earlier run. Re-running must not drop the
        # key table, because it cannot be rebuilt from the normalised table:
        # re-run 18_fsa_premises.py first if a rebuild is wanted.
        log.info("  fsa_establishments already one row per establishment; "
                 "keeping fsa_address_keys")
        return recompute_tiers(con)

    con.execute("DROP TABLE IF EXISTS fsa_address_keys")
    con.execute("""
        CREATE TABLE fsa_address_keys AS
        SELECT DISTINCT fhrsid, address_key
        FROM fsa_establishments
        WHERE address_key IS NOT NULL AND address_key <> ''
    """)
    con.execute("CREATE INDEX idx_fak_key ON fsa_address_keys(address_key)")
    con.execute("CREATE INDEX idx_fak_id ON fsa_address_keys(fhrsid)")

    con.execute("DROP TABLE IF EXISTS fsa_establishments_v2")
    con.execute("""
        CREATE TABLE fsa_establishments_v2 AS
        SELECT fhrsid,
               any_value(business_name) AS business_name,
               any_value(business_type) AS business_type,
               any_value(authority)     AS authority,
               any_value(addr1)         AS addr1,
               any_value(addr2)         AS addr2,
               any_value(postcode)      AS postcode
        FROM fsa_establishments GROUP BY fhrsid
    """)
    con.execute("DROP TABLE fsa_establishments")
    con.execute("ALTER TABLE fsa_establishments_v2 RENAME TO fsa_establishments")

    after = con.execute(
        "SELECT count(*) FROM fsa_establishments").fetchone()[0]
    keys = con.execute("SELECT count(*) FROM fsa_address_keys").fetchone()[0]
    log.info("  after:  %s establishments, %s candidate address keys held "
             "separately", f"{after:,}", f"{keys:,}")

    recompute_tiers(con)


def recompute_tiers(con) -> None:
    # Tier A, recomputed through the key table rather than the row table.
    tier_before = con.execute(
        "SELECT count(*) FROM company_tier WHERE tier='A_premises_confirmed'"
    ).fetchone()[0]
    con.execute("""
        CREATE OR REPLACE TABLE company_premises AS
        SELECT DISTINCT c.company_number, k.fhrsid
        FROM companies c
        JOIN fsa_address_keys k ON k.address_key = c.address_key
    """)
    matched = con.execute(
        "SELECT count(DISTINCT company_number) FROM company_premises").fetchone()[0]
    total = con.execute("SELECT count(*) FROM companies").fetchone()[0]
    log.info("")
    log.info("  companies matching a food establishment: %s of %s (%.1f%%)",
             f"{matched:,}", f"{total:,}", 100 * matched / total)
    log.info("  (Tier A previously reported as %s, inflated by the row count)",
             f"{tier_before:,}")
    con.execute("""
        UPDATE company_tier SET tier = CASE
            WHEN company_number IN (SELECT company_number FROM company_premises)
                THEN 'A_premises_confirmed' ELSE tier END
    """)
    est_matched = con.execute(
        "SELECT count(DISTINCT fhrsid) FROM company_premises").fetchone()[0]
    after = con.execute("SELECT count(*) FROM fsa_establishments").fetchone()[0]
    log.info("  distinct establishments matched to a company: %s of %s (%.1f%%)",
             f"{est_matched:,}", f"{after:,}", 100 * est_matched / after)


def first_insolvency_dates() -> dict:
    """Date of each company's earliest insolvency-category filing."""
    out = {}
    for group in RAW.iterdir():
        if not group.is_dir():
            continue
        for path in group.glob("*.json"):
            try:
                filings = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            best = None
            for f in filings:
                if (f.get("category") or "").lower() != "insolvency":
                    continue
                d = f.get("date") or ""
                if d and (best is None or d < best):
                    best = d
            if best:
                out[path.stem] = best
    return out


def fix_b(con) -> None:
    log.info("")
    log.info("=" * 78)
    log.info("FIX B -- event dates for companies in live proceedings")
    log.info("=" * 78)
    affected = con.execute("""
        SELECT format, count(*) FROM companies
        WHERE outcome='failing' AND died IS NULL GROUP BY 1 ORDER BY 1
    """).fetchall()
    log.info("  affected: %s", dict(affected))

    log.info("  reading first insolvency filing dates from cached histories...")
    dates = first_insolvency_dates()
    log.info("  companies with a dated insolvency filing: %s", f"{len(dates):,}")

    frame = pd.DataFrame(
        [(k, v) for k, v in dates.items()],
        columns=["company_number", "first_insolvency"])
    con.execute("DROP TABLE IF EXISTS first_insolvency")
    con.register("_fi", frame)
    con.execute("CREATE TABLE first_insolvency AS SELECT * FROM _fi")
    con.unregister("_fi")

    # Event date: cessation if dissolved; else the first insolvency filing for
    # companies in live proceedings; else censored at the observation date.
    con.execute(f"""
        ALTER TABLE companies ADD COLUMN IF NOT EXISTS event_date DATE
    """)
    con.execute(f"""
        UPDATE companies SET event_date = COALESCE(
            died,
            CASE WHEN outcome = 'failing' THEN (
                SELECT CAST(fi.first_insolvency AS DATE) FROM first_insolvency fi
                WHERE fi.company_number = companies.company_number
            ) END,
            DATE '{config.OBSERVATION_DATE}')
    """)
    fixed = con.execute("""
        SELECT count(*) FROM companies
        WHERE outcome='failing' AND died IS NULL
          AND event_date < DATE '2026-08-18'
    """).fetchone()[0]
    log.info("  event dates recovered for %s of the affected companies", f"{fixed:,}")

    before = con.execute("""
        SELECT round(avg(lifespan_days), 1) FROM companies
        WHERE outcome='failing' AND died IS NULL""").fetchone()[0]
    con.execute("""
        UPDATE companies
        SET lifespan_days = CAST(date_diff('day', born, event_date) AS INTEGER),
            lifespan_years = date_diff('day', born, event_date) / 365.25
        WHERE outcome='failing' AND died IS NULL AND event_date IS NOT NULL
          AND date_diff('day', born, event_date) >= 0
    """)
    after = con.execute("""
        SELECT round(avg(lifespan_days), 1) FROM companies
        WHERE outcome='failing' AND died IS NULL""").fetchone()[0]
    log.info("  mean recorded lifespan for those companies: %s days -> %s days",
             before, after)
    log.info("  (the reduction is the months of censoring that were previously "
             "credited to companies already in liquidation)")


def main() -> int:
    con = db.connect(wait_seconds=600)
    fix_a(con)
    fix_b(con)
    con.close()
    log.info("")
    log.info("Both fixes applied. Downstream steps must now be re-run: "
             "21, 16, 10, 26, 28, 29, 34, 11.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

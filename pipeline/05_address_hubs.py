"""
Step 5 -- map what sits at each address, and find the ones that are not shops.

Two jobs, one pass over the bulk snapshot.

Job one: who else is at this address
-------------------------------------
The succession question the report wants to answer is not only "did a
restaurant become a takeaway" but "what took its place" in general -- a nail
bar, a barber, a phone shop, an empty unit. Answering that needs the occupants
of a premises across ALL industries, not just the food SIC codes the cohort is
built from. So for every address where at least one cohort company sits, every
live company at that address is recorded with its SIC code and incorporation
date, into `address_occupants`.

One asymmetry has to be stated wherever this table is used: the bulk snapshot
holds live companies only. Food-sector successors are complete, living and
dead, because the cohort was pulled from the register in step 3. Non-food
successors are only visible if they are still trading today. A restaurant that
became a nail bar that then closed is invisible. The bias runs one way -- it
undercounts churn outside food -- and the report says so rather than implying
the non-food picture is as complete as the food one.

Job two: find the addresses that are not really shops.

The succession analysis in step 9 asks: when a restaurant died, what was
incorporated next at the same address? That question is meaningless at an
address that is a professional office.

Many small companies use their accountant's office as their registered office.
Accountancy practices, formation agents and virtual-office providers all
host registered offices for the companies they serve. Left
uncorrected, the succession analysis would report that a handful of
professional service addresses are the most volatile restaurant premises in
London -- hundreds of food businesses born and dying at one front door.

This step counts how many companies of ANY kind sit at each normalised address
in the London postcode areas, by rescanning the bulk snapshot. Counting only
cohort companies would badly undercount: an accountant's address might hold
400 companies of which only 12 are restaurants, and 12 looks like a genuine
parade of shops.

Thresholds
----------
An address is flagged as a hub at 10 or more companies. That is a judgement,
so both the threshold and the sensitivity of the headline findings to it are
reported: step 10 reruns the succession analysis at 5, 10 and 25 and publishes
all three. A real high-street unit occasionally holds several companies -- a
trading company, a property company, a dormant predecessor -- so a threshold
below about 5 would start discarding genuine premises.

Note that this measures LIVE companies only, since that is what the snapshot
contains. An address that was a formation agent five years ago and is a shop
today will be under-counted. Direction of the bias: towards keeping hubs in,
not towards discarding real premises.
"""

from __future__ import annotations

import csv
import sys
import time

import re

import addresses
import config
import db
from ch_api import setup_logging

log = setup_logging("05_address_hubs")

HUB_THRESHOLD = 10

_SIC_CODE = re.compile(r"^\s*(\d{4,5})")

CREATE_SQL = """
        CREATE TABLE address_hubs (
            address_key       VARCHAR PRIMARY KEY,
            postcode          VARCHAR,
            postcode_district VARCHAR,
            companies_at_key  INTEGER,  -- live companies of any SIC at this address
            companies_at_postcode INTEGER,
            is_hub            BOOLEAN,  -- at or above HUB_THRESHOLD
            example_name      VARCHAR   -- one occupant, to make the table readable
        )
"""

OCCUPANTS_SQL = """
        CREATE TABLE address_occupants (
            address_key    VARCHAR,
            company_number VARCHAR,
            company_name   VARCHAR,
            sic_primary    VARCHAR,   -- first SIC slot, any industry
            sic_text       VARCHAR,   -- the published description, for readability
            status_raw     VARCHAR,
            incorporated   VARCHAR,   -- dd/mm/yyyy as published
            in_cohort      BOOLEAN    -- carries one of the four study SIC codes
        )
"""


def main() -> int:
    if not config.SNAPSHOT_CSV.exists():
        log.error("Snapshot CSV not found: %s", config.SNAPSHOT_CSV)
        return 1

    con = db.connect()
    cohort_keys = {
        r[0]
        for r in con.execute(
            "SELECT DISTINCT address_key FROM companies_register WHERE address_key <> ''"
        ).fetchall()
    }
    con.close()
    log.info("Cohort occupies %s distinct addresses; recording every live "
             "occupant of those, in any industry", f"{len(cohort_keys):,}")

    by_key: dict[str, int] = {}
    by_postcode: dict[str, int] = {}
    example: dict[str, str] = {}
    key_postcode: dict[str, str] = {}
    occupants: list[tuple] = []

    t0 = time.monotonic()
    rows_read = 0
    with open(config.SNAPSHOT_CSV, encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        reader.fieldnames = [c.strip() for c in (reader.fieldnames or [])]
        for raw in reader:
            rows_read += 1
            if rows_read % 1_000_000 == 0:
                log.info("  %s rows, %s addresses, %s occupants (%.0fs)",
                         f"{rows_read:,}", f"{len(by_key):,}", f"{len(occupants):,}",
                         time.monotonic() - t0)

            postcode = addresses.normalise_postcode(raw.get("RegAddress.PostCode", ""))
            if not postcode:
                continue
            if addresses.postcode_area(postcode) not in config.LONDON_POSTCODE_AREAS:
                continue

            by_postcode[postcode] = by_postcode.get(postcode, 0) + 1
            key = addresses.address_key(
                raw.get("RegAddress.AddressLine1", ""),
                raw.get("RegAddress.AddressLine2", ""),
                postcode,
            )
            if not key:
                continue
            by_key[key] = by_key.get(key, 0) + 1
            if key not in example:
                example[key] = (raw.get("CompanyName") or "").strip()
                key_postcode[key] = postcode

            if key in cohort_keys:
                sic_text = (raw.get("SICCode.SicText_1") or "").strip()
                m = _SIC_CODE.match(sic_text)
                sic = m.group(1) if m else ""
                occupants.append(
                    (
                        key,
                        (raw.get("CompanyNumber") or "").strip(),
                        (raw.get("CompanyName") or "").strip(),
                        sic,
                        sic_text,
                        (raw.get("CompanyStatus") or "").strip(),
                        (raw.get("IncorporationDate") or "").strip(),
                        sic in config.SIC_COHORT,
                    )
                )

    log.info("Scan complete: %s rows, %s distinct London addresses, %s occupant records (%.0fs)",
             f"{rows_read:,}", f"{len(by_key):,}", f"{len(occupants):,}",
             time.monotonic() - t0)

    rows = [
        (
            key,
            key_postcode.get(key, ""),
            addresses.postcode_district(key_postcode.get(key, "")),
            n,
            by_postcode.get(key_postcode.get(key, ""), 0),
            n >= HUB_THRESHOLD,
            example.get(key, ""),
        )
        for key, n in by_key.items()
    ]

    con = db.connect()
    db.replace_table(
        con, "address_hubs", CREATE_SQL,
        ["address_key", "postcode", "postcode_district", "companies_at_key",
         "companies_at_postcode", "is_hub", "example_name"],
        rows,
    )
    db.replace_table(
        con, "address_occupants", OCCUPANTS_SQL,
        ["address_key", "company_number", "company_name", "sic_primary",
         "sic_text", "status_raw", "incorporated", "in_cohort"],
        occupants,
    )
    con.execute("CREATE INDEX idx_occ_key ON address_occupants(address_key)")

    hubs = con.execute("SELECT count(*) FROM address_hubs WHERE is_hub").fetchone()[0]
    log.info("Addresses flagged as hubs (>= %d companies): %s of %s (%.2f%%)",
             HUB_THRESHOLD, f"{hubs:,}", f"{len(rows):,}", 100 * hubs / max(len(rows), 1))

    log.info("--- largest registered-office hubs in the cohort's postcodes ---")
    biggest = con.execute(
        """
        SELECT h.companies_at_key, h.address_key, h.example_name
        FROM address_hubs h
        WHERE h.address_key IN (SELECT address_key FROM companies_register)
        ORDER BY h.companies_at_key DESC LIMIT 15
        """
    ).fetchall()
    for n, key, name in biggest:
        log.info("  %6s  %-52s %s", f"{n:,}", key[:52], name[:30])

    cohort_in_hubs = con.execute(
        """
        SELECT count(*) FROM companies_register r
        JOIN address_hubs h USING (address_key) WHERE h.is_hub
        """
    ).fetchone()[0]
    cohort_total = con.execute("SELECT count(*) FROM companies_register").fetchone()[0]
    log.info(
        "Cohort companies registered at a hub address: %s of %s (%.1f%%) -- "
        "excluded from succession analysis, retained everywhere else",
        f"{cohort_in_hubs:,}", f"{cohort_total:,}",
        100 * cohort_in_hubs / max(cohort_total, 1),
    )

    db.append_flow(
        con,
        [
            ("05", "london_addresses", len(rows),
             "Distinct normalised addresses in the London postcode areas (all SIC codes)"),
            ("05", "hub_addresses", hubs,
             f"Addresses with {HUB_THRESHOLD}+ live companies -- treated as service addresses"),
            ("05", "cohort_at_hubs", cohort_in_hubs,
             "Cohort companies at a hub address; excluded from premises-level succession only"),
        ],
    )
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

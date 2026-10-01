"""
Step 1 -- build the live cohort from the Companies House bulk snapshot.

Reads the free monthly "Basic Company Data" CSV (~5.5M rows, 2.79 GB) and
keeps companies that are both:

  * classified under one of the four study SIC codes, in ANY of their up to
    four SIC slots, and
  * registered at a postcode in a London or London-adjacent postcode area.

The postcode filter here is deliberately generous; step 3 replaces it with an
authoritative borough lookup and drops what falls outside Greater London.

Important limitation, verified rather than assumed
--------------------------------------------------
This snapshot contains LIVE companies only. A 400,000-row sample of the
2026-03-02 file contained zero populated DissolutionDate values and no
"Dissolved" status. Dissolved companies are deleted from the bulk product,
so a survival analysis built on this file alone would have no denominator and
would be pure survivorship bias. Step 2 recovers the dead from the REST API.

What the snapshot DOES contain, and what step 2 cannot give as cleanly, is the
set of companies that are still on the register but already failing:
liquidation, administration, receivership and proposal-to-strike-off. Those
are labelled here and carried through.

Output
------
Table `companies_live` in data/processed/brickedup.duckdb, plus a cohort flow
record in `cohort_flow` giving the count at each filter stage. The flow table
is what the report's cohort flow diagram is drawn from, and is the reason a
reviewer can check that the numbers add up.

Runtime: roughly four to eight minutes on a laptop; the cost is reading 2.79 GB.
"""

from __future__ import annotations

import csv
import re
import sys
import time

import addresses
import config
import db
from ch_api import setup_logging

log = setup_logging("01_cohort_live")

# The bulk CSV stores SIC as free text: "56103 - Take-away food shops and
# mobile food stands". Only the leading code is reliable.
_SIC_CODE = re.compile(r"^\s*(\d{4,5})")

SIC_COLUMNS = [f"SICCode.SicText_{i}" for i in (1, 2, 3, 4)]


def extract_sic_codes(row: dict) -> list[str]:
    """All five-digit SIC codes present on a company, in slot order."""
    codes = []
    for col in SIC_COLUMNS:
        m = _SIC_CODE.match(row.get(col) or "")
        if m:
            codes.append(m.group(1))
    return codes


def main() -> int:
    if not config.SNAPSHOT_CSV.exists():
        log.error("Snapshot CSV not found: %s", config.SNAPSHOT_CSV)
        log.error(
            "Download 'Basic Company Data as one file' from "
            "https://download.companieshouse.gov.uk/en_output.html and set "
            "CH_SNAPSHOT_CSV, or point it at an existing copy."
        )
        return 1

    log.info("Reading %s", config.SNAPSHOT_CSV)
    log.info("Snapshot date: %s", config.SNAPSHOT_DATE)
    log.info("SIC codes in cohort: %s", ", ".join(sorted(config.SIC_COHORT)))

    # Counters for the cohort flow diagram. Every company that leaves the
    # cohort leaves through exactly one of these gates.
    flow = {
        "rows_read": 0,
        "matched_sic": 0,
        "dropped_no_postcode": 0,
        "dropped_non_london_area": 0,
        "kept": 0,
    }
    by_sic: dict[str, int] = {}
    by_status: dict[str, int] = {}

    rows: list[tuple] = []
    t0 = time.monotonic()

    with open(config.SNAPSHOT_CSV, encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        # The published CSV has stray spaces in several header names.
        reader.fieldnames = [c.strip() for c in (reader.fieldnames or [])]

        for raw in reader:
            flow["rows_read"] += 1
            if flow["rows_read"] % 500_000 == 0:
                log.info(
                    "  %s rows read, %s in cohort (%.0fs)",
                    f"{flow['rows_read']:,}",
                    f"{flow['kept']:,}",
                    time.monotonic() - t0,
                )

            sic_codes = extract_sic_codes(raw)
            cohort_sics = [c for c in sic_codes if c in config.SIC_COHORT]
            if not cohort_sics:
                continue
            flow["matched_sic"] += 1

            postcode = addresses.normalise_postcode(raw.get("RegAddress.PostCode", ""))
            if not postcode:
                flow["dropped_no_postcode"] += 1
                continue

            area = addresses.postcode_area(postcode)
            if area not in config.LONDON_POSTCODE_AREAS:
                flow["dropped_non_london_area"] += 1
                continue

            # The primary SIC is the first cohort code found, in slot order.
            # Companies carrying both a service and a counter code are flagged
            # so the sensitivity analysis can drop them: they are genuinely
            # ambiguous and should not silently land in one bucket.
            primary_sic = cohort_sics[0]
            formats = {config.sic_format(c) for c in cohort_sics}
            is_mixed = len(formats) > 1

            addr1 = (raw.get("RegAddress.AddressLine1") or "").strip()
            addr2 = (raw.get("RegAddress.AddressLine2") or "").strip()
            care_of = (raw.get("RegAddress.CareOf") or "").strip()
            _street, inferred_agent = addresses.strip_care_of(addr1, addr2)

            status = (raw.get("CompanyStatus") or "").strip()
            by_sic[primary_sic] = by_sic.get(primary_sic, 0) + 1
            by_status[status] = by_status.get(status, 0) + 1

            rows.append(
                (
                    (raw.get("CompanyNumber") or "").strip(),
                    (raw.get("CompanyName") or "").strip(),
                    (raw.get("CompanyCategory") or "").strip(),
                    status,
                    config.status_group(status),
                    (raw.get("IncorporationDate") or "").strip(),
                    primary_sic,
                    config.sic_format(primary_sic),
                    is_mixed,
                    ";".join(sic_codes),
                    addr1,
                    addr2,
                    (raw.get("RegAddress.PostTown") or "").strip(),
                    postcode,
                    addresses.postcode_district(postcode),
                    area,
                    addresses.address_key(addr1, addr2, postcode),
                    care_of or inferred_agent or "",
                    (raw.get("Accounts.LastMadeUpDate") or "").strip(),
                    (raw.get("Accounts.AccountCategory") or "").strip(),
                    _to_int(raw.get("Mortgages.NumMortCharges")),
                    _to_int(raw.get("Mortgages.NumMortOutstanding")),
                    _to_int(raw.get("Mortgages.NumMortSatisfied")),
                    (raw.get("PreviousName_1.CompanyName") or "").strip(),
                )
            )
            flow["kept"] += 1

    elapsed = time.monotonic() - t0
    log.info(
        "Scan complete: %s rows in %.0fs (%.0f rows/s)",
        f"{flow['rows_read']:,}",
        elapsed,
        flow["rows_read"] / max(elapsed, 1),
    )

    _write(rows, flow, by_sic, by_status)
    return 0


def _to_int(v) -> int:
    try:
        return int(str(v).strip() or 0)
    except (TypeError, ValueError):
        return 0


COLUMNS = [
    "company_number", "company_name", "company_category", "status_raw",
    "status_group", "incorporation_date", "sic_primary", "format", "sic_mixed",
    "sic_all", "addr1", "addr2", "post_town", "postcode", "postcode_district",
    "postcode_area", "address_key", "care_of", "accounts_last_made_up",
    "accounts_category", "charges_total", "charges_outstanding",
    "charges_satisfied", "previous_name_1",
]

CREATE_SQL = """
        CREATE TABLE companies_live (
            company_number      VARCHAR PRIMARY KEY,
            company_name        VARCHAR,
            company_category    VARCHAR,
            status_raw          VARCHAR,   -- Companies House status string
            status_group        VARCHAR,   -- alive / failing / closing / dead
            incorporation_date  VARCHAR,   -- dd/mm/yyyy as published
            sic_primary         VARCHAR,   -- first cohort SIC in slot order
            format              VARCHAR,   -- counter / service
            sic_mixed           BOOLEAN,   -- carries both a counter and a service code
            sic_all             VARCHAR,   -- semicolon-separated, all slots
            addr1               VARCHAR,
            addr2               VARCHAR,
            post_town           VARCHAR,
            postcode            VARCHAR,
            postcode_district   VARCHAR,
            postcode_area       VARCHAR,
            address_key         VARCHAR,   -- normalised premises key
            care_of             VARCHAR,   -- agent name where registered care-of
            accounts_last_made_up VARCHAR,
            accounts_category   VARCHAR,
            charges_total       INTEGER,
            charges_outstanding INTEGER,
            charges_satisfied   INTEGER,
            previous_name_1     VARCHAR
        )
"""


def _write(rows, flow, by_sic, by_status) -> None:
    con = db.connect()
    db.replace_table(con, "companies_live", CREATE_SQL, COLUMNS, rows)

    # Dates in the bulk file are dd/mm/yyyy. Parse once, here, so that every
    # downstream script works with real dates and nobody re-implements it.
    con.execute("ALTER TABLE companies_live ADD COLUMN incorporated DATE")
    con.execute(
        "UPDATE companies_live SET incorporated = "
        "try_strptime(incorporation_date, '%d/%m/%Y')::DATE"
    )

    db.append_flow(
        con,
        [
            ("01", "rows_in_snapshot", flow["rows_read"],
             f"All UK companies in the {config.SNAPSHOT_DATE} bulk snapshot (live only)"),
            ("01", "matched_cohort_sic", flow["matched_sic"],
             "Carries 56101, 56102, 56103 or 47240 in any SIC slot"),
            ("01", "dropped_no_postcode", flow["dropped_no_postcode"],
             "Registered office postcode missing or malformed"),
            ("01", "dropped_non_london_area", flow["dropped_non_london_area"],
             "Postcode area outside the London and London-adjacent set"),
            ("01", "live_cohort", flow["kept"],
             "Live London food companies before borough verification (step 4)"),
        ],
    )

    log.info("--- cohort flow ---")
    for k, v in flow.items():
        log.info("  %-26s %s", k, f"{v:,}")
    log.info("--- by SIC ---")
    for sic, n in sorted(by_sic.items(), key=lambda kv: -kv[1]):
        log.info("  %-6s %-8s %7s  %s", sic, config.sic_format(sic), f"{n:,}",
                 config.SIC_COHORT[sic])
    log.info("--- by status ---")
    for st, n in sorted(by_status.items(), key=lambda kv: -kv[1]):
        log.info("  %-42s %7s  -> %s", st, f"{n:,}", config.status_group(st))

    con.close()
    log.info("Written to %s", config.DB_PATH)


if __name__ == "__main__":
    sys.exit(main())

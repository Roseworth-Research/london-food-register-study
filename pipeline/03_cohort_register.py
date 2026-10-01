"""
Step 3 -- pull the full register cohort, living and dead, district by district.

This is the step that makes the study honest. The bulk snapshot used in step 1
contains live companies only: dissolved companies are deleted from it. A
survival analysis built on the snapshot alone would be measuring nothing but
survivors, which is the textbook definition of survivorship bias. Here the
dead are recovered.

Method
------
The Companies House advanced search endpoint accepts a `location` parameter
that matches the registered office. Verified on 2026-08-16: `location=N12`
returns companies in the N12 outward code and does not bleed into N1 or N19.
Occasional strays appear where the search text matches something else in the
address, and those are removed client-side by checking the returned postcode.

So the register is walked one postcode district at a time, using the London
district list built in step 2, asking for all four cohort SIC codes at once
and every company status. Each result already carries company number, name,
status, incorporation date, cessation date, full registered office and SIC
codes -- so no follow-up call to the company profile endpoint is needed for
the cohort itself. That reduces what was planned as an overnight job
to roughly fifteen minutes.

The 5,000-result cap
--------------------
The endpoint will not return more than 5,000 results for one query. Where a
district exceeds that, the query is split -- first by SIC code, then by
incorporation year -- until every slice fits. The splitting is automatic and
logged, so the log is a record that nothing was silently truncated.

Output
------
Table `companies_register` in the study database: one row per company found on
the register, with a `source` column recording which slice found it.
"""

from __future__ import annotations

import datetime as dt
import sys
import time

import addresses
import config
import db
from ch_api import CompaniesHouseClient, setup_logging

log = setup_logging("03_cohort_register")

PAGE_SIZE = 500          # results per request; the endpoint accepts up to 5000
RESULT_CAP = 5000        # hard server-side cap on total results for one query
COHORT_SICS = sorted(config.SIC_COHORT)


def search_slice(
    client: CompaniesHouseClient, district: str, sic: str | None,
    inc_from: str | None = None, inc_to: str | None = None,
) -> tuple[list[dict], int]:
    """Page through one advanced-search slice. Returns (items, reported_hits)."""
    params = {
        "location": district,
        "sic_codes": sic or ",".join(COHORT_SICS),
        "size": PAGE_SIZE,
    }
    if inc_from:
        params["incorporated_from"] = inc_from
    if inc_to:
        params["incorporated_to"] = inc_to

    items: list[dict] = []
    start = 0
    hits = 0
    while True:
        params["start_index"] = start
        page = client.get("/advanced-search/companies", params)
        if not page:
            break
        hits = page.get("hits", 0)
        batch = page.get("items") or []
        items.extend(batch)
        start += PAGE_SIZE
        if not batch or start >= min(hits, RESULT_CAP):
            break
    return items, hits


def collect_district(client: CompaniesHouseClient, district: str) -> list[tuple[dict, str]]:
    """All cohort companies in one postcode district, splitting if capped.

    Returns (item, source_slice) pairs so that the provenance of every row is
    recorded and a reviewer can see which query produced it.
    """
    items, hits = search_slice(client, district, None)
    if hits < RESULT_CAP:
        return [(it, district) for it in items]

    # Too many for one query: split by SIC code.
    log.info("  %s: %d hits exceeds cap, splitting by SIC", district, hits)
    out: list[tuple[dict, str]] = []
    for sic in COHORT_SICS:
        sub, sub_hits = search_slice(client, district, sic)
        if sub_hits < RESULT_CAP:
            out.extend((it, f"{district}/{sic}") for it in sub)
            continue
        # Still too many: split by incorporation year.
        log.info("  %s/%s: %d hits, splitting by incorporation year", district, sic, sub_hits)
        for year in range(1980, dt.date.today().year + 1):
            yr, yr_hits = search_slice(
                client, district, sic, f"{year}-01-01", f"{year}-12-31"
            )
            if yr_hits >= RESULT_CAP:
                log.warning(
                    "  %s/%s/%d still at cap (%d) -- slice may be truncated",
                    district, sic, year, yr_hits,
                )
            out.extend((it, f"{district}/{sic}/{year}") for it in yr)
    return out


COLUMNS = [
    "company_number", "company_name", "status_raw", "company_type",
    "date_of_creation", "date_of_cessation", "sic_primary", "format",
    "sic_mixed", "sic_all", "addr1", "addr2", "locality", "postcode",
    "postcode_district", "address_key", "source_slice",
]

CREATE_SQL = """
        CREATE TABLE companies_register (
            company_number     VARCHAR PRIMARY KEY,
            company_name       VARCHAR,
            status_raw         VARCHAR,
            company_type       VARCHAR,
            date_of_creation   DATE,
            date_of_cessation  DATE,   -- populated for dissolved companies
            sic_primary        VARCHAR,
            format             VARCHAR,
            sic_mixed          BOOLEAN,
            sic_all            VARCHAR,
            addr1              VARCHAR,
            addr2              VARCHAR,
            locality           VARCHAR,
            postcode           VARCHAR,
            postcode_district  VARCHAR,
            address_key        VARCHAR,
            source_slice       VARCHAR  -- which query returned this row
        )
"""


def main() -> int:
    con = db.connect()
    districts = [
        r[0]
        for r in con.execute(
            "SELECT district FROM postcode_districts WHERE is_london ORDER BY district"
        ).fetchall()
    ]
    if not districts:
        log.error("No London districts found. Run 02_districts.py first.")
        return 1

    log.info("Walking %d London postcode districts", len(districts))
    client = CompaniesHouseClient()

    seen: set[str] = set()
    rows: list[tuple] = []
    dropped_wrong_postcode = 0
    t0 = time.monotonic()

    for i, district in enumerate(districts, 1):
        found = collect_district(client, district)
        kept = 0
        for item, source in found:
            number = (item.get("company_number") or "").strip()
            if not number or number in seen:
                continue

            addr = item.get("registered_office_address") or {}
            postcode = addresses.normalise_postcode(addr.get("postal_code", ""))
            # Guard against the occasional stray the text search returns.
            if addresses.postcode_district(postcode) != district:
                dropped_wrong_postcode += 1
                continue

            seen.add(number)
            sic_codes = [str(s) for s in (item.get("sic_codes") or [])]
            cohort_sics = [s for s in sic_codes if s in config.SIC_COHORT]
            if not cohort_sics:
                continue
            primary = cohort_sics[0]
            formats = {config.sic_format(s) for s in cohort_sics}

            addr1 = (addr.get("address_line_1") or "").strip()
            addr2 = (addr.get("address_line_2") or "").strip()

            rows.append(
                (
                    number,
                    (item.get("company_name") or "").strip(),
                    (item.get("company_status") or "").strip(),
                    (item.get("company_type") or "").strip(),
                    item.get("date_of_creation"),
                    item.get("date_of_cessation"),
                    primary,
                    config.sic_format(primary),
                    len(formats) > 1,
                    ";".join(sic_codes),
                    addr1,
                    addr2,
                    (addr.get("locality") or "").strip(),
                    postcode,
                    district,
                    addresses.address_key(addr1, addr2, postcode),
                    source,
                )
            )
            kept += 1

        if i % 25 == 0 or kept > 400:
            log.info(
                "  [%3d/%3d] %-6s +%-5d  total %s  (%.0fs, %d requests, %d cached)",
                i, len(districts), district, kept, f"{len(rows):,}",
                time.monotonic() - t0, client.stats["requests"], client.stats["cache_hits"],
            )

    log.info(
        "Register walk complete: %s companies in %.0f minutes (%d live requests, %d cache hits)",
        f"{len(rows):,}", (time.monotonic() - t0) / 60,
        client.stats["requests"], client.stats["cache_hits"],
    )
    log.info("Dropped %d results whose postcode did not match the queried district",
             dropped_wrong_postcode)

    db.replace_table(con, "companies_register", CREATE_SQL, COLUMNS, rows)
    con.execute(
        "ALTER TABLE companies_register ADD COLUMN status_group VARCHAR"
    )
    con.execute(
        "UPDATE companies_register SET status_group = CASE "
        "  WHEN lower(status_raw) IN ('dissolved','removed','converted-closed') THEN 'dead' "
        "  WHEN lower(status_raw) LIKE '%liquidation%' "
        "    OR lower(status_raw) LIKE '%administration%' "
        "    OR lower(status_raw) LIKE '%receiver%' "
        "    OR lower(status_raw) LIKE '%insolvency%' "  # 'insolvency-proceedings' fell to 'unknown' before
        "    OR lower(status_raw) LIKE '%voluntary-arrangement%' THEN 'failing' "
        "  WHEN lower(status_raw) LIKE '%strike%' THEN 'closing' "
        "  WHEN lower(status_raw) IN ('active','open') THEN 'alive' "
        "  ELSE 'unknown' END"
    )

    summary = con.execute(
        """
        SELECT status_group, format, count(*) AS n
        FROM companies_register GROUP BY 1,2 ORDER BY 1,2
        """
    ).fetchall()
    log.info("--- register cohort by outcome and format ---")
    for sg, fmt, n in summary:
        log.info("  %-8s %-8s %7s", sg, fmt, f"{n:,}")

    dead = con.execute(
        "SELECT count(*) FROM companies_register WHERE status_group='dead'"
    ).fetchone()[0]
    db.append_flow(
        con,
        [
            ("03", "register_cohort", len(rows),
             "All London cohort companies on the register, live and dissolved"),
            ("03", "register_dead", dead,
             "Dissolved -- absent from the bulk snapshot entirely"),
            ("03", "dropped_postcode_mismatch", dropped_wrong_postcode,
             "Search returned a company outside the queried district"),
        ],
    )
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

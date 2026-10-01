"""
Step 24 -- pull the control sectors from the REGISTER, not the snapshot.

Why this exists
---------------
Step 23 tried to run the control test using the bulk snapshot, and the test was
invalid. The snapshot holds live companies only. The food cohort holds live and
dissolved. Comparing the two measures different things, and the error is not
small: restricting food to live companies only changes its entry ordering
completely.

    Food, full population (live + dissolved), 2017-19 vs 2023-25:
        bakery +103%  >  cafe +72%  >  takeaway +65%  >  licensed +20%

    Food, live companies only -- the same basis the snapshot forces:
        takeaway +474%  >  cafe +349%  >  bakery +346%  >  licensed +245%

The live-only figures are survivorship-biased: a 2017 incorporation only
appears if it is still trading in 2026, while a 2024 one almost certainly is.
That inflates recent years and does so differently for each sector, according
to how well that sector survives. It is not a measure of entry at all.

So the control sectors have to come from the register itself, with their dead
included, exactly as the food cohort did in step 3. Same method, same 300
London postcode districts, same all-statuses query.

This is worth stating plainly in the report: **the control test could not be
run from free bulk data, and running it from bulk data would have produced a
confident answer that was wrong.**
"""

from __future__ import annotations

import sys
import time

import addresses
import config
import db
from ch_api import CompaniesHouseClient, setup_logging

log = setup_logging("24_control_register")

CONTROL_SICS = {
    "96020": ("Hairdressing and beauty", "very low"),
    "70229": ("Management consultancy", "minimal"),
    "47710": ("Retail of clothing", "moderate"),
    "93130": ("Fitness facilities", "high"),
    "56302": ("Public houses and bars", "high, licensed"),
}

PAGE_SIZE = 500
RESULT_CAP = 5000


def search_slice(client, district, sic, inc_from=None, inc_to=None):
    params = {"location": district, "sic_codes": sic, "size": PAGE_SIZE}
    if inc_from:
        params["incorporated_from"] = inc_from
        params["incorporated_to"] = inc_to
    items, start, hits = [], 0, 0
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


def main() -> int:
    con = db.connect()
    districts = [r[0] for r in con.execute(
        "SELECT district FROM postcode_districts WHERE is_london ORDER BY district"
    ).fetchall()]
    con.close()
    log.info("Walking %d London districts for %d control SIC codes",
             len(districts), len(CONTROL_SICS))

    client = CompaniesHouseClient()
    seen, rows = set(), []
    t0 = time.monotonic()

    for i, district in enumerate(districts, 1):
        for sic in CONTROL_SICS:
            items, hits = search_slice(client, district, sic)
            if hits >= RESULT_CAP:
                # Split by incorporation year, as in step 3.
                log.info("  %s/%s at cap (%d), splitting by year", district, sic, hits)
                items = []
                for year in range(1980, 2027):
                    yr, _ = search_slice(client, district, sic,
                                         f"{year}-01-01", f"{year}-12-31")
                    items.extend(yr)
            for it in items:
                num = (it.get("company_number") or "").strip()
                if not num or num in seen:
                    continue
                addr = it.get("registered_office_address") or {}
                pc = addresses.normalise_postcode(addr.get("postal_code", ""))
                if addresses.postcode_district(pc) != district:
                    continue
                codes = [str(s) for s in (it.get("sic_codes") or [])]
                hit = next((c for c in codes if c in CONTROL_SICS), None)
                if not hit:
                    continue
                seen.add(num)
                rows.append((num, (it.get("company_name") or "").strip(),
                             (it.get("company_status") or "").strip(), hit,
                             it.get("date_of_creation"), it.get("date_of_cessation"),
                             pc, district))
        if i % 30 == 0:
            log.info("  [%3d/%3d] %-6s  total %s  (%.0f min, %d requests)",
                     i, len(districts), district, f"{len(rows):,}",
                     (time.monotonic() - t0) / 60, client.stats["requests"])

    log.info("Control register walk complete: %s companies in %.1f minutes",
             f"{len(rows):,}", (time.monotonic() - t0) / 60)

    con = db.connect(wait_seconds=600)
    db.replace_table(
        con, "control_register",
        """
        CREATE TABLE control_register (
            company_number VARCHAR PRIMARY KEY, company_name VARCHAR,
            status_raw VARCHAR, sic VARCHAR, born DATE, died DATE,
            postcode VARCHAR, postcode_district VARCHAR
        )
        """,
        ["company_number", "company_name", "status_raw", "sic", "born", "died",
         "postcode", "postcode_district"],
        rows,
    )

    log.info("")
    log.info("=" * 92)
    log.info("CONTROL TEST, LIKE FOR LIKE: full populations, live and dissolved, both sides")
    log.info("=" * 92)

    def table(rows_):
        out = []
        for sic, (name, cap) in rows_[1].items():
            early = sum(c for s, y, c in rows_[0] if s == sic and y in (2017, 2018, 2019))
            late = sum(c for s, y, c in rows_[0] if s == sic and y in (2023, 2024, 2025))
            if early < 50:
                continue
            out.append((sic, name, cap, early / 3, late / 3, 100 * (late / early - 1)))
        return sorted(out, key=lambda r: -r[5])

    FOOD = {"47240": ("Bakery retail", "low"), "56103": ("Takeaway food shops", "low"),
            "56102": ("Unlicensed restaurants and cafes", "moderate"),
            "56101": ("Licensed restaurants", "high, licensed")}

    food = con.execute("""
        SELECT sic_primary, year(born), count(*) FROM companies
        WHERE year(born) BETWEEN 2017 AND 2025 GROUP BY 1,2
    """).fetchall()
    ctl = con.execute("""
        SELECT sic, year(born), count(*) FROM control_register
        WHERE year(born) BETWEEN 2017 AND 2025 GROUP BY 1,2
    """).fetchall()

    log.info("")
    log.info("  %-7s %-34s %-16s %8s %8s %8s", "sic", "sector", "capital",
             "2017-19", "2023-25", "growth")
    log.info("  FOOD -- zero-rating headroom varies")
    ft = table((food, FOOD))
    for r in ft:
        log.info("  %-7s %-34s %-16s %8.0f %8.0f %7.0f%%", *r[:3], r[3], r[4], r[5])
    log.info("  CONTROL -- uniform VAT treatment")
    ct = table((ctl, CONTROL_SICS))
    for r in ct:
        log.info("  %-7s %-34s %-16s %8.0f %8.0f %7.0f%%", *r[:3], r[3], r[4], r[5])

    log.info("")
    log.info("  Food ordering:    %s", " > ".join(r[0] for r in ft))
    log.info("  Control ordering: %s", " > ".join(r[0] for r in ct))
    log.info("")
    log.info("  Direct comparison -- same street, same capital, same licensing,")
    log.info("  and neither has meaningful zero-rating headroom:")
    for r in ft:
        if r[0] == "56101":
            log.info("    56101 licensed restaurants %+.0f%%", r[5])
    for r in ct:
        if r[0] == "56302":
            log.info("    56302 public houses/bars   %+.0f%%", r[5])
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

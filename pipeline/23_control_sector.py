"""
Step 23 -- the control sector: is the entry ordering about tax, or about capital?

The single largest gap in the study. The four food categories differ in
zero-rating headroom AND in capital intensity at the same time, and nothing in
the food data can separate them. A control does.

Design
------
Take London companies in sectors where **VAT treatment is uniform** -- every
one of these supplies is standard-rated, with no zero-rating boundary to
respond to -- but where **capital intensity varies just as widely** as it does
across the food categories.

  96020  Hairdressing and beauty          very low capital, standard-rated
  70229  Management consultancy           minimal capital, standard-rated
  47710  Retail of clothing               moderate capital, standard-rated
  93130  Fitness facilities               high capital, standard-rated
  56302  Public houses and bars           high capital, licensed, standard-rated

56302 is the important one. It is the sector the study deliberately excluded:
same trade, same high street, licensed and capital-hungry like a licensed
restaurant, and with essentially no zero-rating available. If pubs behave like
licensed restaurants, the licensed-restaurant result is about capital and
licensing. If they do not, that is harder to explain without something else.

What the two possible outcomes mean
-----------------------------------
**If the control sectors show the same shape** -- cheap-to-start categories
growing fastest, capital-hungry ones flat -- then the food ordering is capital
intensity wearing a tax costume, and the report must say so plainly.

**If they do not** -- if growth is unordered by capital where there is no tax
boundary -- then something specific to food is happening, and the tax boundary
becomes a more credible candidate. It still would not be proof.

The test is pre-specified here, in writing, before it is run. Both outcomes are
publishable and the report commits to reporting whichever occurs.
"""

from __future__ import annotations

import csv
import re
import sys
import time

import pandas as pd

import addresses
import config
import db
from ch_api import setup_logging

log = setup_logging("23_control_sector")

CONTROL_SICS = {
    "96020": ("Hairdressing and beauty", "very low"),
    "70229": ("Management consultancy", "minimal"),
    "47710": ("Retail of clothing", "moderate"),
    "93130": ("Fitness facilities", "high"),
    "56302": ("Public houses and bars", "high, licensed"),
}

FOOD_SICS = {
    "47240": ("Bakery retail", "low"),
    "56103": ("Takeaway food shops", "low"),
    "56102": ("Unlicensed restaurants and cafes", "moderate"),
    "56101": ("Licensed restaurants", "high, licensed"),
}

_SIC = re.compile(r"^\s*(\d{4,5})")
SIC_COLUMNS = [f"SICCode.SicText_{i}" for i in (1, 2, 3, 4)]


def scan_snapshot() -> pd.DataFrame:
    """One pass over the bulk file for the control SIC codes in London."""
    log.info("Scanning %s for control sectors", config.SNAPSHOT_CSV)
    rows = []
    t0 = time.monotonic()
    read = 0
    with open(config.SNAPSHOT_CSV, encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        reader.fieldnames = [c.strip() for c in (reader.fieldnames or [])]
        for raw in reader:
            read += 1
            if read % 1_000_000 == 0:
                log.info("  %s rows, %s kept (%.0fs)", f"{read:,}", f"{len(rows):,}",
                         time.monotonic() - t0)
            codes = []
            for col in SIC_COLUMNS:
                m = _SIC.match(raw.get(col) or "")
                if m:
                    codes.append(m.group(1))
            hit = next((c for c in codes if c in CONTROL_SICS), None)
            if not hit:
                continue
            postcode = addresses.normalise_postcode(raw.get("RegAddress.PostCode", ""))
            if not postcode or addresses.postcode_area(postcode) not in config.LONDON_POSTCODE_AREAS:
                continue
            rows.append({
                "company_number": (raw.get("CompanyNumber") or "").strip(),
                "sic": hit,
                "status": (raw.get("CompanyStatus") or "").strip(),
                "incorporated": (raw.get("IncorporationDate") or "").strip(),
                "postcode": postcode,
                "address_key": addresses.address_key(
                    raw.get("RegAddress.AddressLine1", ""),
                    raw.get("RegAddress.AddressLine2", ""), postcode),
            })
    log.info("Scan complete: %s rows read, %s control companies (%.0fs)",
             f"{read:,}", f"{len(rows):,}", time.monotonic() - t0)
    return pd.DataFrame(rows)


def main() -> int:
    con = db.connect(wait_seconds=600)
    exists = con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name='control_companies'"
    ).fetchone()[0]

    if not exists or "--refresh" in sys.argv:
        frame = scan_snapshot()
        con.execute("DROP TABLE IF EXISTS control_companies")
        con.register("_ctl", frame)
        con.execute("""
            CREATE TABLE control_companies AS
            SELECT *, try_strptime(incorporated, '%d/%m/%Y')::DATE AS born
            FROM _ctl
        """)
        con.unregister("_ctl")
    else:
        log.info("Using existing control_companies table")

    n = con.execute("SELECT count(*) FROM control_companies").fetchone()[0]
    log.info("Control cohort: %s London companies", f"{n:,}")

    # NOTE: the bulk snapshot holds LIVE companies only, so this control is a
    # comparison of INCORPORATION patterns only. That is exactly what the test
    # needs -- the food finding under scrutiny is an entry-composition finding.
    # It is not a survival comparison and must not be presented as one.
    log.info("")
    log.info("=" * 88)
    log.info("ENTRY GROWTH, THREE-YEAR ROLLING AVERAGES, 2017-19 vs 2023-25")
    log.info("Live companies only (the bulk snapshot holds no dissolved companies),")
    log.info("so this compares FORMATION patterns, not survival.")
    log.info("=" * 88)

    def growth_table(rows, label_map, source):
        out = []
        for sic, (name, capital) in label_map.items():
            early = late = 0
            for s, y, c in rows:
                if s != sic:
                    continue
                if y in (2017, 2018, 2019):
                    early += c
                elif y in (2023, 2024, 2025):
                    late += c
            if early < 50:
                continue
            out.append((sic, name, capital, early / 3, late / 3, 100 * (late / early - 1)))
        return sorted(out, key=lambda r: -r[5])

    ctl_rows = con.execute("""
        SELECT sic, year(born) AS y, count(*) FROM control_companies
        WHERE year(born) BETWEEN 2017 AND 2025 GROUP BY 1,2
    """).fetchall()
    food_rows = con.execute("""
        SELECT sic_primary, year(born) AS y, count(*) FROM companies
        WHERE year(born) BETWEEN 2017 AND 2025 GROUP BY 1,2
    """).fetchall()

    log.info("")
    log.info("  FOOD SECTOR  (varies in zero-rating headroom AND capital)")
    log.info("  %-7s %-34s %-16s %9s %9s %9s", "sic", "sector", "capital", "2017-19", "2023-25", "growth")
    for sic, name, cap, e, l, g in growth_table(food_rows, FOOD_SICS, "food"):
        log.info("  %-7s %-34s %-16s %9.0f %9.0f %8.0f%%", sic, name[:34], cap, e, l, g)

    log.info("")
    log.info("  CONTROL SECTORS  (uniform VAT treatment; capital varies)")
    log.info("  %-7s %-34s %-16s %9s %9s %9s", "sic", "sector", "capital", "2017-19", "2023-25", "growth")
    ctl = growth_table(ctl_rows, CONTROL_SICS, "control")
    for sic, name, cap, e, l, g in ctl:
        log.info("  %-7s %-34s %-16s %9.0f %9.0f %8.0f%%", sic, name[:34], cap, e, l, g)

    log.info("")
    log.info("=" * 88)
    log.info("READING THE RESULT")
    log.info("=" * 88)
    log.info("  Food ordering, fastest to slowest growth:")
    log.info("    %s", " > ".join(r[0] for r in growth_table(food_rows, FOOD_SICS, "f")))
    log.info("  Control ordering, fastest to slowest:")
    log.info("    %s", " > ".join(r[0] for r in ctl))
    log.info("")
    log.info("  If capital intensity orders the control sectors the same way it")
    log.info("  orders the food sectors, the food result is a capital story.")
    log.info("  If the control ordering is unrelated to capital, the food ordering")
    log.info("  needs a different explanation -- of which tax is one candidate.")

    high_cap = [r for r in ctl if "high" in r[2]]
    low_cap = [r for r in ctl if r[2] in ("very low", "minimal", "low")]
    if high_cap and low_cap:
        hi = sum(r[5] for r in high_cap) / len(high_cap)
        lo = sum(r[5] for r in low_cap) / len(low_cap)
        log.info("")
        log.info("  Control sectors, mean growth: low-capital %+.0f%%, high-capital %+.0f%%",
                 lo, hi)
        log.info("  Food sectors, mean growth:    low-capital %+.0f%%, high-capital %+.0f%%",
                 sum(r[5] for r in growth_table(food_rows, FOOD_SICS, "f")
                     if r[2] in ("low",)) / max(sum(1 for r in growth_table(food_rows, FOOD_SICS, "f")
                     if r[2] in ("low",)), 1),
                 sum(r[5] for r in growth_table(food_rows, FOOD_SICS, "f")
                     if "high" in r[2]) / max(sum(1 for r in growth_table(food_rows, FOOD_SICS, "f")
                     if "high" in r[2]), 1))

    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

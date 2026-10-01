"""
Step 4 -- resolve every cohort postcode to a London borough.

Step 2 established which postcode districts touch London. That is precise
enough to decide what to download, but not to say which borough a shop is in:
EC1A spans the City of London and Islington, and the study's local angle --
outer-London high streets gaining while the EC and WC lunch economies lost --
lives or dies on getting the borough right.

This step therefore resolves each distinct full postcode in the cohort to an
ONS local authority, and records how it was resolved.

Three resolution methods, in order of preference
------------------------------------------------
  1. `exact`      -- postcodes.io bulk lookup of live postcodes.
  2. `terminated` -- postcodes.io terminated-postcode lookup. Dissolved
                     companies frequently sit at postcodes that no longer
                     exist; without this they would silently drop out and the
                     dead would be under-counted, reintroducing the very
                     survivorship bias step 3 exists to remove.
  3. `district`   -- fall back to the district's borough from step 2, used
                     only where the district maps to exactly one borough.

Anything still unresolved is marked `unresolved` and excluded from
borough-level analysis, but stays in the London-wide totals. The counts by
method are published in the methodology appendix so a reader can see how much
of the geography is inferred rather than looked up.

Source: postcodes.io, serving the ONS Postcode Directory. Free, no key.
Responses cached under data/raw/postcodes.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

import duckdb

import config
from ch_api import setup_logging

log = setup_logging("04_boroughs")

CACHE_FILE = config.DATA_RAW / "postcode_lookup.json"
BULK_URL = "https://api.postcodes.io/postcodes"
TERMINATED_URL = "https://api.postcodes.io/terminated_postcodes/{}"
BATCH = 100  # postcodes.io bulk limit


def load_cache() -> dict:
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: dict) -> None:
    CACHE_FILE.write_text(json.dumps(cache), encoding="utf-8")


def bulk_lookup(postcodes: list[str]) -> dict:
    """Resolve up to 100 live postcodes in one POST."""
    body = json.dumps({"postcodes": postcodes}).encode()
    req = urllib.request.Request(
        BULK_URL, data=body, headers={"Content-Type": "application/json"}
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                payload = json.load(r)
            out = {}
            for entry in payload.get("result", []):
                query = entry.get("query")
                result = entry.get("result")
                if result:
                    out[query] = {
                        "borough": result.get("admin_district"),
                        "ward": result.get("admin_ward"),
                        "lsoa": result.get("lsoa"),
                        "lat": result.get("latitude"),
                        "lon": result.get("longitude"),
                        "method": "exact",
                    }
            return out
        except Exception as e:
            log.warning("bulk lookup retry %d: %s", attempt + 1, e)
            time.sleep(2 * (attempt + 1))
    return {}


def terminated_lookup(postcode: str) -> dict | None:
    """Resolve a postcode that has been withdrawn from the ONS directory."""
    url = TERMINATED_URL.format(urllib.parse.quote(postcode))
    try:
        with urllib.request.urlopen(url, timeout=25) as r:
            result = json.load(r).get("result")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        return None
    except Exception:
        return None
    if not result:
        return None
    return {
        "borough": None,          # terminated records carry no admin_district
        "ward": None,
        "lsoa": None,
        "lat": result.get("latitude"),
        "lon": result.get("longitude"),
        "method": "terminated",
    }


def main() -> int:
    import urllib.parse  # noqa: F401  (used by terminated_lookup)

    con = duckdb.connect(str(config.DB_PATH))

    postcodes = [
        r[0]
        for r in con.execute(
            """
            SELECT DISTINCT postcode FROM (
                SELECT postcode FROM companies_register
                UNION
                SELECT postcode FROM companies_live
            ) WHERE postcode IS NOT NULL AND postcode <> ''
            ORDER BY 1
            """
        ).fetchall()
    ]
    log.info("Distinct cohort postcodes to resolve: %s", f"{len(postcodes):,}")

    cache = load_cache()
    todo = [p for p in postcodes if p not in cache]
    log.info("Already cached: %s, to look up: %s", f"{len(cache):,}", f"{len(todo):,}")

    t0 = time.monotonic()
    for i in range(0, len(todo), BATCH):
        batch = todo[i: i + BATCH]
        found = bulk_lookup(batch)
        cache.update(found)
        # Anything the bulk endpoint did not return is either terminated or
        # invalid. Try the terminated endpoint before giving up on it.
        for pc in batch:
            if pc not in cache:
                term = terminated_lookup(pc)
                cache[pc] = term or {"method": "unresolved"}
        if (i // BATCH) % 20 == 0:
            save_cache(cache)
            log.info(
                "  %s/%s resolved (%.0fs)",
                f"{min(i + BATCH, len(todo)):,}", f"{len(todo):,}", time.monotonic() - t0,
            )
    save_cache(cache)

    # District-level fallback for anything still unknown, where the district
    # maps unambiguously to one borough.
    district_borough = {
        d: b
        for d, b in con.execute(
            """
            SELECT district, london_boroughs FROM postcode_districts
            WHERE is_london AND london_boroughs <> '' AND NOT contains(london_boroughs, ';')
            """
        ).fetchall()
    }

    rows = []
    method_counts: dict[str, int] = {}
    for pc in postcodes:
        entry = cache.get(pc) or {"method": "unresolved"}
        borough = entry.get("borough")
        method = entry.get("method", "unresolved")
        if not borough:
            district = pc.split(" ")[0]
            fallback = district_borough.get(district)
            if fallback:
                borough, method = fallback, "district"
        if not borough:
            method = "unresolved"
        method_counts[method] = method_counts.get(method, 0) + 1
        rows.append((pc, borough, entry.get("ward"), entry.get("lsoa"),
                     entry.get("lat"), entry.get("lon"), method))

    con.execute("DROP TABLE IF EXISTS postcode_borough")
    con.execute(
        """
        CREATE TABLE postcode_borough (
            postcode  VARCHAR PRIMARY KEY,
            borough   VARCHAR,
            ward      VARCHAR,
            lsoa      VARCHAR,
            latitude  DOUBLE,
            longitude DOUBLE,
            method    VARCHAR  -- exact / terminated / district / unresolved
        )
        """
    )
    con.executemany("INSERT INTO postcode_borough VALUES (?,?,?,?,?,?,?)", rows)

    log.info("--- resolution method ---")
    for m, n in sorted(method_counts.items(), key=lambda kv: -kv[1]):
        log.info("  %-12s %6s  (%.1f%%)", m, f"{n:,}", 100 * n / len(rows))

    in_london = con.execute(
        "SELECT count(*) FROM postcode_borough WHERE borough IS NOT NULL"
    ).fetchone()[0]
    con.execute(
        "INSERT INTO cohort_flow VALUES "
        "('04','postcodes_resolved',?, 'Distinct cohort postcodes with a local authority'),"
        "('04','postcodes_unresolved',?, 'No authority found; excluded from borough analysis only')",
        [in_london, len(rows) - in_london],
    )
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

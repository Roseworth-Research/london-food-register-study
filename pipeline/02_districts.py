"""
Step 2 -- establish the geographic spine: which postcode districts are London.

This script answers one question authoritatively, once, so that no later
script has to guess: for every postcode district (outward code) in a London or
London-adjacent postcode area, which local authority does it sit in, and is
that authority one of the 33 London boroughs?

Why districts rather than full postcodes
----------------------------------------
The Companies House advanced search accepts a `location` parameter which
matches the registered office. Testing on 2026-08-16 showed it matches an
outward code exactly -- `location=N12` returns N12 companies and does not
bleed into N1 or N19. That makes the postcode district the natural unit for
pulling the register: roughly 300 queries covers all of London, against
hundreds of thousands of individual postcodes.

A district can straddle two authorities (EC1A covers both the City of London
and Islington; WD25 covers four Hertfordshire authorities and no London
borough at all). Each district is therefore recorded with every authority it
touches, and flagged as London if ANY of them is a London borough. Companies
in straddling districts are assigned a borough at full-postcode resolution in
step 4, where it matters; the district flag exists only to decide what to
download.

Source
------
postcodes.io, which serves the ONS Postcode Directory. Free, no key, no
published rate limit. Responses are cached to data/raw/outcodes so a rerun
costs nothing and a reviewer gets the same mapping.

Runtime: two to four minutes on a first run, seconds thereafter.
"""

from __future__ import annotations

import json
import string
import sys
import time
import urllib.error
import urllib.request

import config
import db
from ch_api import setup_logging

log = setup_logging("02_districts")

CACHE = config.DATA_RAW / "outcodes"
CACHE.mkdir(parents=True, exist_ok=True)

POSTCODES_IO = "https://api.postcodes.io/outcodes/{}"

# The 33 London local authorities as ONS names them. A district is treated as
# London if it touches any of these.
LONDON_BOROUGHS = {
    "Barking and Dagenham", "Barnet", "Bexley", "Brent", "Bromley", "Camden",
    "City of London", "Croydon", "Ealing", "Enfield", "Greenwich", "Hackney",
    "Hammersmith and Fulham", "Haringey", "Harrow", "Havering", "Hillingdon",
    "Hounslow", "Islington", "Kensington and Chelsea", "Kingston upon Thames",
    "Lambeth", "Lewisham", "Merton", "Newham", "Redbridge",
    "Richmond upon Thames", "Southwark", "Sutton", "Tower Hamlets",
    "Waltham Forest", "Wandsworth", "Westminster",
}

# Central London areas use a letter suffix on low-numbered districts
# (EC1A, W1W, SW1Y, WC2H, N1C, E1W, SE1P). Everywhere else is numeric only.
LETTER_SUFFIX_AREAS = {"EC", "WC", "W", "SW", "N", "E", "SE"}


def candidate_districts() -> list[str]:
    """Every plausible outward code in the London postcode areas.

    Generated rather than hardcoded so the list cannot silently go stale, and
    so a reviewer can see exactly what search space was covered. Invalid
    candidates cost one cached 404 each and are discarded.
    """
    out: list[str] = []
    for area in sorted(config.LONDON_POSTCODE_AREAS):
        # From zero: CR0 (central Croydon) and HA0 (Wembley/Alperton) are real
        # districts. range(1, ...) silently omitted both and two major outer-
        # London high streets never entered the cohort (audit finding M1).
        # Every other AREA+0 candidate is invalid and costs one cached 404.
        for n in range(0, 31):
            out.append(f"{area}{n}")
            if area in LETTER_SUFFIX_AREAS and n <= 4:
                out.extend(f"{area}{n}{ch}" for ch in string.ascii_uppercase)
    return out


def lookup(outcode: str) -> dict | None:
    """Resolve one outward code, using the on-disk cache where possible."""
    cache_file = CACHE / f"{outcode}.json"
    if cache_file.exists():
        raw = json.loads(cache_file.read_text(encoding="utf-8"))
        return None if raw.get("__not_found__") else raw

    for attempt in range(4):
        try:
            with urllib.request.urlopen(POSTCODES_IO.format(outcode), timeout=25) as r:
                result = json.load(r).get("result")
            cache_file.write_text(json.dumps(result), encoding="utf-8")
            return result
        except urllib.error.HTTPError as e:
            if e.code == 404:
                cache_file.write_text(json.dumps({"__not_found__": True}), encoding="utf-8")
                return None
            time.sleep(2 * (attempt + 1))
        except Exception:
            time.sleep(2 * (attempt + 1))
    log.warning("Could not resolve outcode %s", outcode)
    return None


def main() -> int:
    candidates = candidate_districts()
    log.info("Testing %d candidate outward codes", len(candidates))

    rows: list[tuple] = []
    valid = london = 0
    for i, oc in enumerate(candidates, 1):
        if i % 200 == 0:
            log.info("  %d/%d tested, %d valid, %d in London", i, len(candidates), valid, london)
        result = lookup(oc)
        if not result:
            continue
        valid += 1
        authorities = result.get("admin_district") or []
        is_london = any(a in LONDON_BOROUGHS for a in authorities)
        if is_london:
            london += 1
        rows.append(
            (
                oc,
                oc[:2] if oc[1].isalpha() else oc[:1],
                is_london,
                ";".join(sorted(authorities)),
                ";".join(sorted(a for a in authorities if a in LONDON_BOROUGHS)),
                len(authorities) > 1,
                result.get("latitude"),
                result.get("longitude"),
            )
        )

    con = db.connect()
    db.replace_table(
        con,
        "postcode_districts",
        """
        CREATE TABLE postcode_districts (
            district          VARCHAR PRIMARY KEY,
            postcode_area     VARCHAR,
            is_london         BOOLEAN,  -- touches at least one London borough
            authorities       VARCHAR,  -- every local authority the district touches
            london_boroughs   VARCHAR,  -- of those, the London ones
            straddles         BOOLEAN,  -- touches more than one authority
            latitude          DOUBLE,
            longitude         DOUBLE
        )
        """,
        ["district", "postcode_area", "is_london", "authorities",
         "london_boroughs", "straddles", "latitude", "longitude"],
        rows,
    )

    db.append_flow(
        con,
        [
            ("02", "outcodes_tested", len(candidates),
             "Candidate outward codes generated from the London postcode areas"),
            ("02", "outcodes_valid", valid,
             "Resolved by postcodes.io (ONS Postcode Directory)"),
            ("02", "outcodes_london", london,
             "Touch at least one of the 33 London boroughs"),
        ],
    )

    log.info("Valid outward codes: %d, of which London: %d", valid, london)
    by_borough = con.execute(
        """
        SELECT trim(b.borough) AS borough, count(*) AS districts
        FROM postcode_districts, UNNEST(str_split(london_boroughs, ';')) AS b(borough)
        WHERE is_london AND trim(b.borough) <> ''
        GROUP BY 1 ORDER BY 2 DESC
        """
    ).fetchall()
    log.info("--- districts per borough ---")
    for borough, n in by_borough:
        log.info("  %-26s %2d", borough, n)

    straddlers = con.execute(
        "SELECT count(*) FROM postcode_districts WHERE is_london AND straddles"
    ).fetchone()[0]
    log.info(
        "%d London districts straddle more than one authority; these are resolved "
        "at full-postcode level in step 4.", straddlers
    )
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

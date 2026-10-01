"""
Step 7 -- pull the per-company life history: filing history and charges.

This is the only genuinely expensive step in the pipeline. Everything before it
runs in minutes; this one is rate-limited to 600 requests per five minutes by
Companies House, and there is one request per company per endpoint.

It is therefore scoped rather than run blind. The default target set is the
companies whose life history actually changes a published number:

  * every company that DIED inside the study window -- because "dissolved" on
    its own does not distinguish a failed restaurant from a retiring owner, and
    the report must not publish a closure count that conflates the two; and
  * every company that is currently failing or being struck off.

This study does not collect officer or person-with-significant-control data.
Linking individuals across companies is technically possible from the public
register and is deliberately out of scope: the research question is about
companies and premises, not about people, and building a person-level dataset
would be a disproportionate intrusion for the benefit it offers here.

What each endpoint contributes
------------------------------
filing-history  The exit route. A solvent voluntary strike-off (form DS01,
                gazette notices GAZ1/GAZ2) is an owner choosing to stop. A
                creditors' voluntary liquidation or a compulsory winding-up
                (LIQ and 600-series forms) is a failure. Also gives the filing
                cadence: late accounts are a distress signal that shows up
                before the death does.
charges         Secured borrowing: who lent, when, how much was outstanding,
                and whether it was ever satisfied. A restaurant fit-out is
                usually debt-financed; a counter is much less capital-hungry.
                Charge density by format is a direct measure of how much
                capital each model needs to start.
Note on what is NOT collected: officers and persons with significant control
are available from the same API and are not pulled. See above.

Resumability
------------
Every response is cached on disk by ch_api, and a `pull_progress` table records
which company/endpoint pairs are done. Killing this script and restarting it
costs nothing. Expect roughly one hour per 6,500 companies per endpoint.

Usage
-----
    python 07_life_history.py                      # default scope, all endpoints
    python 07_life_history.py --endpoints filing-history
    python 07_life_history.py --scope all --limit 5000
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import config
import db
from ch_api import CompaniesHouseClient, setup_logging

log = setup_logging("07_life_history")

ENDPOINTS = ("filing-history", "charges")

# This step no longer classifies anything. It used to carry its own exit-route
# rules, which prefix-matched "GAZ1" and so captured the voluntary "GAZ1(A)"
# notices too -- corrections-log item 2, audit finding M5 -- and its wrong
# labels were written back onto companies.exit_route on every run. The one
# classifier now lives in exit_rules.py and is applied over the cached
# histories by 16_competing_risks.py, which also owns the exit_route column.
# Step 7 is a puller: it fetches, caches, and records progress. Nothing else.


def target_companies(con, scope: str, limit: int | None) -> list[tuple[str, str]]:
    """Company numbers to pull, with the reason each was selected."""
    if scope == "all":
        sql = "SELECT company_number, 'all' FROM companies ORDER BY company_number"
    elif scope == "exits":
        sql = f"""
            SELECT company_number,
                   CASE WHEN outcome = 'dead' THEN 'died_in_window' ELSE outcome END
            FROM companies
            WHERE (died IS NOT NULL AND died >= DATE '{config.STUDY_START}')
               OR outcome IN ('failing', 'closing')
            ORDER BY died DESC NULLS LAST, company_number
        """
    elif scope == "live":
        # The survivors: everything the exits scope does not cover. Their
        # histories complete the denominators (filing footprint, address
        # history, charges) that were previously observed for dead companies
        # only -- comparing exits' histories against survivors' proxies was a
        # structural asymmetry in the study.
        sql = f"""
            SELECT company_number, 'live'
            FROM companies
            WHERE NOT ((died IS NOT NULL AND died >= DATE '{config.STUDY_START}')
                       OR outcome IN ('failing', 'closing'))
              AND died IS NULL
            ORDER BY company_number
        """
    elif scope == "charged":
        sql = """
            SELECT company_number, 'has_charges' FROM companies
            WHERE charges_total > 0 ORDER BY company_number
        """
    else:
        raise SystemExit(f"Unknown scope: {scope}")
    if limit:
        sql += f" LIMIT {limit}"
    return con.execute(sql).fetchall()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", default="exits",
                        choices=("exits", "live", "charged", "all"))
    parser.add_argument("--endpoints", nargs="+", default=list(ENDPOINTS), choices=ENDPOINTS)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    con = db.connect()
    targets = target_companies(con, args.scope, args.limit)
    log.info("Scope '%s': %s companies x %d endpoints = %s requests at best",
             args.scope, f"{len(targets):,}", len(args.endpoints),
             f"{len(targets) * len(args.endpoints):,}")
    log.info("At %.1f requests/second that is about %.1f hours if nothing is cached",
             config.CH_RATE_LIMIT_PER_SECOND,
             len(targets) * len(args.endpoints) / config.CH_RATE_LIMIT_PER_SECOND / 3600)

    con.execute(
        """
        CREATE TABLE IF NOT EXISTS pull_progress (
            company_number VARCHAR, endpoint VARCHAR, n_items INTEGER,
            PRIMARY KEY (company_number, endpoint)
        )
        """
    )
    done = {
        (c, e)
        for c, e in con.execute(
            "SELECT company_number, endpoint FROM pull_progress"
        ).fetchall()
    }
    log.info("Already pulled: %s company/endpoint pairs", f"{len(done):,}")
    con.close()

    client = CompaniesHouseClient()
    raw_dir = config.DATA_RAW / "life_history"
    raw_dir.mkdir(parents=True, exist_ok=True)

    progress_rows: list[tuple] = []
    t0 = time.monotonic()
    pulled = 0

    failures: list[tuple[str, str, str]] = []

    for i, (number, reason) in enumerate(targets, 1):
        for endpoint in args.endpoints:
            if (number, endpoint) in done:
                continue
            # One unreachable company must never end a run over 60,000 of
            # them. A previous run died at 12,500 because a single exhausted
            # retry chain raised. Record the failure, carry on, and report the
            # total at the end so the coverage gap is visible rather than
            # silent.
            try:
                items = client.get_all_items(f"/company/{number}/{endpoint}")
            except Exception as e:
                failures.append((number, endpoint, f"{type(e).__name__}: {e}"))
                log.warning("  skipping %s/%s after repeated failure: %s",
                            number, endpoint, type(e).__name__)
                continue
            out = raw_dir / endpoint / number[:2]
            out.mkdir(parents=True, exist_ok=True)
            (out / f"{number}.json").write_text(json.dumps(items), encoding="utf-8")
            progress_rows.append((number, endpoint, len(items)))
            pulled += 1

        if i % 250 == 0:
            rate = pulled / max(time.monotonic() - t0, 1)
            remaining = (len(targets) - i) * len(args.endpoints)
            log.info(
                "  [%s/%s] %s pulls done, %.1f/s, ~%.1f hours left "
                "(%d live requests, %d cache hits)",
                f"{i:,}", f"{len(targets):,}", f"{pulled:,}", rate,
                remaining / max(rate, 0.01) / 3600,
                client.stats["requests"], client.stats["cache_hits"],
            )
            _flush(progress_rows)
            progress_rows = []

    _flush(progress_rows)
    log.info("Complete: %s pulls in %.1f hours (%d live requests, %d cache hits, %d 404s)",
             f"{pulled:,}", (time.monotonic() - t0) / 3600,
             client.stats["requests"], client.stats["cache_hits"], client.stats["not_found"])
    if failures:
        log.warning("%d company/endpoint pulls could not be completed. Re-running "
                    "this script picks them up; everything already fetched is "
                    "cached and costs nothing.", len(failures))
        (config.OUT / "07_failures.txt").write_text(
            "\n".join(f"{n}\t{e}\t{msg}" for n, e, msg in failures), encoding="utf-8"
        )

    _summarise()
    return 0


def _flush(progress_rows: list[tuple]) -> None:
    """Write accumulated progress. Called periodically so a kill loses little."""
    if not progress_rows:
        return
    import pandas as pd

    con = db.connect()
    con.register("_p", pd.DataFrame(progress_rows,
                                    columns=["company_number", "endpoint", "n_items"]))
    con.execute(
        "INSERT INTO pull_progress SELECT * FROM _p "
        "ON CONFLICT (company_number, endpoint) DO NOTHING"
    )
    con.unregister("_p")
    con.close()


def _summarise() -> None:
    """Report the classification as it stands. Classification itself is owned
    by 16_competing_risks.py over the cached histories; run it after a pull
    that added filing histories."""
    con = db.connect()

    log.info("--- how companies left the register, by format ---")
    rows = con.execute(
        """
        SELECT c.format, c.exit_route, count(*) AS n
        FROM companies c
        WHERE c.exit_route IS NOT NULL AND c.outcome = 'dead'
        GROUP BY 1,2 ORDER BY 1, 3 DESC
        """
    ).fetchall()
    for fmt, route, n in rows:
        log.info("  %-8s %-32s %7s", fmt, route, f"{n:,}")

    log.info("--- insolvent versus solvent exits, by format and era of death ---")
    rows = con.execute(
        """
        SELECT c.format, c.death_era,
               sum(CASE WHEN c.exit_route LIKE '%liquidation%'
                         OR c.exit_route IN ('administration','insolvency_other')
                        THEN 1 ELSE 0 END) AS insolvent,
               sum(CASE WHEN c.exit_route LIKE '%strike_off%' THEN 1 ELSE 0 END) AS struck_off,
               sum(CASE WHEN c.exit_route = 'unknown' THEN 1 ELSE 0 END) AS unknown,
               count(*) AS total
        FROM companies c
        WHERE c.outcome = 'dead' AND c.exit_route IS NOT NULL AND c.death_era IS NOT NULL
        GROUP BY 1,2 ORDER BY 1,2
        """
    ).fetchall()
    for fmt, era, insolvent, struck, unknown, total in rows:
        log.info("  %-8s %-15s insolvent %5s (%4.1f%%)  struck off %5s  unknown %5s  n=%s",
                 fmt, era, f"{insolvent:,}", 100 * insolvent / max(total, 1),
                 f"{struck:,}", f"{unknown:,}", f"{total:,}")
    con.close()


if __name__ == "__main__":
    sys.exit(main())

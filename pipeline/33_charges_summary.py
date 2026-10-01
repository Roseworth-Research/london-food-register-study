"""
Step 33 -- parse the cached charges endpoint for every cohort company.

The pull cached /charges for all 119,220 companies. The snapshot's
charges_total column covered live companies only and is stale; this builds
the real table from the cached responses: per company, charges created,
outstanding, satisfied, and first/last charge dates.

Feeds the secured-borrowing paragraph of the lifecycle chapter: proportion
of companies that EVER granted a charge, by format and era -- proportions
only, never amounts (the withdrawn "2.7x the secured debt" mistake is not
coming back).

Output: table charges_summary in DuckDB + out/charges_by_format.csv
"""

from __future__ import annotations

import json
import sys
import time

import pandas as pd

import config
import db
from ch_api import setup_logging

log = setup_logging("33_charges_summary")

RAW = config.DATA_RAW / "life_history" / "charges"


def main() -> int:
    rows = []
    t0 = time.monotonic()
    n = 0
    for group in sorted(RAW.iterdir()):
        if not group.is_dir():
            continue
        for path in group.glob("*.json"):
            n += 1
            if n % 20000 == 0:
                log.info("  %s files (%.0fs)", f"{n:,}", time.monotonic() - t0)
            try:
                items = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not items:
                continue
            created = [i.get("created_on") or "" for i in items]
            statuses = [(i.get("status") or "").lower() for i in items]
            rows.append((
                path.stem,
                len(items),
                sum(1 for s in statuses if s == "outstanding"),
                sum(1 for s in statuses if "satisfied" in s),
                min((c for c in created if c), default=None),
                max((c for c in created if c), default=None),
            ))

    frame = pd.DataFrame(rows, columns=[
        "company_number", "charges", "outstanding", "satisfied",
        "first_charge", "last_charge",
    ])
    log.info("Companies with at least one charge: %s (of %s histories read)",
             f"{len(frame):,}", f"{n:,}")

    con = db.connect(wait_seconds=600)
    con.execute("DROP TABLE IF EXISTS charges_summary")
    con.register("_ch", frame)
    con.execute("CREATE TABLE charges_summary AS SELECT * FROM _ch")
    con.unregister("_ch")

    summary = con.execute(
        """
        SELECT c.format, c.birth_era,
               count(*) AS companies,
               count(ch.company_number) AS with_charge,
               round(100.0 * count(ch.company_number) / count(*), 2) AS pct_with_charge,
               round(100.0 * sum(CASE WHEN ch.outstanding > 0 THEN 1 ELSE 0 END)
                     / count(*), 2) AS pct_outstanding
        FROM companies c
        LEFT JOIN charges_summary ch USING (company_number)
        WHERE c.birth_era IS NOT NULL AND c.format IN ('counter','service')
        GROUP BY 1, 2 ORDER BY 2, 1
        """
    ).df()
    summary.to_csv(config.OUT / "charges_by_format.csv", index=False)
    log.info("")
    log.info("--- proportion of companies that ever granted a charge ---")
    for r in summary.itertuples():
        log.info("  %-9s %-15s n=%7s  with charge %5.2f%%  outstanding %5.2f%%",
                 r.format, r.birth_era, f"{r.companies:,}",
                 r.pct_with_charge, r.pct_outstanding)
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

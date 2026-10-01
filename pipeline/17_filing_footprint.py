"""
Step 17 -- did the company ever look like a trading business?

The single most useful question the register can answer, and the one this
study had not asked. It comes out of external review, and it reframes
everything.

The problem with every "closure" figure, including ours
-------------------------------------------------------
A company that is incorporated and struck off two years later without ever
filing a set of accounts is not a restaurant that closed. It may be a plan that
was abandoned, a vehicle that was never used, a name reserved and forgotten, or
a business that traded briefly and unlawfully failed to file. What it is not is
evidence that a kitchen opened and then shut.

Company-register analyses -- ours included until now -- count that company
alongside a fifteen-year-old restaurant that went into administration owing
money to forty suppliers. Treating them as the same event is the central
measurement error in this whole field, and it is one we can actually correct,
because we hold the complete filing history of all 60,265 exits.

What this step computes
-----------------------
For every company that left the register, from its own filing history:

  * how many sets of accounts it ever filed
  * whether any were dormant
  * whether it ever filed a confirmation statement (a weaker signal of life)
  * how long it lasted, and how it left

From which: **the proportion of exits that never filed accounts at all**, by
format -- and, more importantly, the insolvency rate *conditional on having
filed accounts*, which is the closest this dataset comes to asking "among
companies that appear to have actually traded, how often does the business
fail?"

That conditional figure is the one worth publishing. The unconditional one
mixes abandoned paperwork with real business failure.

The result is cached to Parquet, because reading 60,265 small JSON files takes
about fifteen minutes and nothing downstream should ever pay that cost twice.
"""

from __future__ import annotations

import json
import pathlib
import sys
import time

import pandas as pd

import config
from ch_api import setup_logging

log = setup_logging("17_filing_footprint")

RAW = config.DATA_RAW / "life_history" / "filing-history"
CACHE = config.DATA_PROCESSED / "filing_footprint.parquet"


def extract() -> pd.DataFrame:
    rows = []
    t0 = time.monotonic()
    files = 0
    for group in sorted(RAW.iterdir()):
        if not group.is_dir():
            continue
        for path in group.glob("*.json"):
            files += 1
            if files % 10_000 == 0:
                log.info("  %s files read (%.0fs)", f"{files:,}", time.monotonic() - t0)
            try:
                items = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue

            n_accounts = n_confirmation = 0
            dormant = False
            first_accounts = None
            for f in items:
                ftype = (f.get("type") or "").upper()
                category = (f.get("category") or "").lower()
                description = (f.get("description") or "").lower()
                if category == "accounts" or ftype.startswith("AA"):
                    n_accounts += 1
                    date = f.get("date")
                    if date and (first_accounts is None or date < first_accounts):
                        first_accounts = date
                    if "dormant" in description or "DORM" in ftype:
                        dormant = True
                if category == "confirmation-statement" or ftype.startswith(("CS", "AR")):
                    n_confirmation += 1

            rows.append({
                "company_number": path.stem,
                "n_accounts": n_accounts,
                "n_confirmation": n_confirmation,
                "ever_dormant": dormant,
                "first_accounts_date": first_accounts,
                "n_filings": len(items),
            })

    log.info("Read %s filing histories in %.1f minutes",
             f"{files:,}", (time.monotonic() - t0) / 60)
    return pd.DataFrame(rows)


def main() -> int:
    if CACHE.exists() and "--refresh" not in sys.argv:
        log.info("Using cached %s", CACHE)
        frame = pd.read_parquet(CACHE)
    else:
        if not RAW.exists():
            log.error("No cached filing histories at %s", RAW)
            return 1
        frame = extract()
        frame.to_parquet(CACHE, index=False)
        log.info("Cached to %s", CACHE)

    import db
    con = db.connect(wait_seconds=300)
    con.execute("DROP TABLE IF EXISTS filing_footprint")
    con.register("_ff", frame)
    con.execute("CREATE TABLE filing_footprint AS SELECT * FROM _ff")
    con.unregister("_ff")

    log.info("")
    log.info("=" * 88)
    log.info("WHAT KIND OF CORPORATE LIFE PRECEDED THE EXIT")
    log.info("=" * 88)
    log.info("%-9s %9s %16s %14s %14s %13s", "format", "exits",
             "never filed", "filed once", "filed 2+", "ever dormant")
    for fmt, n, never, once, more, dorm in con.execute(
        """
        SELECT c.format, count(*),
               sum(CASE WHEN f.n_accounts = 0 THEN 1 ELSE 0 END),
               sum(CASE WHEN f.n_accounts = 1 THEN 1 ELSE 0 END),
               sum(CASE WHEN f.n_accounts >= 2 THEN 1 ELSE 0 END),
               sum(CASE WHEN f.ever_dormant THEN 1 ELSE 0 END)
        FROM companies c JOIN filing_footprint f USING (company_number)
        GROUP BY 1 ORDER BY 1
        """
    ).fetchall():
        log.info("%-9s %9s %10s (%2.0f%%) %8s (%2.0f%%) %8s (%2.0f%%) %7s (%2.0f%%)",
                 fmt, f"{n:,}", f"{never:,}", 100 * never / n, f"{once:,}",
                 100 * once / n, f"{more:,}", 100 * more / n, f"{dorm:,}",
                 100 * dorm / n)

    log.info("")
    log.info("--- by SIC ---")
    for sic, n, never in con.execute(
        """
        SELECT c.sic_primary, count(*),
               sum(CASE WHEN f.n_accounts = 0 THEN 1 ELSE 0 END)
        FROM companies c JOIN filing_footprint f USING (company_number)
        GROUP BY 1 ORDER BY 1
        """
    ).fetchall():
        log.info("  %-7s exits %8s   never filed accounts %8s  (%.0f%%)",
                 sic, f"{n:,}", f"{never:,}", 100 * never / n)

    log.info("")
    log.info("=" * 88)
    log.info("INSOLVENCY, CONDITIONAL ON HAVING FILED ACCOUNTS")
    log.info("The number worth publishing: among companies that left an actual")
    log.info("filing footprint, how often did the ending involve creditors?")
    log.info("=" * 88)
    for grp, fmt, n, ins in con.execute(
        """
        SELECT CASE WHEN f.n_accounts = 0 THEN 'never filed accounts'
                    ELSE 'filed accounts at least once' END AS grp,
               c.format, count(*),
               sum(CASE WHEN e.exit_family = 'insolvency' THEN 1 ELSE 0 END)
        FROM companies c
        JOIN filing_footprint f USING (company_number)
        LEFT JOIN company_exit_v2 e USING (company_number)
        GROUP BY 1,2 ORDER BY 1,2
        """
    ).fetchall():
        log.info("  %-30s %-9s n=%8s   insolvent %6s  (%5.2f%%)",
                 grp, fmt, f"{n:,}", f"{ins:,}", 100 * ins / max(n, 1))

    log.info("")
    log.info("--- conditional insolvency by SIC, filers only ---")
    for sic, n, ins in con.execute(
        """
        SELECT c.sic_primary, count(*),
               sum(CASE WHEN e.exit_family = 'insolvency' THEN 1 ELSE 0 END)
        FROM companies c
        JOIN filing_footprint f USING (company_number)
        LEFT JOIN company_exit_v2 e USING (company_number)
        WHERE f.n_accounts > 0
        GROUP BY 1 ORDER BY 1
        """
    ).fetchall():
        log.info("  %-7s filers %8s   insolvent %6s  (%5.2f%%)",
                 sic, f"{n:,}", f"{ins:,}", 100 * ins / max(n, 1))

    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

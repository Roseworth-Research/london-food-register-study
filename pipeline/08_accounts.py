"""
Step 8 -- balance sheets, from the free bulk accounts archives.

Companies House publishes every electronically filed set of accounts as an
iXBRL document, bundled into one ZIP archive per month. The archives covering
this study -- January 2018 to date -- come to roughly 200 GB, which is not a
laptop-scale download.

They do not have to be downloaded. A ZIP file's index lives at the end of the
archive and every member records its own byte offset, so with HTTP range
requests the archive can be read as if it were a local file and only the
wanted members fetched. Reading the index of a 1.5 GB archive costs about
22 MB; each set of accounts then costs about 7 KB. Across the whole study that
turns 200 GB into a few gigabytes. See remote_zip.py for the mechanism.

Member filenames encode the company number and the balance sheet date --
`Prod224_0050_00000452_20170430.html` -- so the cohort filter is applied to
the index before a single set of accounts is fetched.

Output
------
One Parquet file per month under data/processed/accounts/, then a single load
into the study database as `accounts`. Writing Parquet first rather than
straight to DuckDB means this script can run alongside the per-company API
pull without the two fighting over the database file, and means an interrupted
run resumes at the next unfinished month.

Usage
-----
    python 08_accounts.py                     # fetch every month not yet done
    python 08_accounts.py --from 2018-01 --to 2019-12
    python 08_accounts.py --load              # load the Parquet files into DuckDB

Coverage caveat, to be published
--------------------------------
Paper filings are scanned PDFs with no tagging and never appear in these
archives. Small companies overwhelmingly file electronically, but the gap is
real; the load step reports what share of the cohort has at least one parsed
set of accounts, and that number goes in the methodology appendix.
"""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
import io
import sys
import time

import pandas as pd

import config
import db
import ixbrl
from ch_api import setup_logging
from remote_zip import fetch_members, open_remote_zip

log = setup_logging("08_accounts")

ARCHIVE_URL = "https://download.companieshouse.gov.uk/Accounts_Monthly_Data-{month}{year}.zip"
OUT_DIR = config.DATA_PROCESSED / "accounts"
OUT_DIR.mkdir(parents=True, exist_ok=True)

FIELDS = [
    "net_assets", "equity", "creditors_within_one_year", "creditors_after_one_year",
    "cash", "fixed_assets", "current_assets", "employees", "turnover",
]


def months(start: dt.date, end: dt.date):
    """Yield (year, month name) for every month in the range, inclusive."""
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, calendar.month_name[m]
        m += 1
        if m > 12:
            m, y = 1, y + 1


def cohort_numbers() -> set[str]:
    """Company numbers in the study, zero-padded as they appear in filenames."""
    con = db.connect(read_only=True)
    numbers = {
        r[0].strip().upper()
        for r in con.execute("SELECT company_number FROM companies").fetchall()
    }
    con.close()
    return numbers


def process_month(year: int, month: str, cohort: set[str]) -> int:
    """Fetch and parse every cohort filing in one monthly archive."""
    out_file = OUT_DIR / f"{year}-{month}.parquet"
    if out_file.exists():
        log.info("%s %s already done, skipping", month, year)
        return 0

    url = ARCHIVE_URL.format(month=month, year=year)
    t0 = time.monotonic()
    try:
        zf, backing = open_remote_zip(url)
    except Exception as e:
        log.warning("%s %s unavailable (%s) -- skipping", month, year, e)
        return 0

    infos = zf.infolist()
    index_cost = backing.bytes_fetched
    wanted = [
        info for info in infos
        if (num := ixbrl.company_from_filename(info.filename)) and num in cohort
    ]
    log.info("%s %s: %s filings in archive, %s belong to the cohort (index cost %.0f MB)",
             month, year, f"{len(infos):,}", f"{len(wanted):,}", index_cost / 1e6)

    rows: list[dict] = []
    failed = 0
    seen = 0
    for i, (info, content) in enumerate(fetch_members(url, wanted, backing), 1):
        seen += 1
        name = info.filename
        number = ixbrl.company_from_filename(name) or ""
        parsed = ixbrl.parse(content, number, name)
        if not parsed:
            failed += 1
            continue

        made_up = ixbrl.date_from_filename(name) or parsed.get("balance_sheet_date")
        row = {
            "company_number": number,
            "made_up_to": made_up,
            "financial_year": int(made_up[:4]) if made_up else None,
            "archive": f"{year}-{month}",
            "source_file": name,
            "facts_seen": parsed.get("facts_seen", 0),
            "weak_net_assets": parsed.get("weak_net_assets", False),
        }
        for field in FIELDS:
            row[field] = parsed.get(field)
        rows.append(row)

        if i % 500 == 0:
            log.info("  %s/%s parsed, %.0f MB fetched, %.0fs",
                     f"{i:,}", f"{len(wanted):,}", backing.bytes_fetched / 1e6,
                     time.monotonic() - t0)

    frame = pd.DataFrame(rows)
    frame.to_parquet(out_file, index=False)
    unreadable = len(wanted) - seen
    log.info(
        "%s %s: wrote %s rows (%s unparseable, %s unreadable) in %.0fs, "
        "%.0f MB fetched of which %.0f MB was the index",
        month, year, f"{len(rows):,}", f"{failed:,}", f"{unreadable:,}",
        time.monotonic() - t0, backing.bytes_fetched / 1e6, index_cost / 1e6,
    )
    return len(rows)


def load_into_database() -> None:
    """Load every monthly Parquet file into the study database."""
    files = sorted(OUT_DIR.glob("*.parquet"))
    if not files:
        log.error("No Parquet files in %s -- run the fetch first.", OUT_DIR)
        return

    con = db.connect()
    con.execute("DROP TABLE IF EXISTS accounts")
    con.execute(
        f"""
        CREATE TABLE accounts AS
        SELECT * FROM read_parquet('{OUT_DIR.as_posix()}/*.parquet')
        """
    )
    # A company can file the same year twice (an amended set, or the same
    # accounts appearing in two archives). Keep the latest archive for each
    # company and balance sheet date.
    con.execute(
        """
        CREATE OR REPLACE TABLE accounts AS
        SELECT * EXCLUDE (rn) FROM (
            SELECT *, row_number() OVER (
                PARTITION BY company_number, made_up_to ORDER BY archive DESC
            ) AS rn
            FROM accounts
        ) WHERE rn = 1
        """
    )

    n = con.execute("SELECT count(*) FROM accounts").fetchone()[0]
    companies = con.execute(
        "SELECT count(DISTINCT company_number) FROM accounts"
    ).fetchone()[0]
    cohort_total = con.execute("SELECT count(*) FROM companies").fetchone()[0]
    log.info("Loaded %s filings for %s companies (%.1f%% of the cohort has at "
             "least one parsed set of accounts)",
             f"{n:,}", f"{companies:,}", 100 * companies / max(cohort_total, 1))

    log.info("--- coverage by format and financial year ---")
    for fy, fmt, k in con.execute(
        """
        SELECT a.financial_year, c.format, count(DISTINCT a.company_number)
        FROM accounts a JOIN companies c USING (company_number)
        WHERE a.financial_year BETWEEN 2017 AND 2026
        GROUP BY 1,2 ORDER BY 1,2
        """
    ).fetchall():
        log.info("  %s %-8s %7s", fy, fmt, f"{k:,}")

    have_net_assets = con.execute(
        "SELECT count(*) FROM accounts WHERE net_assets IS NOT NULL"
    ).fetchone()[0]
    weak = con.execute(
        "SELECT count(*) FROM accounts WHERE weak_net_assets"
    ).fetchone()[0]
    log.info("Filings with a net assets figure: %s (%.1f%%); of those, %s came "
             "from a working-capital tag and are excluded from growth stats",
             f"{have_net_assets:,}", 100 * have_net_assets / max(n, 1), f"{weak:,}")

    db.append_flow(
        con,
        [
            ("08", "accounts_filings", n, "Parsed iXBRL accounts filings for cohort companies"),
            ("08", "accounts_companies", companies, "Cohort companies with at least one parsed filing"),
            ("08", "accounts_with_net_assets", have_net_assets, "Filings carrying a net assets figure"),
        ],
    )
    con.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="start", default="2018-01",
                        help="First archive month, YYYY-MM")
    parser.add_argument("--to", dest="end", default=None,
                        help="Last archive month, YYYY-MM (default: last month)")
    parser.add_argument("--load", action="store_true",
                        help="Load the Parquet files into DuckDB and stop")
    args = parser.parse_args()

    if args.load:
        load_into_database()
        return 0

    start = dt.date(int(args.start[:4]), int(args.start[5:7]), 1)
    if args.end:
        end = dt.date(int(args.end[:4]), int(args.end[5:7]), 1)
    else:
        today = dt.date.today()
        end = (today.replace(day=1) - dt.timedelta(days=1)).replace(day=1)

    cohort = cohort_numbers()
    log.info("Cohort: %s company numbers", f"{len(cohort):,}")
    log.info("Archives: %s to %s", args.start, end.strftime("%Y-%m"))

    total = 0
    for year, month in months(start, end):
        total += process_month(year, month, cohort)
    log.info("Fetch complete: %s filings parsed. Run with --load to build the table.",
             f"{total:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

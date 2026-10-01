"""
Step 20 -- reconstruct where each company was registered *while it was trading*.

The problem this fixes
----------------------
Every geographic figure in this study so far uses the registered office as it
stands today. For a company that failed, that address is usually wrong, and
wrong in a systematic direction: **when a company enters liquidation its
registered office is moved to the insolvency practitioner.**

The effect is large. Across the cohort, insolvency runs at 1.74% at ordinary
addresses and 9.61% at mass-registration addresses, and the addresses holding
the most insolvent companies are practitioners' offices -- 261 at one address
in NW11, 215 at one in N21. Mapping insolvency by borough without correcting
this produces a map of where liquidators work.

The fix
-------
Companies House records every change of registered office as an AD01 filing,
and the filing carries the full text of both the old and the new address. Those
filings are already in the cached filing histories, so the whole address
timeline can be reconstructed with no further API calls.

For example, company 06612844:

    2020-08-10  Quest House, Staines Road, Hounslow TW3 3JB
             ->  22 York Buildings, London WC2N 6JU
    2025-08-01  C/O Resolve Advisory Ltd, 22 York Buildings
             ->  C/O Restructuring and Recovery Service, 45 Gresham Street

The trading address is Hounslow. The address on the register today is a
restructuring firm in the City.

What this produces
------------------
For every company with a filing history: the full ordered address timeline, and
three derived addresses --

  first_address       the earliest address on record
  pre_exit_address    the address held immediately before the first insolvency
                      or strike-off filing: the best estimate of where the
                      business actually was
  current_address     the address as it stands now

Downstream, `pre_exit_address` replaces the current address for borough
assignment and premises matching. Companies with no address-change filing keep
their current address, which is then also their only address.

Caveat to publish: an AD01 gives the address as free text, not a structured
record, so parsing is best-effort and the postcode is the reliable part. Where
a postcode cannot be extracted the company keeps its current address and is
flagged.
"""

from __future__ import annotations

import json
import re
import sys
import time

import pandas as pd

import addresses
import config
import db
from ch_api import setup_logging

log = setup_logging("20_address_history")

RAW = config.DATA_RAW / "life_history" / "filing-history"
CACHE = config.DATA_PROCESSED / "address_history.parquet"

ADDRESS_FORMS = {"AD01", "AD02", "AD03", "AD04"}

# Filings that mark the beginning of the end. The address held immediately
# before the earliest of these is the best available estimate of where the
# business traded.
EXIT_MARKERS = ("LIQ", "WU", "AM", "GAZ1", "GAZ2", "DS01", "DS02", "4.20", "600", "601")

_POSTCODE = re.compile(
    r"\b([A-Z]{1,2}\d{1,2}[A-Z]?)\s*(\d[A-Z]{2})\b", re.I)


def split_address(text: str) -> tuple[str, str]:
    """Return (street-ish part, normalised postcode) from free-text address."""
    if not text:
        return "", ""
    m = None
    for m in _POSTCODE.finditer(text):
        pass  # keep the LAST match: the postcode ends the address
    if not m:
        return text.strip(), ""
    postcode = addresses.normalise_postcode(m.group(1) + m.group(2))
    street = text[: m.start()].strip(" ,")
    return street, postcode


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
                log.info("  %s files (%.0fs)", f"{files:,}", time.monotonic() - t0)
            try:
                items = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue

            moves, exit_date = [], None
            for f in items:
                ftype = (f.get("type") or "").upper()
                date = f.get("date") or ""
                if ftype in ADDRESS_FORMS:
                    dv = f.get("description_values") or {}
                    moves.append({
                        "date": dv.get("change_date") or date,
                        "old": (dv.get("old_address") or "").strip(),
                        "new": (dv.get("new_address") or "").strip(),
                    })
                if date and any(ftype.startswith(m) for m in EXIT_MARKERS):
                    if exit_date is None or date < exit_date:
                        exit_date = date

            if not moves:
                continue
            moves.sort(key=lambda m: m["date"])

            # The earliest address on record is the "old" side of the first move.
            first = moves[0]["old"] or moves[0]["new"]
            # The address held just before the first exit-related filing.
            pre_exit = first
            for m in moves:
                if exit_date and m["date"] >= exit_date:
                    break
                if m["new"]:
                    pre_exit = m["new"]
            current = moves[-1]["new"] or moves[-1]["old"]

            f_street, f_pc = split_address(first)
            p_street, p_pc = split_address(pre_exit)
            rows.append({
                "company_number": path.stem,
                "n_moves": len(moves),
                "first_address": first,
                "first_postcode": f_pc,
                "first_key": addresses.address_key(f_street, "", f_pc),
                "pre_exit_address": pre_exit,
                "pre_exit_postcode": p_pc,
                "pre_exit_key": addresses.address_key(p_street, "", p_pc),
                "current_address": current,
                "first_exit_filing": exit_date,
                "moved_after_exit_marker": bool(
                    exit_date and any(m["date"] >= exit_date for m in moves)),
            })

    log.info("Read %s filing histories in %.1f min; %s had address changes",
             f"{files:,}", (time.monotonic() - t0) / 60, f"{len(rows):,}")
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

    con = db.connect(wait_seconds=600)
    con.execute("DROP TABLE IF EXISTS address_history")
    con.register("_ah", frame)
    con.execute("CREATE TABLE address_history AS SELECT * FROM _ah")
    con.unregister("_ah")

    total = con.execute("SELECT count(*) FROM companies").fetchone()[0]
    with_moves = con.execute(
        "SELECT count(*) FROM companies c JOIN address_history a USING (company_number)"
    ).fetchone()[0]
    log.info("")
    log.info("Cohort companies with at least one registered-office move: %s of %s (%.1f%%)",
             f"{with_moves:,}", f"{total:,}", 100 * with_moves / total)

    moved_late = con.execute(
        """
        SELECT count(*) FROM companies c JOIN address_history a USING (company_number)
        WHERE a.moved_after_exit_marker
        """
    ).fetchone()[0]
    log.info("Companies that moved address AFTER an exit-related filing began: %s",
             f"{moved_late:,}")

    log.info("")
    log.info("--- how often the trading address differs from today's register entry ---")
    changed = con.execute(
        """
        SELECT
          count(*) FILTER (WHERE a.pre_exit_key <> '' AND a.pre_exit_key <> c.address_key) AS differs,
          count(*) FILTER (WHERE a.pre_exit_key <> '') AS comparable
        FROM companies c JOIN address_history a USING (company_number)
        """
    ).fetchone()
    log.info("  pre-exit address differs from current: %s of %s comparable (%.1f%%)",
             f"{changed[0]:,}", f"{changed[1]:,}", 100 * changed[0] / max(changed[1], 1))

    log.info("")
    log.info("--- insolvent companies: borough on the register vs borough while trading ---")
    rows = con.execute(
        """
        SELECT
          count(*) AS insolvent_with_history,
          count(*) FILTER (WHERE a.pre_exit_postcode <> ''
                             AND a.pre_exit_postcode <> c.postcode) AS relocated
        FROM companies c
        JOIN address_history a USING (company_number)
        JOIN company_exit_v2 e USING (company_number)
        WHERE e.exit_family = 'insolvency'
        """
    ).fetchone()
    log.info("  insolvent companies with an address history: %s", f"{rows[0]:,}")
    log.info("  of which registered somewhere else while trading: %s (%.1f%%)",
             f"{rows[1]:,}", 100 * rows[1] / max(rows[0], 1))

    log.info("")
    log.info("Next: rebuild borough assignment and the FSA premises match on "
             "pre_exit_key rather than the current address.")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

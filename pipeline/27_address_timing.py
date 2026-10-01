"""
Step 27 -- decompose the 87.8% by WHEN the registered office moved.

External review, correctly: a registered-office change during or after an
insolvency procedure is expected -- there is a formal Companies House
procedure for changing the registered office of a company in liquidation, and
practitioners routinely move the office to their own. So "87.8% of insolvent
companies show a changed office" conflates two different facts:

  * moves BEFORE any insolvency filing -- the register differed from wherever
    the company sat while it was still an ordinary trading company; and
  * moves ON/AFTER the first insolvency filing -- the procedure itself moving
    the record, which says nothing about the office's fidelity during life.

Only the decomposed version prints. The distress anchor is the date of the
company's FIRST filing carrying the Companies House category "insolvency",
read from the cached filing histories -- the same evidence the classifier
uses, so the two analyses cannot disagree about who is insolvent.

Reads: data/raw/life_history/filing-history for companies with
company_exit_v2.exit_family = 'insolvency'. Writes: out/address_timing.csv.
"""

from __future__ import annotations

import json
import sys

import pandas as pd

import config
import db
from ch_api import setup_logging

log = setup_logging("27_address_timing")

RAW = config.DATA_RAW / "life_history" / "filing-history"
ADDRESS_FORMS = {"AD01", "AD02", "AD03", "AD04"}


def main() -> int:
    con = db.connect(read_only=True, wait_seconds=600)
    insolvent = [
        r[0] for r in con.execute(
            "SELECT company_number FROM company_exit_v2 "
            "WHERE exit_family = 'insolvency'"
        ).fetchall()
    ]
    con.close()
    log.info("Insolvent companies to examine: %s", f"{len(insolvent):,}")

    rows = []
    missing = 0
    for number in insolvent:
        path = RAW / number[:2] / f"{number}.json"
        if not path.exists():
            missing += 1
            continue
        try:
            filings = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            missing += 1
            continue

        first_insolvency = None
        moves = []
        for f in filings:
            date = f.get("date") or ""
            if not date:
                continue
            if (f.get("category") or "").lower() == "insolvency":
                if first_insolvency is None or date < first_insolvency:
                    first_insolvency = date
            if (f.get("type") or "").upper() in ADDRESS_FORMS:
                dv = f.get("description_values") or {}
                moves.append(dv.get("change_date") or date)

        if first_insolvency is None:
            # Classified insolvent via form codes without a category-tagged
            # filing; rare. Anchor on the earliest classifying form instead
            # would re-implement the classifier -- record and skip.
            missing += 1
            continue

        before = sum(1 for m in moves if m < first_insolvency)
        after = sum(1 for m in moves if m >= first_insolvency)
        rows.append({
            "company_number": number,
            "n_moves": len(moves),
            "moves_before": before,
            "moves_after": after,
            "first_insolvency": first_insolvency,
        })

    df = pd.DataFrame(rows)
    df.to_csv(config.OUT / "address_timing.csv", index=False)

    n = len(df)
    any_move = df[df.n_moves > 0]
    log.info("Examined %s insolvent companies (%s unusable: no history file "
             "or no category-dated anchor)", f"{n:,}", f"{missing:,}")
    log.info("")
    log.info("--- registered-office moves relative to the FIRST insolvency filing ---")
    log.info("  no move ever recorded:            %6s  (%5.1f%%)",
             f"{n - len(any_move):,}", 100 * (n - len(any_move)) / n)
    log.info("  moved ONLY on/after commencement: %6s  (%5.1f%%)",
             f"{len(any_move[(any_move.moves_before == 0)]):,}",
             100 * len(any_move[(any_move.moves_before == 0)]) / n)
    log.info("  moved before AND after:           %6s  (%5.1f%%)",
             f"{len(any_move[(any_move.moves_before > 0) & (any_move.moves_after > 0)]):,}",
             100 * len(any_move[(any_move.moves_before > 0) & (any_move.moves_after > 0)]) / n)
    log.info("  moved ONLY before (never after):  %6s  (%5.1f%%)",
             f"{len(any_move[(any_move.moves_before > 0) & (any_move.moves_after == 0)]):,}",
             100 * len(any_move[(any_move.moves_before > 0) & (any_move.moves_after == 0)]) / n)
    log.info("")
    log.info("  companies with ANY pre-commencement move:  %s of %s (%.1f%%)",
             f"{int((df.moves_before > 0).sum()):,}", f"{n:,}",
             100 * (df.moves_before > 0).mean())
    log.info("  companies with ANY post-commencement move: %s of %s (%.1f%%)",
             f"{int((df.moves_after > 0).sum()):,}", f"{n:,}",
             100 * (df.moves_after > 0).mean())
    log.info("")
    log.info("Print rule: the mislocation claim rests on the POST-commencement "
             "share (the record moves when the company fails, so TODAY'S "
             "address misplaces HISTORICAL failure). The pre-commencement "
             "share is reported separately as ordinary relocation during "
             "life. The undecomposed 87.8%% is withdrawn from all documents.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

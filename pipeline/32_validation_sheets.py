"""
Step 32 -- generate the manual-validation review sheets.

The method requires two hand-checked samples with published error rates:
200 exit classifications and 200 premises matches. Checking is human work;
this builds the sheets so the reviewer opens a CSV, reads the evidence, and
fills two columns (verdict, notes).

Exit sample: stratified by classified route -- insolvency routes oversampled
(they are rare and carry the headline), strike-off routes proportionally.
Each row: company, our route, and the decisive filings (type, date,
description) drawn from the cached history, plus the public filing-history
URL for anything ambiguous.

Premises sample: 200 Tier-A matches, Companies House name/address beside FSA
name/address, with the address key both sides matched on.

Sampling is deterministic (md5 order) so the sheets are reproducible.
Outputs: out/validation/exit_sample.csv, out/validation/premises_sample.csv
"""

from __future__ import annotations

import json
import sys

import pandas as pd

import config
import db
from ch_api import setup_logging

log = setup_logging("32_validation_sheets")

RAW = config.DATA_RAW / "life_history" / "filing-history"
OUT = config.OUT / "validation"

# route -> sample size. Insolvency oversampled; totals 200.
EXIT_QUOTA = {
    "registrar_strike_off": 45,
    "voluntary_strike_off": 45,
    "creditors_voluntary_liquidation": 40,
    "compulsory_liquidation": 30,
    "members_voluntary_liquidation": 20,
    "administration": 10,
    "insolvency_other": 10,
}

DECISIVE_FORMS = (
    "GAZ1", "GAZ2", "GAZ1(A)", "GAZ2(A)", "DS01", "DS02", "LIQ01", "LIQ02",
    "LIQ03", "LIQ10", "LIQ13", "LIQ14", "WU01", "WU02", "WU15", "4.20",
    "4.70", "4.68", "600", "601", "602", "LRESSP", "2.24B",
)


def decisive_filings(number: str) -> str:
    path = RAW / number[:2] / f"{number}.json"
    if not path.exists():
        return "(no cached history)"
    try:
        filings = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return "(unreadable)"
    lines = []
    for f in filings:
        ftype = (f.get("type") or "").upper()
        cat = (f.get("category") or "").lower()
        if ftype in DECISIVE_FORMS or ftype.startswith("AM") or cat == "insolvency":
            desc = (f.get("description") or "")[:80]
            lines.append(f"{f.get('date','?')} {ftype} {desc}")
    return " || ".join(lines[:12]) or "(no exit-related filings found)"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    con = db.connect(read_only=True, wait_seconds=600)

    frames = []
    for route, quota in EXIT_QUOTA.items():
        frames.append(con.execute(
            f"""
            SELECT c.company_number, c.company_name, c.sic_primary, c.format,
                   c.born, c.died, e.exit_route, e.exit_family
            FROM companies c JOIN company_exit_v2 e USING (company_number)
            WHERE e.exit_route = '{route}'
            ORDER BY md5(c.company_number)
            LIMIT {quota}
            """
        ).df())
    exits = pd.concat(frames, ignore_index=True)
    log.info("Exit sample: %d rows across %d routes", len(exits), len(EXIT_QUOTA))
    exits["decisive_filings"] = exits.company_number.map(decisive_filings)
    exits["filing_history_url"] = (
        "https://find-and-update.company-information.service.gov.uk/company/"
        + exits.company_number + "/filing-history"
    )
    exits["reviewer_verdict"] = ""
    exits["reviewer_correct_route"] = ""
    exits["reviewer_notes"] = ""
    exits.to_csv(OUT / "exit_sample.csv", index=False)

    premises = con.execute(
        """
        SELECT t.company_number, c.company_name,
               c.addr1 AS ch_addr1, c.addr2 AS ch_addr2, c.postcode AS ch_postcode,
               f.business_name AS fsa_name, f.addr1 AS fsa_addr1,
               f.addr2 AS fsa_addr2, f.postcode AS fsa_postcode,
               f.business_type, t.address_source
        FROM company_tier t
        JOIN companies c USING (company_number)
        JOIN company_premises p USING (company_number)
        JOIN fsa_establishments f ON f.fhrsid = p.fhrsid
        WHERE t.tier = 'A_premises_confirmed'
        ORDER BY md5(t.company_number)
        LIMIT 200
        """
    ).df()
    premises["reviewer_verdict"] = ""
    premises["reviewer_notes"] = ""
    premises.to_csv(OUT / "premises_sample.csv", index=False)
    log.info("Premises sample: %d rows", len(premises))

    con.close()
    log.info("Sheets written to %s. Review instructions: verdict is one of "
             "AGREE / DISAGREE / UNCLEAR; for exits, correct_route filled "
             "only on DISAGREE. Error rates publish whatever they are.", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())

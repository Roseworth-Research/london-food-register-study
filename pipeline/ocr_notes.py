"""
Find and read the notes that decide the VAT answer.

The income statement gives one number: revenue. That number is not enough, for
two reasons that only became obvious once the businesses were looked at
properly rather than as brand names.

1. These are not shops. They are groups.
   Costa Limited's revenue includes company-operated stores, franchise
   royalties, Costa Express self-serve machines, wholesale roasted coffee sold
   to franchisees and third parties, and packaged coffee sold through
   supermarkets. Greggs has company-managed shops, franchise shops, and a
   wholesale arm selling frozen product through a supermarket partner. Pret
   sells through supermarkets and franchises internationally. Gail's runs a
   wholesale bakery supplying trade customers.

   Every one of those streams has a different VAT treatment, and two of them
   invert the naive assumption entirely: retail coffee BEANS are zero-rated
   food, not a standard-rated drink, and wholesale supplies to a VAT-registered
   trade customer are recovered by that customer, so they are no burden at all.

2. VAT is a net tax.
   What a business actually hands to HMRC is output tax minus recoverable input
   tax. A business whose sales are zero-rated and whose costs carry VAT is in a
   REPAYMENT position -- HMRC pays it. So the cost base matters as much as the
   sales mix, and the notes disclose enough of it to model: staff costs (no
   VAT), depreciation (no VAT), inventories expensed (mostly zero-rated food),
   leases, and the residue of operating costs that does carry VAT.

This script hunts the pages carrying those notes and OCRs them, so the model in
13_vat_model.py can be built on disclosed structure rather than on a guess
about what a brand sells.
"""

from __future__ import annotations

import json
import re
import sys
import time

import pymupdf

import config
from ch_api import setup_logging
from ocr_accounts import ocr_page

log = setup_logging("ocr_notes")

# Pages worth reading, and what makes them worth reading.
NOTE_PATTERNS = {
    "revenue_disaggregation": re.compile(
        r"(disaggregationofrevenue|revenuefromcontractswithcustomers"
        r"|franchise|royalt|wholesale|licencefee|licensefee|concession"
        r"|costaexpress|salesofgoods|saleofgoods|renderingofservices"
        r"|revenuebyproduct|revenuebysegment|analysisofrevenue|segmental)",
        re.I,
    ),
    "operating_costs": re.compile(
        r"(costofinventoriesrecognised|staffcosts|wagesandsalaries"
        r"|operatingprofitisstatedafter|operatingcosts|expensesbynature"
        r"|auditorsremuneration|auditorremuneration)",
        re.I,
    ),
    "leases": re.compile(
        r"(rightofuseassets|leaseliabilities|operatingleasecommitments"
        r"|shorttermleases|lowvalueleases)",
        re.I,
    ),
    "vat_or_other_taxes": re.compile(
        r"(othertaxesandsocialsecurity|othertaxationandsocialsecurity"
        r"|valueaddedtax|vatpayable|vatreceivable)",
        re.I,
    ),
    # The delivery platforms' key disclosure, and the only route to the number
    # the report actually needs. Revenue tells you what the platform kept; GTV
    # tells you what the customer spent. revenue / GTV is the take rate -- the
    # share of every order that leaves the high street. Listed platforms report
    # GTV as an alternative performance measure because investors demand it,
    # so it sits in the financial review and the APM appendix rather than in
    # the primary statements.
    "gtv_and_take_rate": re.compile(
        r"(grosstransactionvalue|\bgtv\b|transactionvalue|ordervalue"
        r"|averageordervalue|\baov\b|takerate|grossmerchandisevalue|\bgmv\b"
        r"|alternativeperformancemeasure)",
        re.I,
    ),
}


def scan(pdf_path: str, band: tuple[int, int], dpi: int = 200) -> dict:
    """OCR a band of pages and keep every page that matches a note pattern."""
    doc = pymupdf.open(pdf_path)
    first, last = band[0], min(band[1], len(doc))
    hits: dict[str, list] = {k: [] for k in NOTE_PATTERNS}

    for page_no in range(first, last + 1):
        lines = ocr_page(doc, page_no, dpi)
        if not lines:
            continue
        squashed = re.sub(r"\s+", "", " ".join(lines))
        for key, pattern in NOTE_PATTERNS.items():
            if pattern.search(squashed):
                hits[key].append({"page": page_no, "lines": lines})
    doc.close()
    return hits


def main() -> int:
    group = sys.argv[1] if len(sys.argv) > 1 else "chains"
    targets_file = config.SOURCES / group / "note_targets.json"
    if not targets_file.exists():
        log.error("%s not found. Write the page bands to scan first.", targets_file)
        return 1

    targets = json.loads(targets_file.read_text(encoding="utf-8"))
    out_path = config.SOURCES / group / "ocr_notes.json"
    results = json.loads(out_path.read_text()) if out_path.exists() else {}

    for entry in targets:
        key = f"{entry['slug']}|{entry['made_up_to']}"
        if key in results:
            log.info("%s already done", key)
            continue
        t0 = time.monotonic()
        hits = scan(entry["path"], tuple(entry["band"]))
        results[key] = hits
        out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        summary = ", ".join(f"{k}:{len(v)}" for k, v in hits.items() if v) or "nothing"
        log.info("%-26s pages %s-%s in %4.0fs  ->  %s",
                 key, entry["band"][0], entry["band"][1], time.monotonic() - t0, summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())

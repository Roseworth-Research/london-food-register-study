"""
Step 14 -- the delivery platforms: how much of the ticket leaves the high street.

The point of this section is not that delivery grew. Everyone knows delivery
grew. The point is the one the study brief states: **delivery growth is not
margin growth.** A restaurant that replaces a £30 table with a £30 delivery
order has not replaced the money, because a fifth to a third of it is now
somebody else's revenue.

That claim needs two numbers per platform per year, and only one of them is in
the profit and loss account:

  GTV      gross transaction value -- what customers actually spent
  revenue  what the platform kept

revenue ÷ GTV is the **take rate**: the share of every order that leaves the
restaurant. It is the single most useful number in this part of the report,
and it is disclosed by the listed platforms because investors demand it.

Entity notes
------------
The corporate structures matter and are easy to get wrong.

  Deliveroo    Roofoods Ltd (08167130) is the UK trading company and has filed
               since 2013. Deliveroo Limited (13227665) is the former
               Deliveroo plc, listed in 2021 and re-registered as a private
               company after the DoorDash acquisition completed in 2025. The
               plc accounts carry GTV and segment revenue; Roofoods carries UK
               statutory turnover.
  Just Eat     Just Eat Limited (06947854) and Just Eat Holding Limited
               (05438939). The group parent is Just Eat Takeaway.com N.V.,
               Amsterdam-listed until Prosus took it private in 2025, and the
               UK segment figures live in the N.V. annual report, not at
               Companies House.
  Uber Eats    Uber Eats UK Limited (10078453). Most Uber Eats economics sit
               with Uber Portier B.V. in the Netherlands and appear in Uber
               Technologies' SEC filings as the Delivery segment. The UK
               company's accounts will not show the whole picture and the
               report must say so rather than implying they do.
  Stuart       Stuart Delivery Ltd (09790251), the courier platform used by
               many operators for their own-brand delivery. Included because
               it is the "keep the customer, rent the rider" alternative and
               a different economic proposition.

Two consequences for the report, both of which must be printed:

1. **No single source covers UK delivery.** Companies House gives UK statutory
   turnover for the local entities; GTV and take rate come from the listed
   parents' reports; Uber's UK slice is not separately disclosed at all.
2. **Both major platforms went private in 2025.** Deliveroo to DoorDash, Just
   Eat to Prosus. The last fully public years are the last reliable ones, and
   the series ends there by necessity, not by choice.
"""

from __future__ import annotations

import json
import sys

import config
from ch_api import CompaniesHouseClient, setup_logging
from ch_documents import fetch_document

log = setup_logging("14_platforms")

EARLIEST_YEAR_END = "2016-01-01"
OUT_DIR = config.SOURCES / "platforms"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PLATFORMS = {
    "08167130": {
        "name": "Roofoods Ltd (Deliveroo UK)", "slug": "roofoods",
        "role": "Deliveroo's UK trading company. Longest continuous UK series.",
    },
    "13227665": {
        "name": "Deliveroo Limited (formerly Deliveroo plc)", "slug": "deliveroo_plc",
        "role": "Listed parent 2021-2025. Discloses GTV and segment revenue -- "
                "the take-rate numbers. Re-registered private after DoorDash.",
    },
    "06947854": {
        "name": "Just Eat Limited", "slug": "justeat",
        "role": "UK trading company. Group segment data is in the Amsterdam "
                "parent's report, not here.",
    },
    "05438939": {
        "name": "Just Eat Holding Limited", "slug": "justeat_holding",
        "role": "UK holding company; may carry consolidated UK figures.",
    },
    "10078453": {
        "name": "Uber Eats UK Limited", "slug": "ubereats",
        "role": "UK entity only. Most Uber Eats economics sit in the "
                "Netherlands and appear in Uber's SEC filings.",
    },
    "09790251": {
        "name": "Stuart Delivery Ltd", "slug": "stuart",
        "role": "Courier platform for operators running their own delivery -- "
                "the 'rent the rider, keep the customer' model.",
    },
}


def main() -> int:
    client = CompaniesHouseClient()
    index: dict[str, list[dict]] = {}

    for number, meta in PLATFORMS.items():
        slug = meta["slug"]
        folder = OUT_DIR / slug
        folder.mkdir(parents=True, exist_ok=True)

        profile = client.company_profile(number) or {}
        log.info("")
        log.info("%s (%s)", meta["name"], number)
        log.info("  status=%s  SIC=%s  incorporated=%s",
                 profile.get("company_status"), profile.get("sic_codes"),
                 profile.get("date_of_creation"))
        log.info("  %s", meta["role"])

        filings = client.get_all_items(
            f"/company/{number}/filing-history", {"category": "accounts"}
        )
        records = []
        for f in filings:
            values = f.get("description_values") or {}
            made_up = values.get("made_up_date") or f.get("action_date") or f.get("date")
            if not made_up or made_up < EARLIEST_YEAR_END:
                continue
            links = f.get("links") or {}
            meta_link = links.get("document_metadata")
            if not meta_link:
                continue
            doc_id = meta_link.rstrip("/").split("/")[-1]
            dest = folder / f"{made_up}_{f.get('type','AA')}.pdf"
            if not dest.exists():
                raw = fetch_document(doc_id, client._auth, "application/pdf")
                if not raw:
                    log.warning("  %s %s: no PDF available", slug, made_up)
                    continue
                dest.write_bytes(raw)
                log.info("  downloaded %s %-10s %6.1f MB", made_up, f.get("type"),
                         len(raw) / 1e6)
            records.append({
                "made_up_to": made_up, "type": f.get("type"),
                "filed": f.get("date"), "path": str(dest), "document_id": doc_id,
            })
        index[number] = records
        log.info("  %d accounts filings held", len(records))

    (OUT_DIR / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    log.info("")
    log.info("Index written to %s", OUT_DIR / "index.json")
    log.info("Next: build OCR targets for the income statements, as for the chains.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

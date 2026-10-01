"""
Step 12 -- the named chains: revenue, and an estimate of the VAT they carry.

Why the chains matter to this study
-----------------------------------
The company-level analysis splits formats by SIC code, and SIC code is
self-assigned and unreliable. The chains prove the point in their own filings:

    Greggs plc              10710 manufacture of bread, 47240 retail bread
    Pret A Manger (Europe)  47110 retail in non-specialised stores
    Costa Limited           10832 processing of tea and coffee, 56101 LICENSED RESTAURANTS
    Bread Holdings (Gail's) 10710 manufacture of bread

A coffee chain files as a licensed restaurant. A sandwich chain files as a
non-specialised shop. A bakery group files as a manufacturer. None of the four
would appear in the London cohort as the format it actually operates, and by
the same token an unknown share of the cohort's 56102 "unlicensed restaurants
and cafés" are counter-led businesses sitting in the service bucket.

The chains are the answer to that problem, not another instance of it. They
publish audited turnover, they describe their own sales mix in their strategic
reports, and their formats are known to anyone who has stood in one. So they
can carry the VAT argument with real numbers where the SIC-coded cohort cannot.

What this script does and does not do
-------------------------------------
DOES: download every set of accounts each company has filed, extract the text,
and pull out the candidate turnover lines for verification.

DOES NOT: state a VAT figure as fact. **No UK company discloses VAT paid in its
statutory accounts.** Turnover is reported net of VAT, and there is no line
anywhere for the output tax collected. Any figure for "VAT paid" is therefore a
model, not a measurement, and this script keeps the two clearly separated: the
revenue table is evidence, the VAT table is an estimate under stated
assumptions. See 13_vat_model.py.

All four file accounts as PDF, not iXBRL -- large-company filings are not in
the bulk iXBRL product. Text extraction gets the numbers close enough to
locate; every figure that reaches the report is checked against the page it
came from, as the study brief requires ("Ten documents, read
manually").
"""

from __future__ import annotations

import json
import re
import sys

import config
from ch_api import CompaniesHouseClient, setup_logging
from ch_documents import fetch_document

log = setup_logging("12_chains")

# Seven full years plus a comparative. Anything earlier is out of scope.
EARLIEST_YEAR_END = "2017-01-01"

OUT_DIR = config.SOURCES / "chains"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CHAINS = {
    "00502851": {
        "name": "Greggs plc",
        "slug": "greggs",
        "format": "counter, bakery and food-to-go",
        "note": "Listed. Group accounts. Mostly takeaway; a minority of shops have seating.",
    },
    "01854213": {
        "name": "Pret A Manger (Europe) Limited",
        "slug": "pret",
        "format": "counter with seating",
        "note": "Main UK trading entity. Charges a higher eat-in price at some sites.",
    },
    "01270695": {
        "name": "Costa Limited",
        "slug": "costa",
        "format": "coffee shop, counter with seating",
        "note": "Year-end moved from Feb/Mar to Dec after the Coca-Cola acquisition in Jan 2019.",
    },
    "07570780": {
        "name": "Bread Holdings Limited (Gail's)",
        "slug": "gails",
        "format": "bakery counter with seating",
        "note": "February year-end. Filed as a bread manufacturer. Check for a group parent above it.",
    },
}

# Lines in an income statement that plausibly carry the top-line figure.
REVENUE_PATTERNS = [
    r"\b(?:Revenue|Turnover|Total revenue|Group revenue|Sales)\b",
]
# Anything mentioning VAT at all, because the strategic report sometimes says
# something useful about the mix even though the accounts never quantify it.
VAT_PATTERNS = [r"\bVAT\b", r"value added tax", r"zero[- ]rated", r"standard[- ]rated",
                r"eat[- ]in", r"takeaway", r"take[- ]away"]

_MONEY = re.compile(r"-?[\d,]{3,}(?:\.\d)?")


def download_all(client: CompaniesHouseClient) -> dict:
    """Download every accounts filing for each chain. Returns an index."""
    index: dict[str, list[dict]] = {}
    for number, meta in CHAINS.items():
        slug = meta["slug"]
        folder = OUT_DIR / slug
        folder.mkdir(parents=True, exist_ok=True)
        filings = client.get_all_items(
            f"/company/{number}/filing-history", {"category": "accounts"}
        )
        records = []
        for f in filings:
            values = f.get("description_values") or {}
            made_up = values.get("made_up_date") or f.get("action_date") or f.get("date")
            # The study needs seven years plus one comparative. Older filings
            # are skipped: some pre-2012 documents cannot be served at all and
            # none of them are in scope.
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
                log.info("  %s %s %-10s %6.1f MB", slug, made_up, f.get("type"),
                         len(raw) / 1e6)
            records.append({
                "made_up_to": made_up,
                "type": f.get("type"),
                "filed": f.get("date"),
                "path": str(dest),
                "document_id": doc_id,
            })
        index[number] = records
        log.info("%s: %d accounts filings held", meta["name"], len(records))
    (OUT_DIR / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    return index


def extract_candidates(path: str, context: int = 220) -> dict:
    """Pull candidate revenue lines and any VAT commentary out of one PDF."""
    try:
        from pypdf import PdfReader
    except ImportError:
        log.error("pypdf not installed: pip install pypdf")
        return {}

    try:
        reader = PdfReader(path)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}

    revenue_hits, vat_hits = [], []
    for page_no, page in enumerate(reader.pages, 1):
        try:
            text = page.extract_text() or ""
        except Exception:
            continue
        flat = re.sub(r"[ \t]+", " ", text)
        for line in flat.splitlines():
            line = line.strip()
            if not line:
                continue
            if any(re.search(p, line, re.I) for p in REVENUE_PATTERNS) and _MONEY.search(line):
                revenue_hits.append({"page": page_no, "line": line[:200]})
        for pattern in VAT_PATTERNS:
            for m in re.finditer(pattern, flat, re.I):
                snippet = flat[max(0, m.start() - context // 2): m.start() + context]
                vat_hits.append({
                    "page": page_no,
                    "term": pattern,
                    "text": re.sub(r"\s+", " ", snippet).strip(),
                })
    return {
        "pages": len(reader.pages),
        "revenue_candidates": revenue_hits[:40],
        "vat_mentions": vat_hits[:40],
    }


def main() -> int:
    client = CompaniesHouseClient()
    log.info("Downloading chain accounts to %s", OUT_DIR)
    index = download_all(client)

    log.info("")
    log.info("Extracting candidate revenue lines")
    findings = {}
    for number, records in index.items():
        slug = CHAINS[number]["slug"]
        findings[slug] = {}
        for record in records:
            result = extract_candidates(record["path"])
            findings[slug][record["made_up_to"]] = result
            n_rev = len(result.get("revenue_candidates", []))
            n_vat = len(result.get("vat_mentions", []))
            log.info("  %-8s %-12s %3s pages  %2d revenue lines  %2d VAT mentions",
                     slug, record["made_up_to"], result.get("pages", "?"), n_rev, n_vat)

    out = OUT_DIR / "extracted.json"
    out.write_text(json.dumps(findings, indent=2), encoding="utf-8")
    log.info("")
    log.info("Written to %s -- every figure used in the report is then checked "
             "against the page it came from.", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

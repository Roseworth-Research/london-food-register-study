"""
Read figures out of the chains' scanned accounts.

Companies House stores filed accounts as image-only PDFs. There is no text
layer -- verified across all four chains and every year held, using two
independent extractors. So the numbers have to be recognised, not parsed.

This uses RapidOCR, which runs locally on ONNX Runtime and needs no system
binary and no network call. The accounts never leave the machine.

Strategy
--------
OCR is slow relative to text extraction, so pages are not processed blindly.
A statutory profit and loss account is easy to identify: a page whose text
contains a revenue heading, a period label and at least two large numbers in
column. The script walks a candidate band of pages, scores each one, and stops
once it has found the statement it is looking for.

Everything recognised is written to disk with its page number, so any figure
that reaches the report can be traced back to a page and checked by eye. OCR
misreads digits -- that is a fact about OCR, not a risk to be waved away -- so
this produces candidates for verification, never final figures.
"""

from __future__ import annotations

import json
import re
import sys
import time

import pymupdf

import config
from ch_api import setup_logging

log = setup_logging("ocr_accounts")

_ocr = None


def ocr_engine():
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr = RapidOCR()
    return _ocr


# A page holding the income statement almost always carries one of these.
# Matched against a space-stripped copy of the page: OCR frequently loses the
# spaces in a heading set in a display face, so "Statement of Comprehensive
# Income" comes back as "Statement of ComprehensiveIncome" and a literal match
# fails on a page that is plainly the right one.
STATEMENT_HEADINGS = re.compile(
    r"(statementofcomprehensiveincome|incomestatement|profitandlossaccount"
    r"|statementofprofitorloss|consolidatedincomestatement"
    r"|groupincomestatement|statementofincome)",
    re.I,
)
REVENUE_LINE = re.compile(r"^\s*(revenue|turnover|total revenue|group revenue|sales)\b", re.I)
NUMBER = re.compile(r"\(?-?[\d][\d,]{2,}(?:\.\d+)?\)?")


def ocr_page(doc, page_no: int, dpi: int = 200) -> list[str]:
    """Return the recognised text lines of one page, top to bottom."""
    pix = doc[page_no - 1].get_pixmap(dpi=dpi)
    png = pix.tobytes("png")
    result, _ = ocr_engine()(png)
    if not result:
        return []
    # RapidOCR returns [box, text, confidence]; group into visual lines by the
    # vertical centre of each box so a table row reads as one string.
    boxes = []
    for box, text, conf in result:
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        boxes.append((sum(ys) / len(ys), sum(xs) / len(xs), text))
    boxes.sort()
    lines, current, last_y = [], [], None
    for y, x, text in boxes:
        if last_y is not None and abs(y - last_y) > 12:
            lines.append(" ".join(t for _, t in sorted(current)))
            current = []
        current.append((x, text))
        last_y = y
    if current:
        lines.append(" ".join(t for _, t in sorted(current)))
    return lines


def find_income_statement(pdf_path: str, band: tuple[int, int], dpi: int = 200) -> dict:
    """Scan a band of pages for the income statement. Returns what it found."""
    doc = pymupdf.open(pdf_path)
    first, last = band[0], min(band[1], len(doc))
    found = {"pdf": pdf_path, "pages_scanned": [], "statement_page": None,
             "revenue_lines": [], "all_lines": []}

    for page_no in range(first, last + 1):
        lines = ocr_page(doc, page_no, dpi)
        found["pages_scanned"].append(page_no)
        squashed = re.sub(r"\s+", "", " ".join(lines))
        heading = bool(STATEMENT_HEADINGS.search(squashed))
        revenue_lines = [ln for ln in lines if REVENUE_LINE.match(ln) and NUMBER.search(ln)]
        if heading and revenue_lines:
            found["statement_page"] = page_no
            found["revenue_lines"] = revenue_lines
            # Keep the whole page. The report's cross-check is that revenue
            # minus cost of sales equals gross profit; without the other lines
            # there is nothing to check the recognised digits against.
            found["all_lines"] = lines
            break
        # Keep any revenue-looking line even off the main statement: annual
        # reports repeat the top line in a highlights page or a five-year record.
        if revenue_lines:
            found["revenue_lines"].extend(
                [f"p{page_no}: {ln}" for ln in revenue_lines]
            )
            found.setdefault("context_pages", {})[str(page_no)] = lines
    doc.close()
    return found


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    # Defaults to the chains; pass a directory name to run over another set,
    # e.g. `python ocr_accounts.py platforms`.
    group = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "chains"
    group = "chains" if group == "run" else group
    targets = json.loads((config.SOURCES / group / "ocr_targets.json").read_text())
    out_path = config.SOURCES / group / "ocr_results.json"
    results = json.loads(out_path.read_text()) if out_path.exists() else {}

    for entry in targets:
        key = f"{entry['slug']}|{entry['made_up_to']}"
        if key in results and results[key].get("statement_page"):
            log.info("%s already done (page %s)", key, results[key]["statement_page"])
            continue
        t0 = time.monotonic()
        found = find_income_statement(entry["path"], tuple(entry["band"]))
        results[key] = found
        out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        log.info(
            "%-24s scanned %2d pages in %4.0fs -> statement page %s, %d revenue lines",
            key, len(found["pages_scanned"]), time.monotonic() - t0,
            found["statement_page"], len(found["revenue_lines"]),
        )
        for line in found["revenue_lines"][:4]:
            log.info("      %s", line[:120])
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
Render pages of a scanned PDF to images so they can be read.

Companies House stores filed accounts as image-only PDFs -- there is no text
layer to extract, verified across all four chains and every year held. The
figures therefore have to be read off the page, which is what the study brief
section 3 step 5 assumed anyway ("Ten documents, read manually").

Two modes:

    contact   a grid of thumbnails, for finding which page holds the profit
              and loss account without opening thirty images
    page      one or more pages at full resolution, for reading the numbers

Usage:
    python render_pdf.py contact <pdf> [first] [last]
    python render_pdf.py page    <pdf> <from>-<to> [dpi]
"""

from __future__ import annotations

import pathlib
import sys

import pymupdf

import config

SCRATCH = config.OUT / "page_renders"
SCRATCH.mkdir(parents=True, exist_ok=True)


def contact_sheet(pdf_path: str, first: int = 1, last: int | None = None,
                  cols: int = 5, thumb_width: int = 430) -> pathlib.Path:
    """A grid of page thumbnails, large enough to recognise a P&L by its shape."""
    doc = pymupdf.open(pdf_path)
    last = min(last or len(doc), len(doc))
    pages = list(range(first - 1, last))
    rows = (len(pages) + cols - 1) // cols

    first_pix = doc[pages[0]].get_pixmap(dpi=72)
    ratio = first_pix.height / first_pix.width
    thumb_height = int(thumb_width * ratio)

    sheet = pymupdf.Pixmap(
        pymupdf.csRGB, pymupdf.IRect(0, 0, cols * thumb_width, rows * thumb_height), False
    )
    sheet.clear_with(255)

    for i, page_no in enumerate(pages):
        scale = thumb_width / doc[page_no].rect.width
        pix = doc[page_no].get_pixmap(matrix=pymupdf.Matrix(scale, scale))
        x, y = (i % cols) * thumb_width, (i // cols) * thumb_height
        pix.set_origin(x, y)
        sheet.copy(pix, pix.irect)

    out = SCRATCH / f"{pathlib.Path(pdf_path).stem}_contact_{first}-{last}.png"
    sheet.save(out)
    doc.close()
    print(f"{out}  ({cols} columns, pages {first}-{last})")
    return out


def render_pages(pdf_path: str, spec: str, dpi: int = 200) -> list[pathlib.Path]:
    """Render a page or range at readable resolution."""
    doc = pymupdf.open(pdf_path)
    if "-" in spec:
        a, b = spec.split("-")
        wanted = range(int(a), int(b) + 1)
    else:
        wanted = [int(spec)]

    out_files = []
    for page_no in wanted:
        if not 1 <= page_no <= len(doc):
            continue
        pix = doc[page_no - 1].get_pixmap(dpi=dpi)
        out = SCRATCH / f"{pathlib.Path(pdf_path).stem}_p{page_no}.png"
        pix.save(out)
        out_files.append(out)
        print(out)
    doc.close()
    return out_files


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(1)
    mode, pdf = sys.argv[1], sys.argv[2]
    if mode == "contact":
        contact_sheet(pdf,
                      int(sys.argv[3]) if len(sys.argv) > 3 else 1,
                      int(sys.argv[4]) if len(sys.argv) > 4 else None)
    else:
        render_pages(pdf, sys.argv[3],
                     int(sys.argv[4]) if len(sys.argv) > 4 else 200)

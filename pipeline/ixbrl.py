"""
A deliberately small iXBRL reader for Companies House small-company accounts.

Why not a full XBRL processor
-----------------------------
Full XBRL tooling resolves taxonomies, validates calculation linkbases and
handles dimensional breakdowns. None of that is needed here. The study wants
five numbers per filing -- net assets, equity, creditors, cash and average
employees -- from accounts filed under FRS 102 Section 1A or FRS 105, which are
short documents with flat tagging. Parsing the inline tags directly with lxml
is faster, has no taxonomy dependency, and is auditable: a reader can see
exactly which tag names were accepted and how the numbers were scaled.

The cost is that anything unusual is skipped rather than interpreted, and the
proportion skipped is reported.

What the format looks like
--------------------------
An iXBRL document is XHTML with facts marked up inline:

    <ix:nonFraction name="ns5:NetAssetsLiabilities" contextRef="c12"
                    unitRef="GBP" decimals="0" scale="0" sign="-">48,215</ix:nonFraction>

The value is the element's text with separators removed, multiplied by
10^scale, negated if sign is "-". The contextRef points at a context element
elsewhere in the document that carries the reporting date. Element names are
namespace-prefixed and the prefix varies by filing software, so matching is
done on the local name only.

Known limitations, all stated in the methodology appendix
---------------------------------------------------------
  * Paper-filed accounts are scanned PDFs with no tagging and are invisible
    here. Small companies increasingly file electronically, but the coverage
    gap is real and is reported as a percentage of the cohort.
  * Micro-entity accounts under FRS 105 need not disclose employee numbers and
    frequently omit creditors detail. Missing is recorded as NULL, never zero.
    Treating a missing creditors figure as zero debt would be a serious error
    in a study about which formats carry debt.
  * Turnover is not required in small-company filings and is usually absent.
    The study therefore analyses net assets and creditors, not revenue, and
    does not attempt margin analysis from public filings.
"""

from __future__ import annotations

import re
from typing import Any

from lxml import etree

# Local tag names to extract, mapped to the study's column names. Several
# aliases per concept because the taxonomy changed between FRS versions and
# filing software differs.
WANTED = {
    "net_assets": (
        "NetAssetsLiabilities",
        "NetAssetsLiabilitiesIncludingPensionAssetLiability",
        "NetCurrentAssetsLiabilities",  # fallback only; flagged separately below
    ),
    "equity": (
        "Equity",
        "ShareholderFunds",
        "CapitalAndReserves",
        "TotalShareholdersFunds",
    ),
    "creditors_within_one_year": (
        "CreditorsDueWithinOneYear",
        "Creditors",
        "CreditorsAmountsFallingDueWithinOneYear",
    ),
    "creditors_after_one_year": (
        "CreditorsDueAfterOneYear",
        "CreditorsAmountsFallingDueAfterMoreThanOneYear",
    ),
    "debtors": (
        "Debtors",
        "DebtorsDueWithinOneYear",
        "TradeDebtorsTradeReceivables",
    ),
    "share_capital": (
        "CalledUpShareCapital",
        "IssuedShareCapital",
        "CalledUpShareCapitalPaid",
        "EquityShareCapital",
    ),
    "cash": (
        "CashBankOnHand",
        "CashBankInHand",
        "CashCashEquivalents",
    ),
    "fixed_assets": ("FixedAssets", "TangibleFixedAssets"),
    "current_assets": ("CurrentAssets", "TotalCurrentAssets"),
    "employees": (
        "AverageNumberEmployeesDuringPeriod",
        "NumberOfEmployeesIncludingDirectorsDuringPeriod",
        "AverageNumberOfEmployeesDuringThePeriod",
    ),
    "turnover": ("TurnoverRevenue", "Turnover", "Revenue"),
}

# `NetCurrentAssetsLiabilities` is working capital, not net assets. It is kept
# as a last resort because some micro filings tag nothing else usable, but any
# figure sourced from it is marked so the analysis can exclude it.
WEAK_SOURCES = {"NetCurrentAssetsLiabilities"}

_LOCAL = {alias: field for field, aliases in WANTED.items() for alias in aliases}
_NUMBER_CLEAN = re.compile(r"[^\d.\-]")
_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _local_name(qname: str) -> str:
    """Strip a namespace prefix or Clark-notation URI from a tag or attribute.

    Filings are parsed with lxml's HTML parser rather than its XML parser,
    because a meaningful minority of Companies House iXBRL documents are not
    well-formed XML and the XML parser rejects them outright. The HTML parser
    keeps prefixed names as literal strings -- the tag is `ix:nonfraction`, not
    a namespaced QName -- and lowercases tag and attribute names, so matching
    is done on the lowercased local part throughout.
    """
    if not qname:
        return ""
    if "}" in qname:
        qname = qname.rsplit("}", 1)[-1]
    return qname.rsplit(":", 1)[-1]


def _tag(el) -> str:
    """The element's local tag name in lower case, or '' for comments."""
    tag = el.tag
    return _local_name(tag).lower() if isinstance(tag, str) else ""


def _to_number(text: str, scale: str | None, sign: str | None) -> float | None:
    raw = text or ""
    cleaned = _NUMBER_CLEAN.sub("", raw.replace(",", ""))
    if not cleaned or cleaned in {"-", ".", "-."}:
        return None
    try:
        value = float(cleaned)
    except ValueError:
        return None
    if scale:
        try:
            value *= 10 ** int(scale)
        except ValueError:
            pass
    if sign == "-":
        value = -value
    elif "(" in raw and ")" in raw and value > 0:
        # Accounts convention: brackets mean negative. Correctly-tagged
        # filings carry sign="-" as well, but a meaningful minority tag
        # "(48,215)" with no sign attribute, and the regex strips the
        # brackets -- so negative equity was being read as positive. In a
        # study of net assets that is not a rounding error.
        value = -value
    return value


def parse(content: bytes, company_number: str = "", filename: str = "") -> dict[str, Any]:
    """Extract the study's fields from one iXBRL accounts document.

    Returns a dict with the requested figures, the balance sheet date, and
    diagnostics: which tag supplied each figure, and how many facts were seen
    in total. Returns an empty dict only if the document cannot be parsed at
    all.
    """
    try:
        root = etree.fromstring(content, etree.HTMLParser(recover=True, huge_tree=True))
    except Exception:
        return {}
    if root is None:
        return {}

    # Contexts carry the dates. Build id -> date once.
    contexts: dict[str, str] = {}
    for el in root.iter():
        if _tag(el) != "context":
            continue
        ctx_id = el.get("id")
        if not ctx_id:
            continue
        text = " ".join(t for t in el.itertext())
        dates = _DATE.findall(text)
        if dates:
            year, month, day = dates[-1]  # the later of startDate/endDate
            contexts[ctx_id] = f"{year}-{month}-{day}"

    out: dict[str, Any] = {
        "company_number": company_number,
        "source_file": filename,
        "facts_seen": 0,
        "weak_net_assets": False,
    }
    sources: dict[str, str] = {}
    dates_seen: dict[str, str] = {}

    for el in root.iter():
        if _tag(el) != "nonfraction":
            continue
        out["facts_seen"] += 1

        name = el.get("name") or ""
        field = _LOCAL.get(_local_name(name))
        if not field:
            continue

        value = _to_number("".join(el.itertext()), el.get("scale"), el.get("sign"))
        if value is None:
            continue

        ctx = el.get("contextref") or el.get("contextRef")
        date = contexts.get(ctx or "", "")

        # Filings report the current year and the comparative. Keep the latest
        # date seen for each field so the figure is the current period.
        if field in out and date and dates_seen.get(field, "") > date:
            continue
        # A fact whose context resolves to no date must never displace one
        # that is properly dated -- otherwise document order decides.
        if field in out and not date and dates_seen.get(field):
            continue
        # Never let a weak fallback tag overwrite a proper one. Without this,
        # a document that tags both NetAssetsLiabilities and
        # NetCurrentAssetsLiabilities ends up reporting working capital as net
        # assets purely because of element order -- which is what happened on
        # the first full run, where 88% of parsed net-asset figures came from
        # the fallback.
        if (
            _local_name(name) in WEAK_SOURCES
            and sources.get(field)
            and sources[field] not in WEAK_SOURCES
        ):
            continue
        out[field] = value
        sources[field] = _local_name(name)
        if date:
            dates_seen[field] = date
        if field == "net_assets":
            # Track, and CLEAR when a strong tag replaces the weak one --
            # the flag used to be sticky, so figures later corrected by a
            # proper NetAssetsLiabilities tag stayed marked weak and were
            # excluded downstream for no reason.
            out["weak_net_assets"] = _local_name(name) in WEAK_SOURCES

    out["balance_sheet_date"] = max(dates_seen.values()) if dates_seen else (
        max(contexts.values()) if contexts else None
    )
    out["sources"] = sources
    return out


def date_from_filename(filename: str) -> str | None:
    """Companies House names members like Prod224_0050_00000452_20170430.html.

    The trailing date is the made-up-to date, and is more reliable than
    anything inside the document when a filing tags its contexts oddly.
    """
    m = re.search(r"_(\d{4})(\d{2})(\d{2})\.html?$", filename, re.I)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def company_from_filename(filename: str) -> str | None:
    """Extract the company number from a Companies House accounts filename."""
    m = re.search(r"_([0-9A-Z]{8})_\d{8}\.html?$", filename, re.I)
    return m.group(1).upper() if m else None

"""
Shared configuration for the Bricked-Up Windows data pipeline.

Every constant that shapes the cohort or the analysis lives here rather than
being buried in a script, so that a reader or peer reviewer can audit the
study's definitions in one place and re-run the pipeline with different
choices (a different SIC set, a different geography, different era
boundaries) to test how fragile the headline findings are.

Research question
-----------------
Does the VAT boundary between eat-in catering (standard-rated) and cold
takeaway food (largely zero-rated) show up in the observable life history of
London food businesses -- in who survives, who grows, who is born, and who
takes over the premises when a business dies?

Nothing here proves causation. The pipeline produces observational data about
company formation, survival, financial position and succession. The report
states associations and rival explanations, never causal claims.

Sources
-------
1. Companies House "Basic Company Data" monthly snapshot (free bulk CSV).
   Contains LIVE companies only. Verified empirically on 2026-08-16: a
   400,000-row sample of the 2026-03-02 snapshot contained zero populated
   DissolutionDate values and no "Dissolved" status. Dissolved companies must
   therefore be recovered from the REST API (see scripts/02_cohort_dissolved.py).
2. Companies House REST API (advanced search, company profile, filing history,
   charges). Officer and beneficial-ownership data is out of scope.
3. Companies House "Accounts Monthly Data" bulk product (iXBRL accounts).
4. postcodes.io (ONS Postcode Directory served as a free API) for the
   postcode-to-borough mapping.

Author's conflict of interest, declared in the published report: Roseworth
acts for businesses in this sector and has a commercial interest in the
subject matter.
"""

from __future__ import annotations

import datetime as _dt
import os
import pathlib

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

DATA_RAW = REPO_ROOT / "data" / "raw"
DATA_PROCESSED = REPO_ROOT / "data" / "processed"
SOURCES = REPO_ROOT / "sources"
OUT = REPO_ROOT / "out"

for _d in (DATA_RAW, DATA_PROCESSED, SOURCES, OUT):
    _d.mkdir(parents=True, exist_ok=True)

# The single analytical database. Every script reads and writes here, so the
# whole study is one file a reviewer can open with the DuckDB CLI.
DB_PATH = DATA_PROCESSED / "brickedup.duckdb"

# The Companies House bulk snapshot (BasicCompanyDataAsOneFile, ~2.8 GB,
# 5.5M rows). The study used the file published on 2026-03-02.
# Override with the CH_SNAPSHOT_CSV environment variable to use a newer one.
SNAPSHOT_CSV = pathlib.Path(
    os.environ.get(
        "CH_SNAPSHOT_CSV",
        str(REPO_ROOT / "data" / "raw" / "BasicCompanyDataAsOneFile-2026-03-02.csv"),
    )
)

# The date the snapshot describes. This is what the snapshot-derived fields
# (accounts_last_made_up, charges, the 'closing' status detail) are dated to,
# and the censoring date for the small set of companies seen ONLY in the
# snapshot. It is NOT the study's observation date -- see OBSERVATION_DATE.
SNAPSHOT_DATE = _dt.date(2026, 3, 2)

# The single right-censoring date for every survival calculation. This is the
# August 2026 register walk: statuses and cessation dates are observed to this
# date, so survivors are censored here and deaths are counted to here. The
# walk ran on 16 August 2026; the latest gazette-effective cessation date it
# returned is 18 August, so the window closes on the 18th.
#
# An earlier version censored survivors at SNAPSHOT_DATE while counting
# deaths observed by the register walk five months later -- events past every
# censoring time, wrong risk sets, every published survival level ~4-8pp off
# (audit finding B2). One window, applied everywhere, is the fix. Companies
# present only in the March snapshot (registered office moved away before
# August) are still censored at SNAPSHOT_DATE, because that is the last date
# they were genuinely observed alive.
OBSERVATION_DATE = _dt.date(2026, 8, 18)

# ---------------------------------------------------------------------------
# Cohort definition -- SIC codes
# ---------------------------------------------------------------------------
#
# The study splits food retail into two formats, because the VAT treatment
# splits the same way:
#
#   SERVICE formats sell catering. Everything consumed on the premises is
#   standard-rated for VAT regardless of what it is (VAT Notice 709/1).
#
#   COUNTER formats sell goods to take away. Cold takeaway food is largely
#   zero-rated (VAT Notice 701/14); hot takeaway food has been standard-rated
#   since the 2012 rules; hot drinks are standard-rated in all cases. A counter
#   therefore runs a BLENDED rate, not a zero rate. The report must never
#   claim "takeaway is zero-rated" without that distinction.
#
# SIC self-classification is imperfect and the report says so. A cafe with
# 80% takeaway trade may register as 56102; a takeaway with four tables may
# register as 56103. This is measurement error in the independent variable and
# it biases towards finding NO difference between the groups, so a difference
# that survives it is more, not less, credible.

SIC_SERVICE = {
    "56101": "Licensed restaurants",
    "56102": "Unlicensed restaurants and cafes",
}

SIC_COUNTER = {
    "56103": "Take-away food shops and mobile food stands",
    "47240": "Retail sale of bread, cakes, flour confectionery and sugar confectionery",
}

SIC_COHORT = {**SIC_SERVICE, **SIC_COUNTER}

# Excluded and why -- stated so the exclusion is auditable rather than silent.
SIC_EXCLUDED = {
    "56302": (
        "Public houses and bars. Excluded: a different economic animal "
        "(wet-led, tied leases, different tax base) and the study does not cover "
        "pubs. Caveat: gastropubs self-classify inconsistently and some "
        "register as 56101, so this exclusion is approximate."
    ),
    "56290": (
        "Other food services (contract catering). Excluded: business-to-"
        "business contract catering does not face the high-street counter/"
        "cover choice this study is about."
    ),
}


def sic_format(sic_code: str) -> str:
    """Return 'counter', 'service' or 'other' for a five-digit SIC code."""
    if sic_code in SIC_COUNTER:
        return "counter"
    if sic_code in SIC_SERVICE:
        return "service"
    return "other"


# ---------------------------------------------------------------------------
# Geography -- London
# ---------------------------------------------------------------------------
#
# Two filters, applied in sequence:
#
#   1. A cheap postcode-area prefix filter, run against 5.5M snapshot rows.
#      Deliberately generous: it admits postcode areas that straddle the
#      Greater London boundary (EN, KT, TW, WD, DA, BR, CR, RM) because it is
#      better to admit a Hertfordshire company and drop it later than to miss
#      a Barnet one.
#   2. An authoritative postcode-to-borough lookup (scripts/03_geography.py),
#      which resolves each surviving postcode to an ONS local authority and
#      drops anything outside the 32 boroughs plus the City of London.
#
# The published cohort count is the count after step 2.

LONDON_POSTCODE_AREAS = {
    # London postal district proper
    "E", "EC", "N", "NW", "SE", "SW", "W", "WC",
    # Outer areas that contain Greater London territory
    "BR",  # Bromley
    "CR",  # Croydon
    "DA",  # Bexley (part)
    "EN",  # Enfield (part -- also Hertfordshire)
    "HA",  # Harrow, Brent
    "IG",  # Redbridge, Barking and Dagenham
    "KT",  # Kingston, Richmond (part -- also Surrey)
    "RM",  # Havering, Barking and Dagenham
    "SM",  # Sutton, Merton
    "TW",  # Hounslow, Richmond (part -- also Surrey)
    "UB",  # Hillingdon, Ealing
    "WD",  # Harrow (part -- mostly Hertfordshire)
}

# ---------------------------------------------------------------------------
# Era definitions
# ---------------------------------------------------------------------------
#
# The study period runs from two years before the pandemic to the snapshot
# date, and is cut into four eras. Each boundary is a dated, citable public
# event rather than a convenient round number, so that the periodisation
# cannot be accused of being fitted to the result.
#
# The eras are NOT of equal length. Any comparison of counts between eras must
# be expressed as a rate per period-year, never as a raw count. Helper
# `era_length_years` below exists so no script forgets this.

STUDY_START = _dt.date(2018, 1, 1)
STUDY_END = OBSERVATION_DATE

ERAS: list[tuple[str, _dt.date, _dt.date, str]] = [
    (
        "pre_covid",
        _dt.date(2018, 1, 1),
        _dt.date(2020, 3, 22),
        "Two full years before the pandemic. Ends the day before the first "
        "national lockdown. The baseline against which everything after is "
        "measured.",
    ),
    (
        "covid",
        _dt.date(2020, 3, 23),
        _dt.date(2021, 7, 18),
        "First national lockdown (23 March 2020) to the day before Step 4 of "
        "the roadmap. Trading was legally restricted for much of this period "
        "and the state was paying wages (CJRS) and grants. Company survival "
        "in this era measures policy, not business model, and the report says "
        "so explicitly.",
    ),
    (
        "revival",
        _dt.date(2021, 7, 19),
        _dt.date(2022, 3, 31),
        "Step 4 of the roadmap ('Freedom Day', 19 July 2021) to the end of "
        "the 12.5% hospitality VAT rate. Restrictions gone, support winding "
        "down, inflation not yet acute.",
    ),
    (
        "cost_of_living",
        _dt.date(2022, 4, 1),
        OBSERVATION_DATE,
        "From 1 April 2022, when three things landed together: the Ofgem "
        "price cap rose 54%, and hospitality VAT returned to 20% from 12.5%. "
        "Later in the era: National Living Wage rises and the employer NI "
        "change from April 2025 (15% above a GBP 5,000 threshold).",
    ),
]

# The temporary reduced rate of VAT on hospitality is the single most
# important confounder in this study, and also its best natural experiment.
# During the reduced-rate window, the VAT gap between an eat-in cover and a
# cold takeaway item narrowed sharply, then snapped back. If the thesis is
# right, the counter/service divergence should be MUTED while the rate is
# reduced and WIDEN after 1 April 2022. That is a falsifiable prediction the
# report commits to testing.
#
# Source: Finance Act 2020 s.102 and subsequent extensions; HMRC guidance on
# the temporary reduced rate for hospitality, holiday accommodation and
# attractions. Verify against primary sources before publication.
VAT_HOSPITALITY_RATE_PERIODS = [
    (_dt.date(2018, 1, 1), _dt.date(2020, 7, 14), 0.20, "Standard rate"),
    (_dt.date(2020, 7, 15), _dt.date(2021, 9, 30), 0.05, "Temporary reduced rate"),
    (_dt.date(2021, 10, 1), _dt.date(2022, 3, 31), 0.125, "Tapered reduced rate"),
    (_dt.date(2022, 4, 1), OBSERVATION_DATE, 0.20, "Standard rate restored"),
]


def era_of(d: _dt.date | None) -> str | None:
    """Return the era name containing date `d`, or None if outside the study."""
    if d is None:
        return None
    for name, start, end, _ in ERAS:
        if start <= d <= end:
            return name
    return None


def era_length_years(name: str) -> float:
    """Length of an era in years. Use to convert counts into annual rates."""
    for era_name, start, end, _ in ERAS:
        if era_name == name:
            return (end - start).days / 365.25
    raise KeyError(name)


# ---------------------------------------------------------------------------
# Company status labels
# ---------------------------------------------------------------------------
#
# Companies House uses many status strings. The study collapses them into four
# analytical outcomes. The mapping is explicit because the choice matters: a
# company in liquidation has failed in every economic sense but is still "live"
# on the register, and counting it as a survivor would understate failure.

STATUS_GROUPS = {
    "alive": [
        "Active",
        "Live but Receiver Manager on at least one charge",
    ],
    "failing": [
        # Still on the register, but the outcome is effectively determined.
        "Liquidation",
        "In Administration",
        "In Administration/Administrative Receiver",
        "In Administration/Receiver Manager",
        "ADMINISTRATION ORDER",
        "ADMINISTRATIVE RECEIVER",
        "RECEIVERSHIP",
        "RECEIVER MANAGER / ADMINISTRATIVE RECEIVER",
        "Voluntary Arrangement",
        "VOLUNTARY ARRANGEMENT / RECEIVER MANAGER",
    ],
    "closing": [
        # Struck-off proceedings started, usually a dormant or abandoned company.
        "Active - Proposal to Strike off",
        "Proposal to Strike off",
    ],
    "dead": [
        "Dissolved",
        "Removed",
        "Converted / Closed",
    ],
}

_STATUS_LOOKUP = {
    s.strip().lower(): group for group, values in STATUS_GROUPS.items() for s in values
}


def status_group(raw_status: str | None) -> str:
    """Collapse a Companies House status string into one of four outcomes."""
    if not raw_status:
        return "unknown"
    return _STATUS_LOOKUP.get(raw_status.strip().lower(), "unknown")


# ---------------------------------------------------------------------------
# Companies House REST API
# ---------------------------------------------------------------------------

CH_API_BASE = "https://api.company-information.service.gov.uk"
CH_DOC_API_BASE = "https://document-api.company-information.service.gov.uk"

# Published limit: 600 requests per five minutes = 2.0 requests/second.
#
# 1.8/s (540 per five minutes) was tried and ran cleanly for two hours and
# 12,500 requests before Companies House began returning sustained 429s. The
# published limit is evidently not the only throttle in play over a long run,
# so the sustained rate is set lower. A batch job that finishes in nine hours
# instead of seven is a far better outcome than one that dies at hour two.
CH_RATE_LIMIT_PER_SECOND = 1.4

# The key lives in .env at the repository root, which is gitignored. It is
# never printed, logged or committed.
ENV_FILE = REPO_ROOT / ".env"


def companies_house_key() -> str:
    """Read the Companies House API key from .env. Never log the return value."""
    if not ENV_FILE.exists():
        raise RuntimeError(
            f"{ENV_FILE} not found. Create it with a single line:\n"
            "COMPANIES_HOUSE_API_KEY=<your key>"
        )
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("COMPANIES_HOUSE_API_KEY="):
            return line.split("=", 1)[1].strip().strip("\"'")
    raise RuntimeError("COMPANIES_HOUSE_API_KEY not present in .env")


# ---------------------------------------------------------------------------
# Analytical floors
# ---------------------------------------------------------------------------
#
# Reporting floors. These applied to a client-data overlay that was dropped,
# which never enters this repository, but the same discipline is applied to
# public-data cells so that no chart implies precision the sample cannot carry.

MIN_CELL_SIZE = 10  # Do not publish any figure derived from fewer than this.

# Percentage growth flatters whatever started smallest, and counter formats
# start smallest. Report medians and quartiles, never means. Exclude the first
# two trading years, where growth from a near-zero base is meaningless.
MIN_TRADING_YEARS_FOR_GROWTH = 2


# Identifies the pipeline to the public APIs it calls. Set CH_USER_AGENT to
# your own name and contact address before running.
USER_AGENT = os.environ.get(
    "CH_USER_AGENT", "london-food-register-study/1.0 (set CH_USER_AGENT)")

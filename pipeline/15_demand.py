"""
Step 15 -- the demand side: did the customer stop commuting, and where did they go?

The report's original synthesis was that behaviour moved the demand and tax
decided the shape of the supply response. The company data has already
complicated that: the shift in what people incorporate is dated to the first
lockdown, not to any VAT change. This step brings the other half of the
evidence so the demand chapter can be written honestly rather than assumed.

Two sources, both free and official.

**TfL journeys by transport type.** One row per TfL reporting period (thirteen
a year) from April 2010 to May 2026, covering bus, Underground, DLR, tram,
Overground, Elizabeth line and cable car. Published via the London Datastore.
This gives the shape of the collapse and the shape of whatever recovery there
has been, on a consistent basis over sixteen years.

**TfL annual station counts.** Entry and exit totals for every station, 2017 to
2025, published on TfL's open data bucket. This is the part that matters for
this study, because it is measured *per station* -- so the City and West End
can be compared against the outer suburbs directly, rather than inferred from a
network total.

The naming of the station files changed twice over the period, which is why
they cannot simply be guessed:

    2017-2019   AnnualisedEntryExit_YYYY.xlsx
    2020-2023   ACYYYY_AnnualisedEntryExit.xlsx
    2024        AC2024_AnnualisedEntryExit_Public.xlsx
    2025        AC2025_AnnualisedEntryExit_public.xlsx

A caution TfL itself gives and the report must repeat: the annual figures are
derived from typical autumn week surveys scaled by revenue data, and **the 2020
figures were collected during the second national lockdown**. They are not
comparable with any other year and are reported but never used as a baseline.
"""

from __future__ import annotations

import sys
import urllib.parse
import urllib.request

import pandas as pd

import config
from ch_api import setup_logging

log = setup_logging("15_demand")

OUT_DIR = config.SOURCES / "demand"
OUT_DIR.mkdir(parents=True, exist_ok=True)

JOURNEYS_CSV = (
    "https://data.london.gov.uk/download/ep8ow/"
    "06a805f6-77c6-481a-8b08-ddef56afffdd/tfl-journeys-type.csv"
)

STATION_FILES = {
    2017: "Annual Station Counts/2017/AnnualisedEntryExit_2017.xlsx",
    2018: "Annual Station Counts/2018/AnnualisedEntryExit_2018.xlsx",
    2019: "Annual Station Counts/2019/AnnualisedEntryExit_2019.xlsx",
    2020: "Annual Station Counts/2020/AC2020_AnnualisedEntryExit.xlsx",
    2021: "Annual Station Counts/2021/AC2021_AnnualisedEntryExit.xlsx",
    2022: "Annual Station Counts/2022/AC2022_AnnualisedEntryExit.xlsx",
    2023: "Annual Station Counts/2023/AC2023_AnnualisedEntryExit.xlsx",
    2024: "Annual Station Counts/2024/AC2024_AnnualisedEntryExit_Public.xlsx",
    2025: "Annual Station Counts/2025/AC2025_AnnualisedEntryExit_public.xlsx",
}
STATION_BASE = "https://crowding.data.tfl.gov.uk/"

UA = {"User-Agent": config.USER_AGENT}


def download(url: str, dest) -> bool:
    if dest.exists():
        log.info("  %s already held", dest.name)
        return True
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=120) as r:
            dest.write_bytes(r.read())
    except Exception as e:
        log.warning("  could not fetch %s: %s", dest.name, e)
        return False
    log.info("  downloaded %-44s %6.0f KB", dest.name, dest.stat().st_size / 1e3)
    return True


def fetch_all() -> None:
    log.info("Downloading TfL sources to %s", OUT_DIR)
    download(JOURNEYS_CSV, OUT_DIR / "tfl-journeys-type.csv")
    for year, key in STATION_FILES.items():
        download(STATION_BASE + urllib.parse.quote(key),
                 OUT_DIR / f"tfl-station-counts-{year}.xlsx")


def analyse_journeys() -> None:
    path = OUT_DIR / "tfl-journeys-type.csv"
    if not path.exists():
        return
    frame = pd.read_csv(path)
    frame.columns = [c.strip() for c in frame.columns]
    frame["period_end"] = pd.to_datetime(frame["Period ending"], format="%d-%b-%y",
                                         errors="coerce")
    frame = frame.dropna(subset=["period_end"])

    # Normalise for period length: periods 1 and 13 are longer than the rest,
    # so raw period totals are not comparable without this.
    days = pd.to_numeric(frame["Days in period"], errors="coerce")
    for column in ("Bus journeys (m)", "Underground journeys (m)"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame[column + " per day"] = frame[column] / days

    baseline = frame[
        (frame.period_end >= "2019-04-01") & (frame.period_end < "2020-03-01")
    ]
    base_tube = baseline["Underground journeys (m) per day"].mean()
    base_bus = baseline["Bus journeys (m) per day"].mean()

    log.info("")
    log.info("TfL journeys per day, indexed to the 2019/20 financial year (=100)")
    log.info("  %-14s %10s %10s", "period ending", "Underground", "Bus")
    marks = ["2020-03", "2020-06", "2020-12", "2021-07", "2022-04",
             "2023-04", "2024-04", "2025-04", "2026-05"]
    for mark in marks:
        row = frame[frame.period_end.dt.strftime("%Y-%m") == mark]
        if row.empty:
            continue
        r = row.iloc[0]
        log.info("  %-14s %9.0f %10.0f", r.period_end.date(),
                 100 * r["Underground journeys (m) per day"] / base_tube,
                 100 * r["Bus journeys (m) per day"] / base_bus)

    latest = frame.sort_values("period_end").iloc[-1]
    log.info("")
    log.info("  Latest period (%s): Underground at %.0f%% of pre-pandemic, "
             "bus at %.0f%%",
             latest.period_end.date(),
             100 * latest["Underground journeys (m) per day"] / base_tube,
             100 * latest["Bus journeys (m) per day"] / base_bus)

    frame.to_csv(config.OUT / "tfl_journeys_indexed.csv", index=False)


# The classification the report turns on. "City" is the financial district --
# the lunch economy the brief expects to have lost most. "West End" is the
# retail and office core around Oxford Street, Soho and Victoria. "Inner" is
# the rest of Zone 1 and the immediate ring. Everything else is "Outer", which
# is home to many small food businesses.
#
# This is a judgement about geography, applied by name, and it is listed in
# full so a reader can disagree with a specific station rather than with a
# black box.
CITY_STATIONS = {
    "Bank and Monument", "Liverpool Street", "Moorgate", "Cannon Street",
    "Mansion House", "St Paul's", "Aldgate", "Aldgate East", "Barbican",
    "Farringdon", "Blackfriars", "Tower Hill", "Temple", "Chancery Lane",
    "Old Street", "Fenchurch Street",
}
WEST_END_STATIONS = {
    "Oxford Circus", "Bond Street", "Tottenham Court Road", "Piccadilly Circus",
    "Leicester Square", "Covent Garden", "Green Park", "Holborn",
    "Goodge Street", "Warren Street", "Regent's Park", "Marble Arch",
    "Charing Cross", "Embankment", "Victoria", "Westminster", "St James's Park",
    "Baker Street", "Great Portland Street", "Euston Square", "Russell Square",
    "Oxford Circus LU", "Hyde Park Corner", "Knightsbridge", "Sloane Square",
}
INNER_STATIONS = {
    "King's Cross St. Pancras", "Paddington", "Waterloo", "London Bridge",
    "Euston", "Marylebone", "Angel", "Camden Town", "Highbury & Islington",
    "Canary Wharf", "Vauxhall", "Elephant & Castle", "Borough", "Southwark",
    "Lambeth North", "Pimlico", "Gloucester Road", "South Kensington",
    "Earl's Court", "Notting Hill Gate", "Bayswater", "Lancaster Gate",
    "Edgware Road", "Shoreditch High Street", "Bethnal Green", "Whitechapel",
}


def classify_station(name: str) -> str:
    if name in CITY_STATIONS:
        return "City"
    if name in WEST_END_STATIONS:
        return "West End"
    if name in INNER_STATIONS:
        return "Inner"
    return "Outer"


def load_station_year(year: int) -> pd.DataFrame | None:
    """Read one annual station count file into a common shape."""
    path = OUT_DIR / f"tfl-station-counts-{year}.xlsx"
    if not path.exists():
        return None
    try:
        sheets = pd.read_excel(path, sheet_name=None)
    except Exception as e:
        log.warning("  %s unreadable: %s", path.name, e)
        return None

    # These are presentation spreadsheets, not data files. Every vintage has a
    # different sheet name, several rows of title and copyright above the
    # table, and a header split across two or three rows so that "Typical /
    # Weekday (Mon-Thu) / entries" reads correctly to a human eye and not at
    # all to pandas. The one thing that is stable across all nine years is the
    # layout: a cell containing exactly "Station", and a column whose stacked
    # header includes "Annualised".
    for name, sheet in sheets.items():
        header_row = station_col = None
        for row in range(min(12, len(sheet))):
            for col in range(sheet.shape[1]):
                if str(sheet.iat[row, col]).strip().lower() == "station":
                    header_row, station_col = row, col
                    break
            if header_row is not None:
                break
        if header_row is None:
            continue

        # Find the annualised column by reading the whole stacked header.
        annual_col = None
        for col in range(sheet.shape[1]):
            stack = " ".join(
                str(sheet.iat[r, col])
                for r in range(max(0, header_row - 3), min(header_row + 3, len(sheet)))
            ).lower()
            if "annualis" in stack:
                annual_col = col
        if annual_col is None:
            continue

        body = sheet.iloc[header_row + 1:]
        # Mode matters enormously. The Elizabeth line opened in 2022 and turned
        # a string of minor National Rail halts into major stops, so an
        # unfiltered 2019-to-2025 comparison ranks Acton Main Line as London's
        # fastest-growing location. That is a fact about new infrastructure,
        # not about where people now eat lunch.
        out = pd.DataFrame({
            "year": year,
            "mode": body.iloc[:, 0].astype(str).str.strip().str.upper(),
            "station": body.iloc[:, station_col].astype(str).str.strip(),
            "footfall_annual": pd.to_numeric(body.iloc[:, annual_col], errors="coerce"),
        })
        out = out[
            out.station.notna()
            & (out.station != "nan")
            & (out.station != "")
            & out.footfall_annual.notna()
        ]
        if out.empty:
            continue
        out["sheet"] = name
        log.info("  %d: %4d stations from sheet '%s'", year, len(out), name)
        return out

    log.warning("  %s: no sheet matched the expected shape (sheets: %s)",
                path.name, list(sheets)[:6])
    return None


def analyse_stations() -> None:
    frames = [f for f in (load_station_year(y) for y in STATION_FILES) if f is not None]
    if not frames:
        log.warning("No station files could be parsed.")
        return
    stations = pd.concat(frames, ignore_index=True)
    stations["footfall"] = stations["footfall_annual"]
    stations.to_csv(config.OUT / "tfl_station_footfall.csv", index=False)

    log.info("")
    log.info("Station counts parsed: %s rows across %s years",
             f"{len(stations):,}", stations.year.nunique())
    for year, n in stations.groupby("year").station.nunique().items():
        log.info("  %d  %4d stations", year, n)

    # 2019 is the last clean pre-pandemic year. 2020 was surveyed during the
    # second national lockdown and is never used as a baseline.
    tube = stations[stations["mode"] == "LU"]
    wide = tube.pivot_table(index="station", columns="year",
                            values="footfall", aggfunc="sum")
    latest = max(y for y in wide.columns if y >= 2024)
    if 2019 not in wide.columns:
        return
    usable = wide[[2019, latest]].dropna()
    usable = usable[usable[2019] > 0]
    usable["recovery"] = usable[latest] / usable[2019]
    usable["group"] = [classify_station(s) for s in usable.index]
    usable.sort_values("recovery").to_csv(config.OUT / "tfl_station_recovery.csv")

    log.info("")
    log.info("Underground stations only (Elizabeth line and Overground excluded, "
             "because new lines are not returning customers)")
    log.info("Footfall recovery, %d against 2019, %d stations", latest, len(usable))
    log.info("  all Underground: %.0f%% of 2019",
             100 * usable[latest].sum() / usable[2019].sum())

    log.info("")
    log.info("  By location -- the question the report actually needs answered:")
    for group in ("City", "West End", "Inner", "Outer"):
        sub = usable[usable.group == group]
        if sub.empty:
            continue
        log.info("    %-10s %5.0f%% of 2019   (%2d stations, %5.0fm -> %5.0fm journeys)",
                 group, 100 * sub[latest].sum() / sub[2019].sum(), len(sub),
                 sub[2019].sum() / 1e6, sub[latest].sum() / 1e6)

    log.info("")
    log.info("  Weakest 10 Underground stations:")
    for station, r in usable.sort_values("recovery").head(10).iterrows():
        log.info("    %-34s %5.0f%%  %-9s (%.1fm -> %.1fm)",
                 station[:34], 100 * r.recovery, r.group, r[2019] / 1e6, r[latest] / 1e6)
    log.info("")
    log.info("  Strongest 10 Underground stations:")
    for station, r in usable.sort_values("recovery").tail(10).iterrows():
        log.info("    %-34s %5.0f%%  %-9s (%.1fm -> %.1fm)",
                 station[:34], 100 * r.recovery, r.group, r[2019] / 1e6, r[latest] / 1e6)


def main() -> int:
    fetch_all()
    analyse_journeys()
    analyse_stations()
    log.info("")
    log.info("CSV outputs written to %s", config.OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())

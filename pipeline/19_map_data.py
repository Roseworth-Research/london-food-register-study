"""
Step 19 -- borough-level metrics and geometry for the map.

Produces one self-contained JSON holding both the borough boundaries and every
metric the map can colour by, so the visualisation has no external
dependencies and can be published as a single file.

Boundaries: ONS Open Geography Portal, Local Authority Districts, ultra-
generalised and clipped to the coastline (BUC). Small enough to inline.

Metrics, per borough:

  formation      companies incorporated, by year and by format
  presence       companies currently on the register
  exits          dissolutions, split by route
  insolvency     the rate that actually involves creditors
  abandonment    exits that never filed accounts -- the "unfinished dreams"
  persistence    median years on the register, and three-year survival
  premises       FSA food establishments matched, and companies per premises
  growth         median year-on-year change in reported equity

Every rate carries its denominator, because a rate without one is not a
finding. Boroughs with fewer than the reporting floor of companies in any cell
return null for that cell rather than a misleading number.
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request

import pandas as pd

import config
import db
from ch_api import setup_logging

log = setup_logging("19_map_data")

ONS = ("https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/"
       "Local_Authority_Districts_December_2023_Boundaries_UK_BUC/FeatureServer/0/query")

LONDON_BOROUGHS = [
    "Barking and Dagenham", "Barnet", "Bexley", "Brent", "Bromley", "Camden",
    "City of London", "Croydon", "Ealing", "Enfield", "Greenwich", "Hackney",
    "Hammersmith and Fulham", "Haringey", "Harrow", "Havering", "Hillingdon",
    "Hounslow", "Islington", "Kensington and Chelsea", "Kingston upon Thames",
    "Lambeth", "Lewisham", "Merton", "Newham", "Redbridge",
    "Richmond upon Thames", "Southwark", "Sutton", "Tower Hamlets",
    "Waltham Forest", "Wandsworth", "Westminster",
]

INSOLVENT = ("compulsory_liquidation", "creditors_voluntary_liquidation",
             "administration", "insolvency_other")


def fetch_geometry() -> dict:
    cache = config.DATA_RAW / "london_boroughs.geojson"
    if cache.exists():
        log.info("Using cached borough geometry")
        return json.loads(cache.read_text(encoding="utf-8"))

    names = ",".join(f"'{b}'" for b in LONDON_BOROUGHS)
    params = {
        "where": f"LAD23NM IN ({names})",
        "outFields": "LAD23NM",
        "outSR": "4326",
        "f": "geojson",
    }
    url = ONS + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT})
    with urllib.request.urlopen(req, timeout=180) as r:
        geo = json.load(r)
    cache.write_text(json.dumps(geo), encoding="utf-8")
    log.info("Fetched %d borough boundaries (%.0f KB)",
             len(geo.get("features", [])), cache.stat().st_size / 1024)
    return geo


def main() -> int:
    geo = fetch_geometry()
    con = db.connect(read_only=True, wait_seconds=600)

    has = lambda t: bool(con.execute(  # noqa: E731
        "SELECT count(*) FROM information_schema.tables WHERE table_name=?", [t]
    ).fetchone()[0])
    have_exits = has("company_exit_v2")
    have_footprint = has("filing_footprint")
    have_fsa = has("fsa_establishments")
    log.info("Optional tables -- exits:%s footprint:%s fsa:%s",
             have_exits, have_footprint, have_fsa)

    ins_clause = (
        f"sum(CASE WHEN e.exit_route IN {INSOLVENT} THEN 1 ELSE 0 END)"
        if have_exits else "NULL"
    )
    join_exits = ("LEFT JOIN company_exit_v2 e USING (company_number)"
                  if have_exits else "")
    never_clause = (
        "sum(CASE WHEN f.n_accounts = 0 THEN 1 ELSE 0 END)"
        if have_footprint else "NULL"
    )
    join_footprint = ("LEFT JOIN filing_footprint f USING (company_number)"
                      if have_footprint else "")

    core = con.execute(f"""
        SELECT t.best_borough AS borough,
               count(*)                                              AS companies,
               sum(CASE WHEN c.outcome = 'alive' THEN 1 ELSE 0 END)  AS active,
               sum(CASE WHEN c.outcome = 'dead' THEN 1 ELSE 0 END)   AS dissolved,
               sum(CASE WHEN c.format = 'counter' THEN 1 ELSE 0 END) AS counter,
               sum(CASE WHEN c.format = 'service' THEN 1 ELSE 0 END) AS service,
               sum(CASE WHEN c.at_hub THEN 1 ELSE 0 END)             AS at_agent,
               median(c.lifespan_years)                              AS median_years,
               {ins_clause}                                          AS insolvent,
               {never_clause}                                        AS never_filed,
               sum(CASE WHEN year(c.born) BETWEEN 2022 AND 2025 THEN 1 ELSE 0 END) AS opened_recent,
               sum(CASE WHEN year(c.died) BETWEEN 2022 AND 2025 THEN 1 ELSE 0 END) AS closed_recent,
               sum(CASE WHEN t.tier = 'A_premises_confirmed' THEN 1 ELSE 0 END) AS premises_confirmed
        FROM companies c
        JOIN company_tier t USING (company_number)
        {join_exits} {join_footprint}
        WHERE t.best_borough IN (SELECT unnest($1::VARCHAR[]))
          -- Geography uses the TRADING address, not today's registered office.
          -- 72% of companies with an address history sit somewhere different
          -- now, and 87.8% of those that reached insolvency do, because
          -- liquidation moves the registered office to the practitioner.
          -- Tier C (best-known address is a mass-registration address) is
          -- excluded: its borough is the agent's, not the business's.
          AND t.tier <> 'C_unlocated'
        GROUP BY 1 ORDER BY 1
    """, [LONDON_BOROUGHS]).fetch_df()

    by_year = con.execute("""
        SELECT t.best_borough AS borough, year(c.born) AS year, c.format, count(*) AS n
        FROM companies c JOIN company_tier t USING (company_number)
        WHERE t.best_borough IN (SELECT unnest($1::VARCHAR[]))
          AND t.tier <> 'C_unlocated' AND year(c.born) BETWEEN 2018 AND 2025
        GROUP BY 1,2,3
    """, [LONDON_BOROUGHS]).fetch_df()

    premises = pd.DataFrame()
    if have_fsa:
        premises = con.execute("""
            SELECT t.best_borough AS borough,
                   count(DISTINCT p.fhrsid) AS premises,
                   count(DISTINCT p.company_number) AS matched
            FROM company_tier t LEFT JOIN company_premises p USING (company_number)
            WHERE t.best_borough IS NOT NULL AND t.tier <> 'C_unlocated'
            GROUP BY 1
        """).fetch_df()

    growth = pd.DataFrame()
    if has("accounts"):
        growth = con.execute(f"""
            WITH pairs AS (
                SELECT c.borough, a.company_number, a.financial_year,
                       COALESCE(a.equity, CASE WHEN NOT a.weak_net_assets
                                               THEN a.net_assets END) AS eq,
                       lag(COALESCE(a.equity, CASE WHEN NOT a.weak_net_assets
                                                   THEN a.net_assets END))
                         OVER (PARTITION BY a.company_number ORDER BY a.financial_year) AS prev_eq,
                       lag(a.financial_year)
                         OVER (PARTITION BY a.company_number ORDER BY a.financial_year) AS prev_year
                FROM accounts a JOIN companies c USING (company_number)
                WHERE c.borough IS NOT NULL
                  AND a.financial_year BETWEEN 2018 AND {config.STUDY_END.year}
            )
            SELECT borough,
                   median((eq - prev_eq) / prev_eq) AS median_growth,
                   count(*) AS n_pairs
            FROM pairs
            WHERE prev_eq > 1000 AND financial_year = prev_year + 1
            GROUP BY 1
        """).fetch_df()
    con.close()

    boroughs = {}
    for _, r in core.iterrows():
        b = r.borough
        years = by_year[by_year.borough == b]
        series = {}
        for year in range(2018, 2026):
            row = years[years.year == year]
            series[str(year)] = {
                "counter": int(row[row.format == "counter"].n.sum()),
                "service": int(row[row.format == "service"].n.sum()),
            }
        entry = {
            "companies": int(r.companies),
            "premises_confirmed": int(r.premises_confirmed),
            "active": int(r.active),
            "dissolved": int(r.dissolved),
            "counter": int(r.counter),
            "service": int(r.service),
            "at_agent": int(r.at_agent),
            "median_years": round(float(r.median_years), 2) if pd.notna(r.median_years) else None,
            "opened_recent": int(r.opened_recent),
            "closed_recent": int(r.closed_recent),
            "by_year": series,
        }
        entry["counter_share"] = round(entry["counter"] / max(entry["companies"], 1), 4)
        entry["dissolved_rate"] = round(entry["dissolved"] / max(entry["companies"], 1), 4)
        entry["agent_share"] = round(entry["at_agent"] / max(entry["companies"], 1), 4)
        entry["net_churn"] = entry["opened_recent"] - entry["closed_recent"]
        entry["open_close_ratio"] = round(
            entry["opened_recent"] / max(entry["closed_recent"], 1), 3)

        if pd.notna(r.insolvent):
            entry["insolvent"] = int(r.insolvent)
            entry["insolvency_rate"] = round(int(r.insolvent) / max(entry["companies"], 1), 5)
        if pd.notna(r.never_filed):
            entry["never_filed"] = int(r.never_filed)
            entry["never_filed_rate"] = round(
                int(r.never_filed) / max(entry["dissolved"], 1), 4)

        if not premises.empty:
            p = premises[premises.borough == b]
            if not p.empty:
                entry["premises"] = int(p.premises.iloc[0])
                entry["matched_companies"] = int(p.matched.iloc[0])
                entry["companies_per_premises"] = round(
                    int(p.matched.iloc[0]) / max(int(p.premises.iloc[0]), 1), 2)

        if not growth.empty:
            g = growth[growth.borough == b]
            if not g.empty and int(g.n_pairs.iloc[0]) >= config.MIN_CELL_SIZE:
                entry["median_growth"] = round(float(g.median_growth.iloc[0]), 4)
                entry["growth_pairs"] = int(g.n_pairs.iloc[0])

        boroughs[b] = entry

    payload = {
        "meta": {
            "cohort": int(core.companies.sum()),
            "snapshot_date": str(config.SNAPSHOT_DATE),
            "boroughs": len(boroughs),
            "note": "Companies on the register with a London registered office and one of four food SIC codes, EXCLUDING those registered at mass-registration addresses (accountants, formation agents, insolvency practitioners). A company is not a business; a registered office is not a trading premises.",
            "excluded_hub_note": "Insolvency runs at 1.74% at ordinary addresses and 9.61% at agent addresses, because a company entering liquidation has its registered office moved to the practitioner. Borough metrics are computed on ordinary addresses only.",
        },
        "boroughs": boroughs,
        "geometry": geo,
    }
    out = config.OUT / "london_map_data.json"
    out.write_text(json.dumps(payload), encoding="utf-8")
    log.info("Written %s (%.0f KB)", out, out.stat().st_size / 1024)

    log.info("")
    log.info("%-24s %8s %8s %7s %8s %9s", "borough", "companies", "active",
             "counter", "open/close", "med yrs")
    for b, e in sorted(boroughs.items(), key=lambda kv: -kv[1]["companies"])[:12]:
        log.info("%-24s %8s %8s %6.0f%% %8.2f %9.1f", b[:24],
                 f"{e['companies']:,}", f"{e['active']:,}",
                 100 * e["counter_share"], e["open_close_ratio"],
                 e["median_years"] or 0)
    return 0


if __name__ == "__main__":
    sys.exit(main())

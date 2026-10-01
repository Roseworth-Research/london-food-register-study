"""
Step 18 -- match companies to real food premises, using Food Standards Agency data.

Why this is the most important step in the study
------------------------------------------------
Everything before this analyses the **companies register**, which cannot see
whether a shop exists. Three separate weaknesses all trace to that one gap:

  * the format classification is a SIC code the company chose for itself, and
    the chains prove how unreliable that is -- Costa files as a licensed
    restaurant, Pret as a shop;
  * a registered office may be an accountant, a home or a formation agent, so
    "what opened at the same address" is not safely answerable;
  * an incorporation is not an opening and a dissolution is not a closure.

The Food Standards Agency fixes all three at once, and it is free.

Every business in the UK that sells food to the public must be registered with
its local authority and is inspected. The FSA publishes the resulting register:
business name, **regulator-assigned business type**, and full address of the
**premises** -- not a registered office.

That gives three things the company register cannot:

  1. **An independent classification.** `BusinessType` is assigned by an
     environmental health officer who has been inside the building. It is the
     external validation the format ranking has been missing.
  2. **Real premises.** Addresses are where food is actually made and sold.
  3. **Evidence of trading.** A food hygiene rating cannot be held without
     operating. Matching a company to an FSA establishment is the strongest
     available evidence that it was a real business rather than paperwork.

And it makes the study's best remaining question askable: **do the companies
behind food premises turn over faster than the premises themselves?**

Method
------
Pull every establishment in the 33 London local authorities, normalise the
premises address with the same key used for companies, and join. Matching is
address-first, with business-name similarity as a secondary check, and it is
deliberately conservative: a missed match understates linkage, which is the
safe direction. The unmatched rate is reported rather than hidden, and a manual
validation sample is required before any figure derived from this goes to print.

Source: Food Standards Agency, api.ratings.food.gov.uk, API version 2. Open
data under the Open Government Licence.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import pandas as pd

import addresses
import config
import db
from ch_api import setup_logging

log = setup_logging("18_fsa_premises")

API = "https://api.ratings.food.gov.uk"
HEADERS = {
    "x-api-version": "2",
    "Accept": "application/json",
    "User-Agent": config.USER_AGENT,
}
CACHE = config.DATA_RAW / "fsa"
CACHE.mkdir(parents=True, exist_ok=True)

# The 33 London local authorities, as the FSA names them. Matched against the
# authority list returned by the API rather than hardcoded IDs, because IDs
# change when authorities are reorganised.
LONDON_AUTHORITIES = {
    "barking and dagenham", "barnet", "bexley", "brent", "bromley", "camden",
    "city of london", "croydon", "ealing", "enfield", "greenwich", "hackney",
    "hammersmith and fulham", "haringey", "harrow", "havering", "hillingdon",
    "hounslow", "islington", "kensington and chelsea", "kingston upon thames",
    "lambeth", "lewisham", "merton", "newham", "redbridge",
    "richmond upon thames", "southwark", "sutton", "tower hamlets",
    "waltham forest", "wandsworth", "westminster",
}

# FSA business types that correspond to this study's cohort. The FSA scheme is
# coarser than SIC but has the decisive advantage of being assigned by someone
# who visited the premises.
FOOD_TYPES = {
    "Restaurant/Cafe/Canteen",
    "Takeaway/sandwich shop",
    "Retailers - other",
    "Pub/bar/nightclub",
    "Mobile caterer",
    "Other catering premises",
    "Manufacturers/packers",
    "Hospitals/Childcare/Caring Premises",
    "School/college/university",
    "Importers/Exporters",
    "Distributors/Transporters",
    "Farmers/growers",
    "Retailers - supermarkets/hypermarkets",
}

# The comparison that matters: how the regulator classifies a premises, against
# how the company classified itself.
COUNTER_TYPES = {"Takeaway/sandwich shop", "Retailers - other",
                 "Retailers - supermarkets/hypermarkets", "Mobile caterer"}
SERVICE_TYPES = {"Restaurant/Cafe/Canteen", "Pub/bar/nightclub",
                 "Other catering premises"}


def get(path: str, params: dict | None = None, retries: int = 4) -> dict | None:
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    delay = 2.0
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(delay); delay *= 2
        except Exception:
            time.sleep(delay); delay *= 2
    log.warning("  gave up on %s", path)
    return None


def london_authorities() -> list[dict]:
    data = get("/Authorities/basic")
    if not data:
        return []
    out = []
    for a in data.get("authorities", []):
        name = (a.get("Name") or "").strip().lower()
        # FSA names some authorities "London Borough of X" or "X Council".
        # FSA authority names vary: "London Borough of X", "X Council",
        # "City of London Corporation", and hyphenated forms like
        # "Kingston-upon-Thames". Normalise all of them or three boroughs go
        # missing, which is what happened on the first run.
        cleaned = (name.replace("london borough of ", "")
                       .replace("royal borough of ", "")
                       .replace(" corporation", "")
                       .replace(" council", "")
                       .replace("city of westminster", "westminster")
                       .replace("-", " ")
                       .strip())
        if cleaned in LONDON_AUTHORITIES or name in LONDON_AUTHORITIES:
            out.append({"id": a.get("LocalAuthorityId"), "name": a.get("Name")})
    return out


def fetch_authority(auth: dict) -> pd.DataFrame:
    cache_file = CACHE / f"authority_{auth['id']}.json"
    if cache_file.exists():
        records = json.loads(cache_file.read_text(encoding="utf-8"))
    else:
        records = []
        page = 1
        while True:
            data = get("/Establishments", {
                "localAuthorityId": auth["id"], "pageSize": 5000, "pageNumber": page,
            })
            if not data:
                break
            batch = data.get("establishments", [])
            records.extend(batch)
            if len(batch) < 5000:
                break
            page += 1
        cache_file.write_text(json.dumps(records), encoding="utf-8")
        log.info("  %-34s %6s establishments", auth["name"][:34], f"{len(records):,}")

    rows = []
    for e in records:
        parts = [(e.get(f"AddressLine{i}") or "").strip() for i in (1, 2, 3, 4)]
        postcode = addresses.normalise_postcode(e.get("PostCode") or "")
        if not postcode:
            continue

        # The two registers structure addresses differently, and this is why
        # the first run matched almost nothing outside a few boroughs.
        # Companies House puts the street in line 1 ("12 High Street"). The FSA
        # usually puts the premises name there ("The Bakery") and the street in
        # line 2. Building one key from line 1 alone therefore compares a shop
        # name against a street name and finds nothing.
        #
        # So every plausible line is offered as a candidate key and a company
        # matches if it matches ANY of them. Precision is preserved by the
        # postcode, which is part of every key.
        candidates = set()
        for i in range(len(parts)):
            candidates.add(addresses.address_key(parts[i], parts[i + 1]
                                                 if i + 1 < len(parts) else "", postcode))
        joined = " ".join(p for p in parts if p)
        candidates.add(addresses.address_key(joined, "", postcode))
        candidates.discard("")

        for key in candidates:
            rows.append({
                "fhrsid": e.get("FHRSID"),
                "business_name": (e.get("BusinessName") or "").strip(),
                "business_type": (e.get("BusinessType") or "").strip(),
                "authority": auth["name"],
                "addr1": parts[0],
                "addr2": parts[1],
                "postcode": postcode,
                "address_key": key,
            })
    return pd.DataFrame(rows)


def main() -> int:
    auths = london_authorities()
    log.info("London authorities found in the FSA register: %d", len(auths))
    if not auths:
        log.error("Could not resolve London authorities from the FSA API.")
        return 1

    frames = [fetch_authority(a) for a in auths]
    fsa = pd.concat(frames, ignore_index=True)
    fsa = fsa[fsa.address_key != ""]
    log.info("Establishments with a usable address key: %s", f"{len(fsa):,}")

    log.info("")
    log.info("--- FSA business types across London ---")
    for btype, n in fsa.business_type.value_counts().head(14).items():
        log.info("  %-46s %7s", btype, f"{n:,}")

    con = db.connect(wait_seconds=600)
    con.execute("DROP TABLE IF EXISTS fsa_establishments")
    con.register("_fsa", fsa)
    con.execute("CREATE TABLE fsa_establishments AS SELECT * FROM _fsa")
    con.unregister("_fsa")
    con.execute("CREATE INDEX idx_fsa_key ON fsa_establishments(address_key)")

    # ---- the match -------------------------------------------------------
    matched = con.execute(
        """
        SELECT count(DISTINCT c.company_number) FROM companies c
        JOIN fsa_establishments f ON f.address_key = c.address_key
        """
    ).fetchone()[0]
    total = con.execute("SELECT count(*) FROM companies").fetchone()[0]
    log.info("")
    log.info("=" * 84)
    log.info("COMPANY TO PREMISES MATCH")
    log.info("=" * 84)
    log.info("  cohort companies matched to an FSA food premises: %s of %s (%.1f%%)",
             f"{matched:,}", f"{total:,}", 100 * matched / total)

    log.info("")
    log.info("  Match rate by whether the company sits at a mass-registration address:")
    for hub, n, m in con.execute(
        """
        SELECT c.at_hub, count(*),
               count(DISTINCT CASE WHEN f.address_key IS NOT NULL
                                   THEN c.company_number END)
        FROM companies c
        LEFT JOIN fsa_establishments f ON f.address_key = c.address_key
        GROUP BY 1 ORDER BY 1
        """
    ).fetchall():
        label = "agent / mass-registration address" if hub else "ordinary address"
        log.info("    %-36s %7s companies, %6s matched (%.1f%%)",
                 label, f"{n:,}", f"{m:,}", 100 * m / n)

    # ---- the validation the study has been missing ------------------------
    log.info("")
    log.info("=" * 84)
    log.info("SIC AGAINST THE REGULATOR: does the company's self-classification hold?")
    log.info("=" * 84)
    log.info("  %-8s %-40s %8s", "SIC", "FSA business type at the same address", "n")
    for sic, btype, n in con.execute(
        """
        SELECT c.sic_primary, f.business_type, count(*) AS n
        FROM companies c JOIN fsa_establishments f ON f.address_key = c.address_key
        WHERE NOT c.at_hub
        GROUP BY 1,2 QUALIFY row_number() OVER (PARTITION BY c.sic_primary ORDER BY n DESC) <= 4
        ORDER BY c.sic_primary, n DESC
        """
    ).fetchall():
        log.info("  %-8s %-40s %8s", sic, btype[:40], f"{n:,}")

    agree = con.execute(
        f"""
        SELECT
          sum(CASE WHEN c.format='counter' AND f.business_type IN
                ('{"','".join(COUNTER_TYPES)}') THEN 1 ELSE 0 END) AS counter_agree,
          sum(CASE WHEN c.format='counter' AND f.business_type IN
                ('{"','".join(SERVICE_TYPES)}') THEN 1 ELSE 0 END) AS counter_disagree,
          sum(CASE WHEN c.format='service' AND f.business_type IN
                ('{"','".join(SERVICE_TYPES)}') THEN 1 ELSE 0 END) AS service_agree,
          sum(CASE WHEN c.format='service' AND f.business_type IN
                ('{"','".join(COUNTER_TYPES)}') THEN 1 ELSE 0 END) AS service_disagree
        FROM companies c JOIN fsa_establishments f ON f.address_key = c.address_key
        WHERE NOT c.at_hub
        """
    ).fetchone()
    ca, cd, sa, sd = agree
    log.info("")
    log.info("  Counter-coded companies at a counter-type premises: %s; at a "
             "service-type premises: %s  (%.0f%% agreement)",
             f"{ca:,}", f"{cd:,}", 100 * ca / max(ca + cd, 1))
    log.info("  Service-coded companies at a service-type premises: %s; at a "
             "counter-type premises: %s  (%.0f%% agreement)",
             f"{sa:,}", f"{sd:,}", 100 * sa / max(sa + sd, 1))

    # ---- company churn versus premises churn ------------------------------
    log.info("")
    log.info("=" * 84)
    log.info("COMPANIES PER PREMISES: do the legal entities turn over faster?")
    log.info("=" * 84)
    rows = con.execute(
        """
        SELECT f.fhrsid, count(DISTINCT c.company_number) AS companies,
               sum(CASE WHEN c.outcome IN ('dead','failing') THEN 1 ELSE 0 END) AS gone
        FROM fsa_establishments f
        JOIN companies c ON c.address_key = f.address_key
        WHERE NOT c.at_hub
        GROUP BY 1
        """
    ).fetch_df()
    if not rows.empty:
        log.info("  Food premises (distinct FHRSID) matched to >=1 cohort company: %s",
                 f"{len(rows):,}")
        log.info("  Companies per premises: median %.0f, mean %.2f, max %d",
                 rows.companies.median(), rows.companies.mean(), rows.companies.max())
        for k in (1, 2, 3, 4):
            share = (rows.companies == k).mean() if k < 4 else (rows.companies >= 4).mean()
            label = f"{k} companies" if k < 4 else "4 or more companies"
            log.info("    %-22s %5.1f%% of premises", label, 100 * share)
        log.info("  Premises where every matched company has left the register: "
                 "%.1f%%", 100 * (rows.gone == rows.companies).mean())

    con.close()
    log.info("")
    log.info("Manual validation of a sample is required before any figure here is "
             "published. Address matching is conservative; the unmatched rate is "
             "reported above and is not evidence of absence.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

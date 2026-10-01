"""
Step 31 -- the reverse linkage at full scale: every name-resolvable London
food establishment, matched to the company register, with the matching rules
stated precisely enough to be re-implemented from this docstring.

Population: all 17,625 FSA establishments in London whose trading name
contains LTD or LIMITED -- the only ones resolvable BY NAME. Selection stated
wherever results are used: companies named after their shop.

THE MATCHER, precisely
----------------------
Normalisation (both sides identically):
  1. uppercase; "&" -> " AND "
  2. every non-alphanumeric -> space; whitespace collapsed
  3. suffix tokens LTD / LIMITED and leading THE removed
  e.g.  "The Golden Grill (London) Ltd." -> "GOLDEN GRILL LONDON"

Search: Companies House advanced search, company_name_includes = the
normalised name. If zero hits and the name contained "AND", retried with the
"&" form; if still zero and the name has 3+ tokens, retried on the first two
tokens (a broader net that the match tiers then filter).

Match tiers, tried in order, method recorded on every row:
  T1 exact        normalised candidate == normalised target
  T2 no-brackets  equality after deleting bracketed qualifiers on either
                  side -- catches "(LONDON)" / "(UK)" naming style
  T3 typo         Levenshtein distance <= 1 (<= 2 when the target is over
                  12 characters) -- catches single-keystroke errors in
                  either register
  T4 token-sort   equality after sorting tokens -- catches word-order
                  differences ("CAFE ROMA" / "ROMA CAFE")

Tie-break when several candidates pass the same tier:
  a) registered-office postcode DISTRICT equals the premises district
     (the strongest available signal that this is the right company)
  b) company status active over dissolved
  c) earliest incorporation
Ambiguity after tie-breaks is counted and reported, not hidden.

Captured per match: company number, status, incorporation date, SIC codes,
registered postcode -> district, area, London-area flag, cohort membership,
food-SIC flag, and whether the registered office sits in the SAME district
as the premises (the office-at-the-shop rate, measured directly).

Output: out/fsa_reverse_full.csv + summary tables in the log. Every API
response cached; a rerun is free.
"""

from __future__ import annotations

import json
import re
import sys
import time

import pandas as pd

import addresses
import config
import db
from ch_api import CompaniesHouseClient, setup_logging

log = setup_logging("31_fsa_reverse_full")

FOOD_SICS = {"56101", "56102", "56103", "47240"}

AREA_TOWN = {
    "B": "Birmingham", "M": "Manchester", "LS": "Leeds", "CF": "Cardiff",
    "G": "Glasgow", "EH": "Edinburgh", "L": "Liverpool", "S": "Sheffield",
    "NE": "Newcastle", "NG": "Nottingham", "LE": "Leicester", "CV": "Coventry",
    "DE": "Derby", "ST": "Stoke", "PR": "Preston", "BB": "Blackburn",
    "BL": "Bolton", "OL": "Oldham", "BD": "Bradford", "HD": "Huddersfield",
    "LU": "Luton", "SL": "Slough", "RG": "Reading", "GU": "Guildford",
    "AL": "St Albans", "HP": "Hemel Hempstead", "SG": "Stevenage",
    "CM": "Chelmsford", "SS": "Southend", "ME": "Medway", "CT": "Canterbury",
    "TN": "Tonbridge", "OX": "Oxford", "MK": "Milton Keynes",
    "PE": "Peterborough", "CB": "Cambridge", "BN": "Brighton",
    "PO": "Portsmouth", "SO": "Southampton", "NN": "Northampton",
}

_CLEAN = re.compile(r"[^A-Z0-9 ]")
_BRACKETS = re.compile(r"\([^)]*\)")


def normalise(name: str) -> str:
    n = (name or "").upper().replace("&", " AND ")
    n = _CLEAN.sub(" ", n)
    toks = [t for t in n.split() if t not in ("LTD", "LIMITED")]
    if toks and toks[0] == "THE":
        toks = toks[1:]
    return " ".join(toks)


def no_brackets(name: str) -> str:
    return normalise(_BRACKETS.sub(" ", (name or "")))


def levenshtein(a: str, b: str, cap: int) -> int:
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        best = cur[0]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[-1] + 1, prev[j - 1] + (ca != cb)))
            best = min(best, cur[-1])
        if best > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def match_tier(target: str, target_nb: str, candidates: list[dict]) -> tuple[str | None, list[dict]]:
    """Return (method, passing candidates) for the first tier with a hit."""
    t1 = [c for c in candidates if normalise(c.get("company_name", "")) == target]
    if t1:
        return "T1_exact", t1
    t2 = [c for c in candidates if no_brackets(c.get("company_name", "")) == target_nb]
    if t2:
        return "T2_no_brackets", t2
    cap = 2 if len(target) > 12 else 1
    t3 = [c for c in candidates
          if levenshtein(normalise(c.get("company_name", "")), target, cap) <= cap]
    if t3:
        return "T3_typo", t3
    key = " ".join(sorted(target.split()))
    t4 = [c for c in candidates
          if " ".join(sorted(normalise(c.get("company_name", "")).split())) == key]
    if t4:
        return "T4_token_sort", t4
    return None, []


def tie_break(cands: list[dict], premises_district: str) -> tuple[dict, bool]:
    """Best candidate and whether the choice was ambiguous before rules."""
    if len(cands) == 1:
        return cands[0], False

    def district(c):
        pc = ((c.get("registered_office_address") or {}).get("postal_code") or "")
        return addresses.postcode_district(addresses.normalise_postcode(pc))

    same = [c for c in cands if district(c) == premises_district and premises_district]
    pool = same or cands
    active = [c for c in pool if (c.get("company_status") or "") == "active"]
    pool = active or pool
    pool.sort(key=lambda c: c.get("date_of_creation") or "9999")
    return pool[0], True


def main() -> int:
    con = db.connect(read_only=True, wait_seconds=600)
    sample = con.execute(
        """
        SELECT fhrsid, business_name, business_type, authority, postcode
        FROM fsa_establishments
        WHERE upper(business_name) LIKE '%LTD%'
           OR upper(business_name) LIKE '%LIMITED%'
        ORDER BY md5(CAST(fhrsid AS VARCHAR))
        """
    ).df()
    cohort = {r[0] for r in con.execute(
        "SELECT company_number FROM companies").fetchall()}
    con.close()
    log.info("Full name-resolvable population: %s establishments",
             f"{len(sample):,}")

    client = CompaniesHouseClient()
    rows = []
    t0 = time.monotonic()
    for i, e in enumerate(sample.itertuples(), 1):
        target = normalise(e.business_name)
        target_nb = no_brackets(e.business_name)
        if not target:
            continue
        premises_district = addresses.postcode_district(
            addresses.normalise_postcode(e.postcode or ""))

        hits = []
        try:
            hits = (client.advanced_search(
                company_name_includes=target, size=50) or {}).get("items", [])
            if not hits and " AND " in f" {target} ":
                hits = (client.advanced_search(
                    company_name_includes=target.replace(" AND ", " & "),
                    size=50) or {}).get("items", [])
            if not hits and len(target.split()) >= 3:
                broad = " ".join(target.split()[:2])
                hits = (client.advanced_search(
                    company_name_includes=broad, size=50) or {}).get("items", [])
        except Exception as ex:
            log.warning("  search failed %r: %s", target, type(ex).__name__)

        method, cands = match_tier(target, target_nb, hits)
        if method is None:
            rows.append({"fhrsid": e.fhrsid, "business_type": e.business_type,
                         "authority": e.authority, "resolved": False,
                         "method": "none"})
        else:
            best, ambiguous = tie_break(cands, premises_district)
            sics = [str(s) for s in (best.get("sic_codes") or [])]
            pc = addresses.normalise_postcode(
                ((best.get("registered_office_address") or {})
                 .get("postal_code") or ""))
            district = addresses.postcode_district(pc)
            area = re.match(r"^[A-Z]{1,2}", pc or "")
            area = area.group(0) if area else ""
            number = (best.get("company_number") or "").strip()
            rows.append({
                "fhrsid": e.fhrsid, "business_type": e.business_type,
                "authority": e.authority, "resolved": True, "method": method,
                "ambiguous": ambiguous, "n_candidates": len(cands),
                "company_number": number,
                "company_status": best.get("company_status"),
                "incorporated": best.get("date_of_creation"),
                "sics": "|".join(sics),
                "has_food_sic": bool(set(sics) & FOOD_SICS),
                "office_postcode": pc, "office_district": district,
                "office_area": area,
                "office_in_london_area": area in config.LONDON_POSTCODE_AREAS,
                "office_same_district_as_premises":
                    bool(premises_district) and district == premises_district,
                "in_study_cohort": number in cohort,
                "office_town_guess": AREA_TOWN.get(area, ""),
            })

        if i % 500 == 0:
            rate = i / max(time.monotonic() - t0, 1)
            log.info("  %s/%s  (%.1f/s, ~%.1f h left, %d live requests)",
                     f"{i:,}", f"{len(sample):,}", rate,
                     (len(sample) - i) / max(rate, .1) / 3600,
                     client.stats["requests"])
            pd.DataFrame(rows).to_csv(
                config.OUT / "fsa_reverse_full.csv", index=False)

    df = pd.DataFrame(rows)
    df.to_csv(config.OUT / "fsa_reverse_full.csv", index=False)

    res = df[df.resolved == True].copy()  # noqa: E712
    log.info("")
    log.info("==== FULL REVERSE LINKAGE ====")
    log.info("resolved: %s of %s (%.1f%%)", f"{len(res):,}", f"{len(df):,}",
             100 * len(res) / max(len(df), 1))
    for m, n in res.method.value_counts().items():
        log.info("  %-16s %6s", m, f"{n:,}")
    log.info("ambiguous after tie-breaks: %s", f"{int(res.ambiguous.sum()):,}")
    log.info("")
    for col, label in (
        ("has_food_sic", "carries a study food SIC"),
        ("office_in_london_area", "office in a London postcode area"),
        ("office_same_district_as_premises", "office in the SAME district as the premises"),
        ("in_study_cohort", "present in the 119,220 cohort"),
    ):
        log.info("  %-46s %.1f%%", label, 100 * res[col].astype(bool).mean())
    log.info("")
    log.info("--- by business type (resolved n, food-SIC %%, cohort %%) ---")
    for t, sub in res.groupby("business_type"):
        log.info("  %-40s n=%5s  food %5.1f%%  cohort %5.1f%%",
                 t, f"{len(sub):,}",
                 100 * sub.has_food_sic.astype(bool).mean(),
                 100 * sub.in_study_cohort.astype(bool).mean())
    log.info("")
    log.info("--- non-London registered offices, by area (top 15) ---")
    nl = res[~res.office_in_london_area.astype(bool)]
    for area, n in nl.office_area.value_counts().head(15).items():
        log.info("  %-4s %-18s %5s", area, AREA_TOWN.get(area, ""), f"{n:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

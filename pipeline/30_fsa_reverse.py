"""
Step 30 -- the reverse linkage: FSA premises -> Companies House.

The study's universe was built CH -> food SICs -> London addresses, which can
estimate the PRECISION of SIC self-classification but never its RECALL: a
real London food premises whose operating company carries a non-food SIC --
or a registered office outside London -- never entered the 119,220 and is
invisible. This step estimates that blind spot from a sample.

Design, with its selection stated up front: only establishments whose
TRADING NAME contains "LTD"/"LIMITED" can be resolved to the register by
name (17,625 of 231,089 London food establishments). Companies named after
their shop are plausibly unrepresentative -- single-site, owner-named -- so
the estimate is a first bound, not a census. A deterministic sample of 400
is drawn (ordered hash of the FHRS id), each searched on the Companies House
advanced-search API by normalised name, and an exact normalised-name match
accepted.

For every resolved company: does it carry one of the four study SICs? Is its
registered office in London? Is it in the study cohort? The three shares are
the recall estimate, the geography leak, and the two-population gap.

Results: out/fsa_reverse_sample.csv. API responses cached as always.
"""

from __future__ import annotations

import re
import sys

import pandas as pd

import config
import db
from ch_api import CompaniesHouseClient, setup_logging

log = setup_logging("30_fsa_reverse")

RELEVANT_TYPES = {
    "Restaurant/Cafe/Canteen", "Takeaway/sandwich shop",
    "Bakers", "Bakery",
}
SAMPLE = 400
FOOD_SICS = {"56101", "56102", "56103", "47240"}

_CLEAN = re.compile(r"[^A-Z0-9 ]")


def normalise(name: str) -> str:
    n = _CLEAN.sub(" ", (name or "").upper())
    n = re.sub(r"\b(LTD|LIMITED|THE)\b", " ", n)
    return " ".join(n.split())


def main() -> int:
    con = db.connect(read_only=True, wait_seconds=600)
    types = ",".join(f"'{t}'" for t in RELEVANT_TYPES)
    sample = con.execute(
        f"""
        SELECT fhrsid, business_name, business_type, postcode
        FROM fsa_establishments
        WHERE (upper(business_name) LIKE '%LTD%'
               OR upper(business_name) LIKE '%LIMITED%')
          AND business_type IN ({types})
        ORDER BY md5(CAST(fhrsid AS VARCHAR))
        LIMIT {SAMPLE}
        """
    ).df()
    cohort = {
        r[0] for r in con.execute("SELECT company_number FROM companies").fetchall()
    }
    con.close()
    log.info("Sample: %d name-resolvable London food establishments "
             "(of 17,625 eligible; deterministic hash order)", len(sample))

    client = CompaniesHouseClient()
    rows = []
    for i, e in enumerate(sample.itertuples(), 1):
        target = normalise(e.business_name)
        if not target:
            continue
        try:
            hits = (client.advanced_search(
                company_name_includes=target, size=20) or {}).get("items", [])
        except Exception as ex:
            log.warning("  search failed for %r: %s", target, type(ex).__name__)
            continue
        match = next(
            (h for h in hits if normalise(h.get("company_name", "")) == target),
            None,
        )
        if match is None:
            rows.append({"fhrsid": e.fhrsid, "resolved": False})
            continue
        sics = [str(s) for s in (match.get("sic_codes") or [])]
        pc = ((match.get("registered_office_address") or {}).get("postal_code")
              or "").upper().replace(" ", "")
        area = re.match(r"^[A-Z]{1,2}", pc)
        london = bool(area) and area.group(0) in config.LONDON_POSTCODE_AREAS
        number = (match.get("company_number") or "").strip()
        rows.append({
            "fhrsid": e.fhrsid,
            "resolved": True,
            "company_number": number,
            "has_food_sic": bool(set(sics) & FOOD_SICS),
            "sics": "|".join(sics),
            "registered_in_london_area": london,
            "in_study_cohort": number in cohort,
        })
        if i % 100 == 0:
            log.info("  %d/%d searched", i, len(sample))

    df = pd.DataFrame(rows)
    df.to_csv(config.OUT / "fsa_reverse_sample.csv", index=False)

    res = df[df.resolved == True].copy()  # noqa: E712
    res["has_food_sic"] = res.has_food_sic.astype(bool)
    log.info("")
    log.info("--- reverse linkage, name-resolvable sample ---")
    log.info("  resolved to a company by exact normalised name: %d of %d (%.1f%%)",
             len(res), len(df), 100 * len(res) / max(len(df), 1))
    if len(res):
        log.info("  of resolved -- carries a study food SIC:        %.1f%%",
                 100 * res.has_food_sic.mean())
        log.info("  of resolved -- registered office in a London "
                 "postcode area:                                  %.1f%%",
                 100 * res.registered_in_london_area.mean())
        log.info("  of resolved -- present in the 119,220 cohort:   %.1f%%",
                 100 * res.in_study_cohort.mean())
        log.info("")
        log.info("  Missing from the cohort therefore splits into: no food "
                 "SIC (recall loss), non-London registered office (geography "
                 "leak), or both. SIC distribution of resolved non-food:")
        nf = res[res.has_food_sic == False]  # noqa: E712
        from collections import Counter
        c = Counter(s for row in nf.sics for s in row.split("|") if s)
        for sic, n in c.most_common(8):
            log.info("    %-8s %d", sic, n)
    log.info("")
    log.info("Selection caveat prints with every use: name-resolvable "
             "establishments only; companies named after their shop.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

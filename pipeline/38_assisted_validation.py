"""
Step 38 -- assisted validation: an independently constructed second classifier.

Honest labelling first: this is NOT independent human review. It is a
SECOND, DIFFERENTLY-CONSTRUCTED automated re-derivation of every sampled
case, with disagreements surfaced for case-by-case adjudication and the
full worksheets published. A reader can re-check any row; the method is
documented here; the residual limitation (no human rater) is stated
wherever the results are used.

Three parts:

A. EXIT ROUTES, second rater. The production classifier works on the SET of
   filing types. The second rater is sequence-aware and description-aware:
   it orders the decisive filings by date, reads the description text, and
   applies different logic (last-procedure-wins with withdrawal handling)
   rather than the classifier's fixed priority. Agreement, disagreement and
   unclear are counted; disagreements go to adjudication.

B. PREMISES MATCHES, plausibility scorer. For each of the 200 sampled
   company-establishment pairs: postcode equality, street-number equality,
   and name-token containment between the FSA trading name and the CH
   company name. Strong pairs pass; weak pairs go to adjudication.

C. THE NON-LTD GENERALISATION TEST (referee point 3). The Ltd-named slice
   is 7.3% of establishments. For everything else, names cannot resolve --
   but ADDRESSES can: sample deduplicated non-Ltd food establishments,
   look for cohort companies registered at the same address key where that
   address holds exactly one company. Coverage there is a lower bound on
   register visibility for the 92.7%, built with zero hand research.

Outputs: out/validation/exit_sample_scored.csv,
premises_sample_scored.csv, nonltd_generalisation.csv + log summary.
"""

from __future__ import annotations

import re
import sys

import pandas as pd

import config
import db
from ch_api import setup_logging

log = setup_logging("38_assisted_validation")

OUT = config.OUT / "validation"


# ---------- A. exit second rater ----------

def second_rate_exit(decisive: str) -> str:
    """Sequence-aware re-derivation from the decisive-filings string."""
    if not isinstance(decisive, str) or decisive.startswith("("):
        return "unclear"
    events = []
    for part in decisive.split("||"):
        part = part.strip()
        m = re.match(r"(\d{4}-\d{2}-\d{2})\s+(\S+)\s*(.*)", part)
        if m:
            events.append((m.group(1), m.group(2).upper(), m.group(3).lower()))
    if not events:
        return "unclear"
    events.sort()

    def last(pred):
        hits = [e for e in events if pred(e)]
        return hits[-1] if hits else None

    court = last(lambda e: e[1].startswith("WU") or e[1] == "4.20"
                 or "winding-up order" in e[2] or "wound up by the court" in e[2])
    admin = last(lambda e: e[1].startswith("AM") or "administration" in e[2])
    decl = last(lambda e: e[1] in ("LIQ01", "4.70")
                or "declaration of solvency" in e[2])
    cvl_evid = last(lambda e: e[1] in ("LIQ02", "LIQ03", "4.68", "2.24B")
                    or "creditors" in e[2])
    vol_liq = last(lambda e: e[1] in ("LRESSP", "600", "601", "602",
                                      "LIQ10", "LIQ13", "LIQ14")
                   or "resolution to wind up" in e[2])
    ds01 = last(lambda e: e[1] == "DS01" or "application to strike" in e[2])
    ds01_wd = last(lambda e: e[1] in ("DS02",) or "withdraw" in e[2])
    gaz_vol = last(lambda e: e[1] in ("GAZ1(A)", "GAZ2(A)", "GAZ1A", "GAZ2A"))
    gaz_reg = last(lambda e: e[1] in ("GAZ1", "GAZ2", "FTE1", "FTE2"))

    if court:
        return "compulsory_liquidation"
    if admin and not (vol_liq and vol_liq[0] > admin[0]):
        return "administration"
    if decl and not (cvl_evid and cvl_evid[0] > decl[0]):
        return "members_voluntary_liquidation"
    if cvl_evid or vol_liq:
        return "creditors_voluntary_liquidation"
    if ds01 and not (ds01_wd and ds01_wd[0] > ds01[0]):
        return "voluntary_strike_off"
    if gaz_vol:
        return "voluntary_strike_off"
    if gaz_reg:
        return "registrar_strike_off"
    return "unclear"


def part_a() -> pd.DataFrame:
    df = pd.read_csv(OUT / "exit_sample.csv")
    df["second_rater"] = df.decisive_filings.map(second_rate_exit)
    df["verdict"] = "AGREE"
    df.loc[df.second_rater == "unclear", "verdict"] = "UNCLEAR"
    df.loc[(df.second_rater != "unclear")
           & (df.second_rater != df.exit_route), "verdict"] = "DISAGREE"
    df.to_csv(OUT / "exit_sample_scored.csv", index=False)
    vc = df.verdict.value_counts()
    log.info("A. EXIT ROUTES (n=%d): agree %d, disagree %d, unclear %d",
             len(df), vc.get("AGREE", 0), vc.get("DISAGREE", 0),
             vc.get("UNCLEAR", 0))
    for r in df[df.verdict != "AGREE"].itertuples():
        log.info("   %s  label=%s  rater2=%s  | %s",
                 r.company_number, r.exit_route, r.second_rater,
                 str(r.decisive_filings)[:150])
    return df


# ---------- B. premises plausibility ----------

_CLEAN = re.compile(r"[^A-Z0-9 ]")
STOP = {"LTD", "LIMITED", "THE", "AND", "OF", "CO", "UK", "LONDON",
        "RESTAURANT", "RESTAURANTS", "CAFE", "KITCHEN", "FOOD", "FOODS"}


def toks(s):
    return {t for t in _CLEAN.sub(" ", str(s).upper()).split()
            if t and t not in STOP}


def number(s):
    m = re.match(r"\s*(\d+[A-Za-z]?)\b", str(s))
    return m.group(1).upper() if m else ""


def part_b() -> pd.DataFrame:
    df = pd.read_csv(OUT / "premises_sample.csv")
    rows = []
    for r in df.itertuples():
        pc = str(r.ch_postcode).replace(" ", "").upper() == \
             str(r.fsa_postcode).replace(" ", "").upper()
        num_ch = number(r.ch_addr1) or number(r.ch_addr2)
        num_fs = number(r.fsa_addr1) or number(r.fsa_addr2)
        num = bool(num_ch) and num_ch == num_fs
        t1, t2 = toks(r.company_name), toks(r.fsa_name)
        name_overlap = len(t1 & t2) / max(1, min(len(t1), len(t2))) if t1 and t2 else 0
        score = (2 * pc) + (1 * num) + (2 * (name_overlap >= 0.5)) + (1 * (0 < name_overlap < 0.5))
        verdict = ("STRONG" if (pc and (num or name_overlap >= 0.5))
                   else "PLAUSIBLE" if score >= 2 else "REVIEW")
        rows.append({"postcode_match": pc, "number_match": num,
                     "name_overlap": round(name_overlap, 2),
                     "auto_verdict": verdict})
    out = pd.concat([df, pd.DataFrame(rows)], axis=1)
    out.to_csv(OUT / "premises_sample_scored.csv", index=False)
    vc = out.auto_verdict.value_counts()
    log.info("")
    log.info("B. PREMISES MATCHES (n=%d): strong %d, plausible %d, review %d",
             len(out), vc.get("STRONG", 0), vc.get("PLAUSIBLE", 0),
             vc.get("REVIEW", 0))
    # Address components match BY CONSTRUCTION (pairs were made on address
    # keys), so the only independent evidence here is the NAME channel.
    no = out.name_overlap
    log.info("   independent name evidence: overlap>=0.5: %d (%.0f%%), "
             "partial 0<x<0.5: %d, zero: %d -- zero-name pairs rest on "
             "address-only evidence and are the honest review set",
             int((no>=0.5).sum()), 100*(no>=0.5).mean(),
             int(((no>0)&(no<0.5)).sum()), int((no==0).sum()))
    for r in out[out.auto_verdict == "REVIEW"].itertuples():
        log.info("   %s | CH:%r %r %s | FSA:%r %r %s",
                 r.company_number, str(r.company_name)[:34],
                 str(r.ch_addr1)[:28], r.ch_postcode,
                 str(r.fsa_name)[:34], str(r.fsa_addr1)[:28], r.fsa_postcode)
    return out


# ---------- C. non-Ltd generalisation by address ----------

def part_c() -> None:
    con = db.connect(read_only=True, wait_seconds=600)
    df = con.execute("""
        WITH est AS (
            SELECT fhrsid, any_value(business_name) AS business_name,
                   any_value(business_type) AS business_type,
                   list(DISTINCT address_key) AS keys
            FROM fsa_establishments
            JOIN fsa_address_keys USING (fhrsid)
            WHERE business_type IN ('Restaurant/Cafe/Canteen',
                                    'Takeaway/sandwich shop', 'Mobile caterer')
              AND upper(business_name) NOT LIKE '%LTD%'
              AND upper(business_name) NOT LIKE '%LIMITED%'
            GROUP BY fhrsid
            ORDER BY md5(CAST(fhrsid AS VARCHAR))
            LIMIT 4000
        ),
        expl AS (
            SELECT e.fhrsid, e.business_type, u.key
            FROM est e, unnest(e.keys) AS u(key)
            WHERE u.key IS NOT NULL AND u.key <> ''
        ),
        hits AS (
            SELECT x.fhrsid, x.business_type,
                   max(CASE WHEN c.companies_at_address = 1 THEN 1 ELSE 0 END) AS single_co_match,
                   max(CASE WHEN c.companies_at_address = 1
                            AND c.sic_primary IN ('56101','56102','56103','47240')
                            THEN 1 ELSE 0 END) AS single_co_food
            FROM expl x LEFT JOIN companies c ON c.address_key = x.key
            GROUP BY 1, 2
        )
        SELECT business_type,
               count(*) AS establishments,
               sum(single_co_match) AS with_single_company_at_address,
               sum(single_co_food) AS of_which_food_cohort
        FROM hits GROUP BY 1
    """).df()
    con.close()
    df.to_csv(OUT / "nonltd_generalisation.csv", index=False)
    log.info("")
    log.info("C. NON-LTD ESTABLISHMENTS, address-based register visibility "
             "(sample of 4,000 deduplicated):")
    for r in df.itertuples():
        log.info("   %-28s n=%5d  single-company CH address: %4d (%.1f%%)  "
                 "of which in food cohort: %4d (%.1f%% of matched)",
                 r.business_type, r.establishments,
                 r.with_single_company_at_address,
                 100 * r.with_single_company_at_address / r.establishments,
                 r.of_which_food_cohort,
                 100 * r.of_which_food_cohort /
                 max(1, r.with_single_company_at_address))
    log.info("   Reading: an address-key match to a single registered company "
             "is evidence, not proof, of the operator; this is a lower bound "
             "on register visibility for the 92.7%% that names cannot resolve.")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    part_a()
    part_b()
    part_c()
    log.info("")
    log.info("Label wherever used: assisted validation -- second automated "
             "rater + adjudicated disagreements; worksheets published; no "
             "human rater, stated as a limitation.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
The exit-route classifier, in one place.

This module exists because the classifier used to live in two places -- step 7
(the pull) and step 16 (the correction) -- and they disagreed. Step 7 carried
the withdrawn GAZ1-prefix bug; step 16 fixed that but had a branch-order bug of
its own that made members' voluntary liquidation unreachable. Both steps now
import this module, so there is exactly one classification and it is the
corrected one.

The MVL problem, because it is subtle enough to have caused two bugs
----------------------------------------------------------------------
A members' voluntary liquidation is a SOLVENT winding-up: the directors swear a
declaration of solvency and the company pays everyone in full. It is a
retirement or a restructure, not a failure, and counting it as insolvency is
exactly the dissolution-versus-failure conflation this study exists to avoid.

But every MVL filing carries the Companies House category "insolvency", and the
liquidation forms are shared across procedures:

  * LIQ01 / 4.70    declaration of solvency -- this DEFINES the MVL
  * LIQ13           return of final meeting in an MVL (members')
  * LIQ14           return of final meeting in a CVL (creditors')
  * LRESSP          special resolution to wind up -- filed in BOTH MVL and CVL
  * 600 / 601 / 602 liquidator appointment and notices -- any liquidation type

So the statutory logic is applied directly: a voluntary liquidation WITH a
declaration of solvency is an MVL; a voluntary liquidation WITHOUT one is a
CVL. The declaration is checked before any category-based test, because the
category cannot tell the two apart. A declaration followed by CVL-specific
paperwork (a statement of affairs means creditors are involved) is a
conversion -- an MVL that turned out not to be solvent -- and is classified CVL.

Verified against the cached filing histories: 134 companies in the cohort filed
a declaration of solvency; under the previous branch order all 134 were
classified as insolvency, 121 of them as compulsory liquidation via LIQ13.
"""

from __future__ import annotations

# Winding up BY THE COURT. Unambiguously compulsory, unambiguously insolvency.
COURT_LIQ_FORMS = {"WU01", "WU02", "WU07", "WU15", "4.20", "COCOMP", "L64.07"}  # COCOMP/WU07/L64.07 added after assisted validation caught compulsory orders classified insolvency_other

# CVL-specific paperwork: a statement of affairs for creditors has no place in
# a members' voluntary liquidation.
CVL_ONLY_FORMS = {"LIQ02", "LIQ03", "4.68", "2.24B"}

# The declaration of solvency. Present in an MVL and only in an MVL.
MVL_DECLARATION_FORMS = {"LIQ01", "4.70"}

# Voluntary-liquidation paperwork that appears in BOTH procedures. Evidence
# that a voluntary liquidation happened; silent on which kind.
VOL_LIQ_GENERIC_FORMS = {"LRESSP", "600", "601", "602", "LIQ10", "LIQ13", "LIQ14"}

# Strike-off. The (A) suffix marks the gazette notice that follows a voluntary
# DS01 application; without it the notice is registrar-initiated. Matched
# exactly, never by prefix -- the prefix version of this rule is corrections-log
# item 2.
VOLUNTARY_FORMS = {"DS01", "DS02", "GAZ1(A)", "GAZ2(A)", "GAZ1A", "GAZ2A"}
REGISTRAR_FORMS = {"GAZ1", "GAZ2", "FTE1", "FTE2"}


def classify(filings: list[dict]) -> tuple[str, str]:
    """Return (exit_route, exit_family) for one company's filing history."""
    forms = {(f.get("type") or "").upper() for f in filings}
    categories = {(f.get("category") or "").lower() for f in filings}

    has_court = bool(forms & COURT_LIQ_FORMS)
    has_admin = any(f.startswith("AM") for f in forms)
    has_declaration = bool(forms & MVL_DECLARATION_FORMS)
    has_cvl_only = bool(forms & CVL_ONLY_FORMS)
    has_vol_liq = bool(forms & VOL_LIQ_GENERIC_FORMS)
    has_insolvency_cat = "insolvency" in categories
    has_voluntary = bool(forms & VOLUNTARY_FORMS)
    has_registrar = bool(forms & REGISTRAR_FORMS)

    # Court procedures first: a winding-up order or an administration is an
    # insolvency whatever else was filed.
    if has_court:
        return "compulsory_liquidation", "insolvency"
    if has_admin:
        return "administration", "insolvency"
    # The declaration of solvency decides between the voluntary procedures,
    # and it must be tested BEFORE the category, because MVL filings carry the
    # category "insolvency" too. A declaration alongside CVL-specific paperwork
    # is a conversion and stays CVL.
    if has_declaration and not has_cvl_only:
        return "members_voluntary_liquidation", "solvent_winding_up"
    if has_cvl_only or has_vol_liq:
        return "creditors_voluntary_liquidation", "insolvency"
    if has_insolvency_cat:
        return "insolvency_other", "insolvency"
    # Directors applying to strike their own company off beats a registrar
    # notice, because the registrar notice is usually a consequence of it.
    if has_voluntary:
        return "voluntary_strike_off", "voluntary_dissolution"
    if has_registrar:
        return "registrar_strike_off", "registrar_dissolution"
    return "unknown", "unknown"

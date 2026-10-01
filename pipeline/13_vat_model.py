"""
Step 13 -- what VAT do the chains actually carry, once you look at the whole business?

Read this before quoting any number this script produces
--------------------------------------------------------
**No UK company discloses the VAT it collects.** Turnover in statutory accounts
is stated NET of VAT, and there is no line anywhere -- profit and loss, balance
sheet or notes -- for output tax. The "tax" line is corporation tax, a
different tax entirely. So "how much VAT did Greggs pay" cannot be looked up.
It can only be modelled. The revenue figures here are audited evidence; every
VAT figure is arithmetic performed on an assumption, and the report must label
it that way wherever it appears.

Three corrections to the naive model, each of which moves the answer a long way
-------------------------------------------------------------------------------

**1. These are groups, not shops.** A first pass treated Costa as "coffee, so
20%". Costa Limited's revenue is company-operated stores, franchise royalties,
Costa Express, wholesale roasted coffee to franchisees and third parties, and
packaged coffee through supermarkets. Greggs runs company-managed shops,
franchised shops and a wholesale arm selling frozen product through a
supermarket partner. Pret sells through supermarkets and franchises abroad.
Gail's runs a wholesale bakery supplying trade customers. Each stream has its
own treatment.

**2. Retail coffee is zero-rated.** Roasted beans and ground coffee sold for
home preparation are food, not a beverage: VATA 1994 Schedule 8, Group 1, the
overriding items that restore zero-rating to "cocoa, coffee, chicory and other
roasted coffee substitutes, and preparations and extracts thereof". The cup of
coffee is standard-rated; the bag of the same beans is not. A coffee company's
grocery arm is therefore a ZERO-rated business sitting inside a standard-rated
one. Ready-to-drink canned coffee goes the other way -- a beverage, standard-
rated. These boundaries are exactly the kind that need specialist sign-off.

**3. VAT on a business-to-business sale is not a burden.** A franchisee
reclaims the VAT on its royalty. A supermarket reclaims the VAT on anything
standard-rated it buys. Standard-rating only *bites* where the customer cannot
reclaim -- retail sales to the public. So the number that matters for the
thesis is not the effective rate across all revenue; it is the effective rate
across the CONSUMER-FACING revenue, because that is the money competing with
the zero-rated shop next door.

And the fourth, which inverts the whole picture for some of them
----------------------------------------------------------------
**VAT is a net tax.** What reaches HMRC is output tax minus recoverable input
tax. A fully taxable business recovers input VAT on everything it buys --
packaging, energy, rent where the landlord has opted to tax, equipment,
marketing, professional fees, delivery commissions.

So a business selling zero-rated food is not merely paying no VAT. It is in a
**repayment position**: it reclaims input tax with no output tax to set against
it, and HMRC pays it money. The wholesale bakery, the frozen-product arm, the
bag of beans -- these are not neutral. They are net receipts from the
Exchequer.

That is the sharpest version of the Window Tax parallel this study has found.
The tax system does not simply charge the dining room more than the hatch. On
the zero-rated side of the line it pays money out.

Cost base assumptions
---------------------
Input VAT is modelled from the cost structure the accounts disclose -- staff
costs and depreciation carry no VAT at all, food inputs are mostly zero-rated,
and the residue (packaging, energy, property, services, technology, marketing)
mostly does. Where a note has been read, the real figure is used; where it has
not, the assumption is stated and flagged.

A counter format uses materially more packaging per pound of sales than a
dining room does, and packaging is standard-rated. That works in the counter's
favour on the input side and is one more reason the naive arithmetic overstates
the gap.
"""

from __future__ import annotations

import datetime as dt
import json
import sys

import pandas as pd

import config
from ch_api import setup_logging

log = setup_logging("13_vat_model")

# ---------------------------------------------------------------------------
# VAT treatment of each kind of thing these businesses sell
# ---------------------------------------------------------------------------
#
# `standard_share` is the fraction of that stream's net revenue that carries
# the standard rate. `consumer_facing` decides whether the VAT is a real burden
# or is reclaimed by the buyer.

TREATMENTS = {
    "retail_eat_in": {
        "standard_share": 1.00, "consumer_facing": True,
        "why": "Consumed on the premises is catering. Standard-rated without exception.",
    },
    "retail_hot_drinks": {
        "standard_share": 1.00, "consumer_facing": True,
        "why": "Hot drinks are standard-rated in every circumstance. There is no "
               "zero-rating route for a cup of coffee, lid on or lid off.",
    },
    "retail_hot_food_takeaway": {
        "standard_share": 1.00, "consumer_facing": True,
        "why": "Hot takeaway food KEPT hot, heated to order or sold from a hot "
               "cabinet -- standard-rated under the five 2012 tests (originally "
               "standard-rated from 1984).",
    },
    "retail_bake_cooling": {
        "standard_share": 0.00, "consumer_facing": True,
        "why": "The pasty-tax settlement: food sold warm because it is "
               "cooling from the oven, not kept hot, not heated to order, not "
               "in heat-retentive packaging and not marketed as hot, fails all "
               "five 2012 tests and is ZERO-rated. This is why a rack-cooled "
               "sausage roll is zero-rated while the same item from a hot "
               "cabinet is not. Needs specialist sign-off per item.",
    },
    "retail_cold_takeaway": {
        "standard_share": 0.22, "consumer_facing": True,
        "why": "Cold takeaway food is zero-rated, EXCEPT the excepted items -- "
               "confectionery, crisps, ice cream, soft drinks and bottled water -- "
               "which stay standard-rated. No real basket is wholly zero-rated; "
               "the assumed 22% is the drinks-and-snacks attachment.",
    },
    "grocery_packaged_coffee": {
        "standard_share": 0.00, "consumer_facing": True,
        "why": "Roasted beans, ground coffee and pods sold for home preparation "
               "are zero-rated food (Sch 8 Grp 1 overriding items). The bag is "
               "zero-rated even though the cup is not.",
    },
    "grocery_chilled_frozen_food": {
        "standard_share": 0.05, "consumer_facing": True,
        "why": "Cold food sold through a supermarket is zero-rated. The small "
               "standard-rated residue is confectionery lines.",
    },
    "ready_to_drink": {
        "standard_share": 0.00, "consumer_facing": True,
        "why": "Cold canned and bottled coffee sold to take away is a preparation "
               "of coffee, restored to zero-rating by Sch 8 Grp 1 overriding "
               "item 5 (HMRC VFOOD7720, checked 1 Oct 2026). Only hot drinks or "
               "drinks consumed on the premises are standard-rated.",
    },
    "franchise_royalties": {
        "standard_share": 1.00, "consumer_facing": False,
        "why": "Standard-rated services, but the franchisee reclaims it in full. "
               "No burden on anyone.",
    },
    "wholesale_food_to_trade": {
        "standard_share": 0.00, "consumer_facing": False,
        "why": "Bread, bakery and roasted coffee sold to trade customers are "
               "zero-rated food. This stream generates NO output tax while its "
               "input tax is recoverable -- a net repayment from HMRC.",
    },
    "wholesale_equipment_services": {
        "standard_share": 1.00, "consumer_facing": False,
        "why": "Machines, licences and support charged to trade customers. "
               "Standard-rated, and reclaimed by the customer.",
    },
    "other": {
        "standard_share": 0.60, "consumer_facing": False,
        "why": "Residual. Assumed mostly standard-rated business-to-business.",
    },
}

# ---------------------------------------------------------------------------
# What each chain actually sells, as a share of net revenue
# ---------------------------------------------------------------------------
#
# These shares are the load-bearing assumption in the whole model. Where the
# revenue note discloses a split, `source` says so and the numbers come from
# the filing. Where it does not, the shares are a stated judgement about the
# format and `source` says "assumption" -- and the sensitivity run shows how
# much the answer depends on it.

CHAIN_STREAMS = {
    "costa": {
        "name": "Costa Limited",
        "source": "assumption pending revenue note",
        "streams": {
            "retail_hot_drinks": 0.42,
            "retail_eat_in": 0.18,
            "retail_cold_takeaway": 0.08,
            "franchise_royalties": 0.09,
            "wholesale_food_to_trade": 0.13,     # roasted beans to franchisees and Express
            "wholesale_equipment_services": 0.05,
            "grocery_packaged_coffee": 0.03,
            "ready_to_drink": 0.02,
        },
        "note": (
            "The correction that matters most here. Costa Express is largely a "
            "business-to-business proposition: the forecourt operator sells the "
            "cup to the public, and Costa sells that operator beans (zero-rated "
            "food) and machine services. So a large slice of what looks like "
            "'coffee revenue' never touches a consumer at the standard rate."
        ),
    },
    "greggs": {
        "name": "Greggs plc",
        "source": "B2B share DISCLOSED (segmental note); retail split assumed",
        "streams": {
            # Segmental note, FY2025: retail company-managed shops £1,897.2m,
            # business-to-business £254.0m, total £2,151.2m. So B2B is 11.8% of
            # revenue (FY2024: 11.6%). The B2B channel sells product to
            # franchise and wholesale partners -- food, zero-rated -- plus a
            # smaller royalty element which is standard-rated but reclaimed.
            "wholesale_food_to_trade": 0.095,
            "franchise_royalties": 0.023,
            # Retail 88.2%, split by format. Still an assumption.
            "retail_hot_food_takeaway": 0.310,
            "retail_cold_takeaway": 0.375,
            "retail_hot_drinks": 0.135,
            "retail_eat_in": 0.062,
        },
        "note": (
            "Greggs is the case the cooling rule decides. Its baked savouries "
            "are racked to cool, not kept hot -- that is precisely how they "
            "stay zero-rated under the 2012 tests -- while the hot cabinets "
            "(pizza, chicken, hot sandwiches, rolled out from 2022) and every "
            "hot drink are standard-rated. How much of the 31% 'hot food' till "
            "is genuinely kept hot is therefore the single assumption the "
            "Greggs figure turns on, and the scenario table below shows its "
            "range rather than pretending to know it."
        ),
    },
    "pret": {
        "name": "Pret A Manger (Europe) Limited",
        "source": "assumption pending revenue note",
        "streams": {
            "retail_cold_takeaway": 0.34,
            "retail_hot_drinks": 0.26,
            "retail_eat_in": 0.20,
            "retail_hot_food_takeaway": 0.11,
            "franchise_royalties": 0.05,
            "grocery_chilled_frozen_food": 0.04,
        },
        "note": (
            "Pret charges a higher price to eat in at many sites. That is a "
            "business pricing explicitly for the VAT boundary, and it is the "
            "cleanest public evidence in the study that operators treat this "
            "gap as real money rather than an accounting curiosity."
        ),
    },
    "gails": {
        "name": "Gail's (Grain Topco Limited)",
        "source": "wholesale share DISCLOSED (revenue analysis note); retail split assumed",
        "streams": {
            # Revenue analysis note, FY2025: retail £219,828k, wholesale
            # £58,217k, total £278,045k. Wholesale is 20.9% of revenue
            # (FY2024: 22.8%) -- larger than the brand's shop estate suggests,
            # and every pound of it is zero-rated food sold to trade.
            "wholesale_food_to_trade": 0.209,
            # Retail 79.1%, split by format. Still an assumption.
            "retail_cold_takeaway": 0.285,
            "retail_eat_in": 0.235,
            "retail_hot_drinks": 0.215,
            "retail_hot_food_takeaway": 0.056,
        },
        "note": (
            "Gail's runs a real wholesale bakery alongside the shops. That arm "
            "is zero-rated on its sales and recovers input tax on its costs, so "
            "it is a net repayment business inside a standard-rated retail one."
        ),
    },
}

# ---------------------------------------------------------------------------
# Cost base: what share of each cost line carries recoverable input VAT
# ---------------------------------------------------------------------------

COST_VAT_BEARING = {
    "staff_costs": 0.00,          # wages, NI, pension: outside VAT entirely
    "depreciation": 0.00,         # the input tax was recovered when bought
    "food_ingredients": 0.05,     # mostly zero-rated food; the residue is packaging-in-price
    "packaging": 1.00,            # standard-rated, and a counter uses far more of it
    "property_energy": 0.55,      # rent only where the landlord has opted to tax; energy yes
    "other_operating": 0.85,      # marketing, technology, professional fees, repairs
}

# Fallback shares of total operating cost, used until the expense notes are read.
DEFAULT_COST_SPLIT = {
    "staff_costs": 0.33,
    "depreciation": 0.09,
    "food_ingredients": 0.28,
    "packaging": 0.05,
    "property_energy": 0.14,
    "other_operating": 0.11,
}

STANDARD_RATE = 0.20

# ---------------------------------------------------------------------------
# The Greggs question: how much of the "hot food" till is genuinely KEPT hot?
# ---------------------------------------------------------------------------
#
# The base model above books all of Greggs' hot-food share (31.0% of revenue)
# as standard-rated. That is the correct treatment for hot cabinets and
# heated-to-order lines, and the WRONG treatment for the rack-cooled baked
# savouries -- the sausage rolls and bakes that fail all five 2012 tests and
# are zero-rated. Nobody outside Greggs knows the true split, so it is run as
# scenarios: the share of the hot-food till that is kept hot / heated to
# order, with the remainder reclassified as cooling bakes at 0%.
GREGGS_KEPT_HOT_SCENARIOS = {
    "high: all hot food standard (base model)": 1.00,
    "central: hot cabinets, hot sandwiches, heated lines": 0.35,
    "low: cooling rule on all baked savouries": 0.10,
}

# The hospitality rate applied to catering and to hot takeaway food and drink.
# Cold takeaway food was zero-rated throughout and is unaffected.
HOSPITALITY_RATE = [
    (dt.date(2000, 1, 1), dt.date(2020, 7, 14), 0.20),
    (dt.date(2020, 7, 15), dt.date(2021, 9, 30), 0.05),
    (dt.date(2021, 10, 1), dt.date(2022, 3, 31), 0.125),
    (dt.date(2022, 4, 1), dt.date(2100, 1, 1), 0.20),
]

# Streams the temporary reduced rate actually applied to.
HOSPITALITY_STREAMS = {
    "retail_eat_in", "retail_hot_drinks", "retail_hot_food_takeaway",
}


def hospitality_rate_for_year(year_end: dt.date, days: int = 364) -> float:
    """Average hospitality rate over a financial year, weighted by days.

    A year ending 2 January 2021 straddles the 20% period and the 5% period.
    Applying one headline rate to the whole year would be simply wrong.
    """
    start = year_end - dt.timedelta(days=days - 1)
    weighted = 0.0
    for period_start, period_end, rate in HOSPITALITY_RATE:
        overlap = (min(year_end, period_end) - max(start, period_start)).days + 1
        if overlap > 0:
            weighted += rate * overlap
    return weighted / days


def model_year(revenue_net: float, streams: dict, hospitality_rate: float,
               cost_split: dict | None = None, operating_costs: float | None = None) -> dict:
    """Model one chain-year: output tax, consumer burden, input tax, net position."""
    output_vat = 0.0
    consumer_vat = 0.0
    consumer_net_revenue = 0.0
    zero_rated_revenue = 0.0

    for stream, share in streams.items():
        treatment = TREATMENTS[stream]
        stream_net = revenue_net * share
        rate = hospitality_rate if stream in HOSPITALITY_STREAMS else STANDARD_RATE
        standard_net = stream_net * treatment["standard_share"]
        vat = standard_net * rate
        output_vat += vat
        zero_rated_revenue += stream_net - standard_net
        if treatment["consumer_facing"]:
            consumer_vat += vat
            consumer_net_revenue += stream_net

    # Input tax. Recoverable in full for these businesses -- all are fully
    # taxable, none is partly exempt.
    costs = operating_costs if operating_costs else revenue_net * 0.93
    split = cost_split or DEFAULT_COST_SPLIT
    input_vat = sum(
        costs * split.get(line, 0.0) * bearing * STANDARD_RATE
        for line, bearing in COST_VAT_BEARING.items()
    )

    consumer_gross = consumer_net_revenue + consumer_vat
    return {
        "revenue_net": revenue_net,
        "hospitality_rate": hospitality_rate,
        "output_vat": output_vat,
        "input_vat_recoverable": input_vat,
        "net_vat_to_hmrc": output_vat - input_vat,
        "zero_rated_revenue": zero_rated_revenue,
        "zero_rated_share": zero_rated_revenue / revenue_net if revenue_net else 0.0,
        # Headline rate across ALL revenue, which flatters nobody and misleads
        # slightly, because business-to-business VAT is reclaimed.
        "output_vat_pct_of_revenue": output_vat / revenue_net if revenue_net else 0.0,
        # The number that matters: the rate on money a consumer hands over.
        "consumer_net_revenue": consumer_net_revenue,
        "consumer_vat": consumer_vat,
        "consumer_gross_spend": consumer_gross,
        "consumer_effective_rate_on_net": (
            consumer_vat / consumer_net_revenue if consumer_net_revenue else 0.0
        ),
        "consumer_effective_rate_on_gross": (
            consumer_vat / consumer_gross if consumer_gross else 0.0
        ),
        "kept_per_10_consumer_spend": (
            10 * consumer_net_revenue / consumer_gross if consumer_gross else 0.0
        ),
        "net_vat_pct_of_revenue": (
            (output_vat - input_vat) / revenue_net if revenue_net else 0.0
        ),
    }


def main() -> int:
    revenue_file = config.SOURCES / "chains" / "revenue_verified.json"
    if not revenue_file.exists():
        log.error(
            "%s not found.\n"
            "Run 12_chains.py, then ocr_accounts.py, check the recognised "
            "figures against the page images, and write the verified revenue "
            "table there. The model must not run on unverified OCR output.",
            revenue_file,
        )
        return 1

    data = json.loads(revenue_file.read_text(encoding="utf-8"))
    rows = []
    for slug, years in data.items():
        # Keys beginning with an underscore are the file's own documentation --
        # the basis notes and the discontinuity warnings, which matter to a
        # reader and are deliberately carried in the data file rather than
        # kept somewhere they can drift away from the numbers.
        if slug.startswith("_"):
            continue
        chain = CHAIN_STREAMS[slug]
        for year in years:
            year_end = dt.date.fromisoformat(year["year_end"])
            rate = hospitality_rate_for_year(year_end, year.get("days", 364))
            result = model_year(year["revenue_gbp"], chain["streams"], rate)
            rows.append({
                "chain": chain["name"], "slug": slug,
                "financial_year": year["label"], "year_end": year["year_end"],
                **result,
            })

    frame = pd.DataFrame(rows).sort_values(["slug", "year_end"])
    frame.to_csv(config.OUT / "chain_vat_model.csv", index=False)

    for slug, chain in CHAIN_STREAMS.items():
        sub = frame[frame.slug == slug]
        if sub.empty:
            continue
        log.info("")
        log.info("=" * 100)
        log.info("%s   [revenue mix: %s]", chain["name"], chain["source"])
        log.info("=" * 100)
        log.info("%s", chain["note"])
        log.info("")
        log.info("  Revenue mix assumed:")
        for stream, share in sorted(chain["streams"].items(), key=lambda kv: -kv[1]):
            t = TREATMENTS[stream]
            log.info("    %-30s %5.0f%%  %-14s std %3.0f%%",
                     stream, 100 * share,
                     "consumer" if t["consumer_facing"] else "business",
                     100 * t["standard_share"])
        log.info("")
        log.info("  %-10s %12s %11s %11s %11s %10s %9s",
                 "year", "net revenue", "output VAT", "input VAT", "net to HMRC",
                 "cons. rate", "kept/£10")
        for _, r in sub.iterrows():
            log.info("  %-10s %12s %11s %11s %11s %9.1f%% %9.2f",
                     r.financial_year, f"£{r.revenue_net/1e6:,.1f}m",
                     f"£{r.output_vat/1e6:,.1f}m",
                     f"£{r.input_vat_recoverable/1e6:,.1f}m",
                     f"£{r.net_vat_to_hmrc/1e6:,.1f}m",
                     100 * r.consumer_effective_rate_on_net,
                     r.kept_per_10_consumer_spend)

    log.info("")
    log.info("=" * 100)
    log.info("THE £10 TEST, most recent year, on consumer-facing sales only")
    log.info("=" * 100)
    latest = frame.sort_values("year_end").groupby("slug").tail(1)
    for _, r in latest.sort_values("kept_per_10_consumer_spend").iterrows():
        log.info("  %-34s keeps £%.2f of every £10   (zero-rated share of all "
                 "revenue: %.0f%%)",
                 r.chain, r.kept_per_10_consumer_spend, 100 * r.zero_rated_share)
    log.info("  %-34s keeps £8.33 of every £10", "A wholly standard-rated restaurant")
    log.info("  %-34s keeps £10.00 of every £10", "A wholly zero-rated counter")
    log.info("")
    log.info("=" * 100)
    log.info("GREGGS SCENARIOS -- the cooling-rule split, most recent year")
    log.info("=" * 100)
    greggs = CHAIN_STREAMS["greggs"]
    latest_greggs = frame[frame.slug == "greggs"].sort_values("year_end").iloc[-1]
    hot_share = greggs["streams"]["retail_hot_food_takeaway"]
    scenario_rows = []
    for label, kept_hot in GREGGS_KEPT_HOT_SCENARIOS.items():
        streams = dict(greggs["streams"])
        streams["retail_hot_food_takeaway"] = hot_share * kept_hot
        streams["retail_bake_cooling"] = hot_share * (1 - kept_hot)
        result = model_year(latest_greggs.revenue_net, streams,
                            latest_greggs.hospitality_rate)
        scenario_rows.append({
            "chain": greggs["name"], "financial_year": latest_greggs.financial_year,
            "scenario": label, "kept_hot_share_of_hot_food": kept_hot,
            **result,
        })
        log.info("  %-50s kept-hot %3.0f%%   keeps £%.2f of every £10   "
                 "(zero-rated share of all revenue: %.0f%%)",
                 label, 100 * kept_hot, result["kept_per_10_consumer_spend"],
                 100 * result["zero_rated_share"])
    pd.DataFrame(scenario_rows).to_csv(
        config.OUT / "chain_vat_scenarios.csv", index=False)
    log.info("")
    log.info("The spread of that table is the honest uncertainty on the Greggs "
             "figure. Print the range, not a point.")

    log.info("")
    log.info("Every VAT figure above is modelled, not disclosed. Revenue is audited.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

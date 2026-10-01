# VAT review — the twenty questions

Each question was answered against the primary source named (never a summary
site), with a short extract, citation and date. Answers: `answers-A-B-C.md` and
`answers-D-E-F-H.md`; outcomes: `STATUS.md`.

Status key: each question ends with what the report/model currently assumes,
so a "no" answer identifies exactly what must change.

---

## A. Catering and eat-in

**A1.** Are ALL supplies "in the course of catering" standard-rated regardless
of the item — including cold food consumed on premises? Confirm the wording of
VATA 1994 Sch 8 Grp 1 Note (3) and Notice 709/1 §2.
*Model assumes: eat-in 100% standard.*

**A2.** What counts as "premises" after the 2012 changes (Notes 3A–3C;
Notice 709/1) — tables outside, shared food courts, benches? Does our prose
describing "eat-in" survive a café with pavement seating?
*Report describes eat-in vs takeaway as a clean split; confirm the caveat
wording needed.*

## B. Hot takeaway and the cooling rule — decides the Greggs figures

**B1.** Confirm the five tests for "hot food" (Note 3B; Notice 709/1 §4.4 /
VFOOD4220): heated for consumption hot · heated to order · kept hot ·
heat-retentive packaging · advertised as hot — and that meeting ANY ONE makes
the sale standard-rated.
*Model assumes: any-one-met = standard.*

**B2.** Confirm the converse: an item baked on site, racked to cool, sold
without heat retention, ordinary bag, not marketed as hot, is ZERO-rated even
if warm at sale. Check current HMRC wording (VFOOD4220–4260) AND post-2012
case law (incl. Sub One Ltd (t/a Subway) v HMRC, CA 2014 — toasted subs
standard) for anything that narrows it.
*Model's "retail_bake_cooling" stream assumes: zero.*

**B3.** Toasted sandwiches, paninis, hot cabinets, rotisserie: heated to
order or kept hot = standard. Confirm each.
*Model assumes: standard (Greggs kept-hot share; Pret hot food).*

**B4.** Greggs public-record check: what can be CITED (not assumed) about
Greggs not holding savouries hot — 2012 pasty-tax consultation response,
contemporaneous statements, current product FAQ? The report may only say "a
practice Greggs has described publicly", with the citation, or must drop the
company-specific sentence and speak of "operators that rack-cool".
*Print rule: Greggs inputs are public information + stated assumptions ONLY —
see section G.*

## C. Drinks — both temperature boundaries

**C1.** Hot drinks (coffee, tea, hot chocolate) standard-rated in every
channel under current law; confirm Notice 709/1, and confirm the 2020–22
temporary reduced rate covered hot non-alcoholic drinks, so every "always"
sentence is scoped "outside 15 Jul 2020 – 31 Mar 2022".
*Model applies the reduced rate to hot drinks in that window: confirm.*

**C2.** Cold drinks: beverages are an excepted item (standard) — confirm
which cold drinks in a café basket are standard (juices, smoothies, iced
coffee, bottled water) and which escape via the overriding items (milk and
flavoured-milk drinks). Our cold-takeaway basket assumes 22% standard-rated
attachment: is the composition defensible?
*Model assumes: cold takeaway 22% standard.*

## D. Retail and wholesale streams

**D1.** Retail coffee beans, ground coffee and pods for home preparation:
zero under Sch 8 Grp 1 overriding item 5 ("coffee… and preparations and
extracts thereof"). Confirm pods; confirm ready-to-drink canned/bottled
coffee is standard (a beverage).
*Model: grocery coffee 0%, RTD 100%.*

**D2.** Wholesale bread/bakery/roasted coffee sold TO trade customers
(franchisees, supermarkets, caterers): zero as food — confirm the boundary
between "a supply of catering" and "a supply of food to a caterer".
*Model: wholesale_food_to_trade 0%, generating input-tax recovery.*

**D3.** Chilled/frozen supermarket lines ~5% standard residue
(confectionery): plausible? Adjust if not.

## E. Structure, input tax, and the B2B logic

**E1.** Franchise royalties: standard-rated; franchisee recovers in full — a
food business selling zero-rated and standard-rated supplies is fully taxable
(not partly exempt), so full recovery. Confirm.
*Model excludes all B2B VAT from consumer burden.*

**E2.** Costa Express: from PUBLIC filings/terms only — is Costa principal or
agent on the cup at third-party sites? If public information cannot settle
it, the B2B classification stays but is listed as a stated assumption with a
sensitivity line.
*Model: Express treated as B2B.*

**E3.** Repayment-trader mechanics: a business with zero-rated outputs and
standard-rated inputs recovers input tax (monthly returns available).
Confirm our neutral wording — mechanics only, no "HMRC pays it" colour.

**E4.** Input-side assumptions, documented as practice judgement: property
share bearing VAT (opt-to-tax) 55%; packaging fully standard; food inputs
~5% standard residue; staff/depreciation outside scope. Record the basis or
adjust the ranges.
*Model: COST_VAT_BEARING table; costs default 93% of revenue where notes
unread — both must appear in the assumptions appendix.*

## F. Delivery and the threshold

**F1.** Platform commission: standard-rated service to the restaurant;
restaurant is principal on the food sale under current platform agency terms
(check the platforms' published UK terms); delivered hot food standard.
Confirm all three and date-stamp the terms checked.

**F2.** Registration threshold £90,000: confirm current; confirm the
framing sentence "the boundary is a feature of registered businesses — a
business below the threshold charges no VAT on any sale and recovers none".
No wording anywhere that reads as advice to stay below it.

## G. The Greggs print protocol (public information only)

Every Greggs input in the published table carries one of two labels:

| Input | Source | Label |
|---|---|---|
| Revenue, by year | Audited accounts | disclosed |
| Retail vs B2B split (11.8% FY2025) | Segmental note in the accounts | disclosed |
| Retail format split (hot food/cold/drinks/eat-in) | Not published anywhere | assumption, stated |
| Kept-hot share of hot food | Not published anywhere | assumption, shown as 10%–100% scenario range |
| Rack-cooling practice | Public statements (cite per B4) | public record, cited |

The published sentence is a range, never a point: *"on public information
alone, Greggs retains between £8.82 and £9.34 of every £10 — where in that
range the truth sits is known only to Greggs."* The same protocol applies to
Costa, Pret and Gail's; anything not labelled disclosed is labelled assumed.

## H. Reduced-rate window and history

**H1.** Scope and dates: 5% from 15 Jul 2020, 12.5% from 1 Oct 2021, 20%
from 1 Apr 2022; covered catering, hot takeaway food, hot non-alcoholic
drinks; cold takeaway unaffected; alcohol excluded. Confirm each element.

**H2.** History line for print: hot takeaway standard-rated from 1 May 1984
(FA 1984); standard rate 15% then, 17.5% from 1991, 20% from 4 Jan 2011 —
"wide for four decades: 15 points at first, 20 since 2011". Confirm dates.

**H3.** Colour: Jaffa Cake (cake vs biscuit) and the 2012 "pasty tax"
described accurately and only as colour.

---

Completion rule: all answers filed with source extracts → the worksheet is
signed and dated → §9 of the flagship and the whole of Paper 2 unlock.
Questions answered "unclear" demote the affected claim to a stated
assumption or remove it.

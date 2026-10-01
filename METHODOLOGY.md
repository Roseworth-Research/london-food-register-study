# Methodology

*The Paper High Street* and its companion papers — version 1.0, October 2026.

Written for a reader who wants to check the work rather than take it on trust: a
referee, a statistician, a journalist with a calculator, or a competitor hoping to
find the hole. Every number below is reproducible from the code in `pipeline/`
and the public data it collects.

> **Interpretation.** The study analyses administrative records and does not
> assess the conduct of any company, director, adviser, insolvency practitioner
> or registered-office provider. Its address, company and exit classifications
> are analytical only. It does not establish whether an individual company
> traded, whether a premises opened or closed, why a company was struck off or
> moved its registered office, whether any business complied with tax law or
> engaged in tax planning, or whether anyone acted improperly. Full statement:
> [docs/INTERPRETATION.md](docs/INTERPRETATION.md).

---

## 1. Question, and how it changed

The study began with a tax hypothesis. Eat-in food is standard-rated for VAT as
catering; cold takeaway food is largely zero-rated; so a counter keeps more of each
pound than a dining room, and the post-2020 drift of London's food trade from
covers to counters might be the VAT schedule selecting the format.

Five hypotheses were written down before any data was collected, with a
commitment to publish the outcome whatever it was:

| | Hypothesis | Test | Outcome |
|---|---|---|---|
| H1 | Counter formats survive better than service formats | Kaplan–Meier, log-rank, by incorporation era | **Rejected, reversed** — counters leave the register faster in every era and specification |
| H2 | Counter formats show better net-asset growth | Median year-on-year growth, Mann–Whitney | Null — weak in direction, negligible in size |
| H3 | The counter share of new incorporations rises year on year | Annual share, Wilson intervals | **Rejected as written**; a one-off step in 2020 Q2, then drift down |
| H4 | Dying service premises are taken over by counters more than the reverse | Premises-level succession matching | Rejected — the flow runs the other way |
| H5 | The format gap narrows under the reduced hospitality VAT rate and widens after the April 2022 snapback | Quarterly death rates per 1,000 at risk | Rejected as specified; confounded by pandemic support |

The timing of the H3 step (the first lockdown, a quarter before any VAT change)
and a control test on five sectors with no food VAT boundary removed the tax
reading. What remained, and became the study, was a measurement finding: **the
company register describes legal companies, not premises, and in London's food
sector the difference changes the conclusions an analyst would draw.**

## 2. The cohort

**Industrial classification.** Every company carrying any of four SIC codes in
any of its four SIC slots:

| SIC | Description | Format |
|---|---|---|
| 56101 | Licensed restaurants | service |
| 56102 | Unlicensed restaurants and cafés | service |
| 56103 | Take-away food shops and mobile food stands | counter |
| 47240 | Retail sale of bread, cakes and confectionery | counter |

Excluded by design: 56302 (public houses and bars) and 56290 (contract
catering). Format is taken from the first cohort SIC code in slot order;
companies carrying both a counter and a service code are flagged and every
headline is re-run without them.

**Geography.** A registered office in a postcode district that touches one of
the 33 London local authorities. Some of those districts straddle the Greater
London boundary, so 4,436 companies (3.7%) sit in neighbouring authorities.
London-wide totals include them; every borough-level figure is restricted to
the 33 London authorities. 637 companies have no resolvable authority and are
excluded from borough analysis only.

**Estimand.** Companies enter the cohort by their latest registered office and
industry code. Survival estimates therefore describe companies so classified —
conditional on that later classification — not a cohort fixed at incorporation.

## 3. Sources

| Source | Used for | Collected |
|---|---|---|
| Companies House Basic Company Data (bulk CSV, 2 March 2026) | Live cohort; occupancy of every London address | Published file |
| Companies House API, `/advanced-search/companies` | Full register cohort, living and dissolved, walked by postcode district | 16–18 August 2026 |
| Companies House API, per-company filing history and charges | Exit routes, address histories, secured borrowing | 16 August – 1 October 2026 |
| Companies House Accounts Monthly Data (bulk iXBRL archives) | Balance sheets, January 2018 to July 2026 | Read by HTTP range request, not downloaded |
| ONS Postcode Directory via postcodes.io | Postcode and outward code to local authority | 16 August 2026 |
| Food Standards Agency Food Hygiene Rating Scheme open data | London food establishments and their type | 17–18 August 2026 |
| Transport for London open data | Station entries and journeys (context only) | 17 August 2026 |
| Filed annual accounts (Greggs, Pret, Costa, Gail's; Deliveroo, Uber Eats UK) | Audited revenue for the VAT model (Paper 2) | Read from the filed PDFs and checked by arithmetic |

**The observation is frozen.** Every API response and lookup is cached under
`data/raw/` on the authors' systems; the cache is not distributed
([docs/DATA-GOVERNANCE.md](docs/DATA-GOVERNANCE.md)). Full provenance of every
source is in [docs/DATA-SOURCES.md](docs/DATA-SOURCES.md). Companies House data changes daily, so an uncached pipeline is not
reproducible even in principle. The single observation date for survival is the
register walk of 18 August 2026; companies seen only in the March snapshot are
censored at 2 March 2026. Filing histories for the two postcode districts walked
last (CR0, HA0) were retrieved on 1 October 2026.

## 4. Three facts about the data that shaped the method

**The free bulk file contains no dissolved companies.** A 400,000-row sample of
the March 2026 file had no dissolution dates and no dissolved status. Any
survival analysis built on it alone is survivorship-biased by construction. All
67,155 dissolved companies in the study were requested from the register.

**The search API filters by postcode district.** The `location` parameter
matches an outward code exactly (`N12` does not return N1 or N19). Walking 302
districts with all four SIC codes per query took about 400 requests; 124 strays
whose returned postcode did not match the district were dropped.

**Registered offices move constantly.** Of companies in the March file but not
found in the August walk, a sample showed nearly all had moved. The cohort is
the union of both sources: 118,057 from the register walk plus 1,163 seen only
in the March file.

## 5. Cohort flow

| Stage | n |
|---|---|
| Companies in the March 2026 bulk file | 5,677,276 |
| Carrying a cohort SIC code | 188,858 |
| Live, in a London postcode area | 52,594 |
| Outward codes touching a London authority | 302 |
| **Register walk: living and dissolved** | **118,057** |
| — of which dissolved | 67,155 |
| Added from the March file alone (office moved) | 1,163 |
| **Master cohort** | **119,220** |
| At an address holding 10+ companies (service address) | 38,009 (31.9%) |
| Companies with at least one parsed set of accounts | 50,206 (165,052 filings) |
| Exits in the study window, classified from filing histories | 61,717 (100%) |

Status at the observation date: 45,900 active; 4,729 active with a proposal to
strike off; 1,436 in insolvency proceedings; 67,155 dissolved. The audit trail of
every stage is the `cohort_flow` table (`out/csv/cohort_flow.csv`).

## 6. Periods

| Era | From | To | Boundary event |
|---|---|---|---|
| Pre-COVID | 2018-01-01 | 2020-03-22 | Day before the first national lockdown |
| COVID | 2020-03-23 | 2021-07-18 | Lockdown to the day before Step 4 of the roadmap |
| Revival | 2021-07-19 | 2022-03-31 | Restrictions lifted, to the end of the 12.5% hospitality rate |
| Cost-of-living | 2022-04-01 | observation date | Ofgem cap +54% and hospitality VAT back to 20%, same day |

Every boundary is a dated public event. Eras are unequal in length, so every
cross-era comparison is a rate per period-year, never a raw count. Survival in
the COVID era measures policy — furlough, grants, the winding-up moratorium,
filing extensions — not business models, and is never used as evidence alone.

## 7. Outcomes and exit routes

| Outcome | Includes |
|---|---|
| alive | Active |
| closing | Active, proposal to strike off (censored, not an event — proposals are often withdrawn) |
| failing | Liquidation, administration, receivership, voluntary arrangement (an event, dated at the first insolvency filing) |
| dead | Dissolved, removed |

**Survival means remaining on the register.** An incorporation is not an
opening and a dissolution is not a closure.

**Exit routes** are classified for every exit from its complete filing history
(`pipeline/16_competing_risks.py`, rules in `exit_rules.py`):

| Route | Basis |
|---|---|
| Registrar strike-off | Compulsory gazette notices without a directors' application |
| Voluntary strike-off | Directors' application (DS01, GAZ1(A)) |
| Creditors' voluntary liquidation | CVL forms |
| Compulsory liquidation | Court winding-up order and compulsory-liquidation forms |
| Administration | Administration forms |
| Members' voluntary liquidation | A declaration of solvency — solvent, never counted as failure |
| Other insolvency | Remaining insolvency-category filings (e.g. voluntary arrangements) |

**Pre-deadline exits.** A company's first accounts fall due about 21 months
after incorporation. A removed company with no accounts on file, dissolved
before that point, is a pre-deadline exit. This describes the record only; it
makes no claim about whether the company traded.

## 8. Statistical methods

All estimators are implemented directly in `pipeline/survival.py` so the
arithmetic can be checked against a textbook without trusting a library's
defaults.

- **Survival:** Kaplan–Meier with Greenwood variance and log-log intervals;
  log-rank with tie correction; duration in days from incorporation.
- **Competing risks:** Aalen–Johansen cumulative incidence of insolvency and of
  dissolution, on an equal three-year follow-up cohort (companies incorporated
  early enough to be observed for three full years); bootstrap intervals, also
  clustered by address.
- **Composition:** stratified log-rank across era × address type × inner/outer
  London; discrete-time logistic hazard model adjusting for era, address type,
  zone and duration.
- **First-accounts frame:** survival with time zero at each company's first filed
  accounts, so that every company in the frame demonstrably filed.
- **Proportions:** Wilson intervals, exact Clopper–Pearson where counts are
  small, two-proportion z-tests.
- **Medians, not means,** for every financial measure; growth winsorised at the
  1st and 99th percentiles, opening base above £1,000, first two trading years
  excluded.

On a cohort of 119,220 almost anything is statistically significant, so every
result is reported with its effect size and the papers lead with the effect.

## 9. Addresses

**Normalisation** (`pipeline/addresses.py`): house number, street and postcode,
with unit designators and care-of agents removed. Matching prefers precision to
recall; the resulting undercount is acknowledged.

**Service addresses.** An address at which many companies are registered is a
professional office, not a shop. Every London address is counted across all 5.7
million companies in the bulk file (not just the cohort), and an address holding
10 or more companies is classified as a service address. These are excluded
from premises-level analysis only, and every headline is reported with and
without them. This is classification, not a judgement on any address provider.

**Address history.** Registered-office changes are reconstructed from each
company's change-of-address filings, so a company is placed where it was, not
where its record sits today. For insolvent companies, moves are decomposed by
timing relative to the first insolvency filing.

**The rank-reversal experiment** (`pipeline/26_rank_reversal.py`) ranks the 33
boroughs on two measures under three readings: as registered; at addresses
holding exactly one cohort company; and premises-confirmed (a selected subset,
always labelled). It reports how many boroughs move and the rank correlation
between readings. It demonstrates instability across defensible readings, not
which reading is true.

## 10. The premises linkage

Companies are linked to the Food Standards Agency register by normalised address
(`pipeline/18_fsa_premises.py`, normalised to one row per establishment in
`39_final_fixes.py`), and in the reverse direction by trading name.

- **Company side:** 37,683 companies match a food establishment on any address
  they are known to have used; 33,502 (28.1%) on their current address.
- **Establishment side:** 16,277 of 70,470 London food establishments (23.1%)
  have any cohort company registered at their address.
- **Name side:** 5,152 establishments (7.3%) trade under their company's name and
  can be resolved by name; that subset is used for the classification check and
  labelled as selected wherever it appears.

A premises match confirms a food establishment at the company's address, not
that the company operates it.

## 11. Validation

- **Exit routes:** 200 sampled exits re-derived by an independently constructed
  second classifier working from the sequence and description of filings.
  Agreement 96.5% at route level and about 99.5% at the level of insolvency
  versus dissolution; every disagreement adjudicated; one classifier gap (court
  winding-up forms) found and fixed. Worksheets: `out/validation/`.
- **Premises matches:** 200 sampled pairs scored; only six carry independent
  name evidence, which is why matches are described as address-level only.
- **Reconciliation:** every status, route and borough total is required to sum
  to its stated population; two corrections (20 and 21) came from this check.
- **Review:** the method and statistics were examined in three independent
  written reviews, each answered point by point and adopted, and the headline
  figures were audited by adversarial recomputation against the frozen database.

## 12. The VAT model (Paper 2)

Audited revenue for each operator is split into streams (eat-in, hot drinks, hot
takeaway, cold takeaway, packaged grocery, wholesale, franchise income); each
stream carries its legal rate; only consumer-facing streams enter the "£10 test",
because VAT charged to another business is recovered by it. Streams are labelled
*disclosed* where taken from a note to the filed accounts and *assumed*
otherwise. The mix is held constant across years by construction, so the
reduced-rate years measure the rate change alone. Greggs is run as a scenario
range over the share of hot food genuinely kept hot. The treatment of each
stream was checked against primary sources — twenty questions, answered with
extracts and citations in `docs/vat-review/`. Every VAT figure is modelled; no
company discloses the VAT it collects.

Every figure about a named operator is labelled as one of three kinds: a
**disclosed fact** (taken from filed accounts or another primary source), a
**model assumption** (introduced by the researchers), or a **model output**
(computed from the two). A model output is never a company's actual VAT
position, and the model makes no finding about any company's tax compliance,
planning or conduct.

## 13. Limitations

- **A company is not a business,** an incorporation is not an opening, and a
  dissolution is not a closure. Permanent and structural.
- **Registered office is not a trading address.** Premises are inferred only
  where independently confirmed, and confirmation covers a minority.
- **SIC codes are self-declared** and right roughly two-thirds to three-quarters
  of the time against the regulator's classification.
- **Unmeasured composition:** capital, founder experience and intentions are not
  observed; the adjusted model controls only for recorded characteristics.
- **Filing lag:** small companies file up to nine months after year end, so the
  latest financial year is incomplete.
- **The premises register is a current snapshot;** closed premises are invisible.
- **No causal identification of anything VAT.** Every claim about the tax
  boundary is "consistent with", never "shows".

## 14. What the study deliberately does not collect

Officer and person-with-significant-control records are on the same public
register and would allow individuals to be linked across companies. They are not
collected, and no person-level analysis is performed. No client data of any
kind enters the study. See [docs/DATA-GOVERNANCE.md](docs/DATA-GOVERNANCE.md).

## 14b. AI assistance

The research is human-directed and AI-assisted. Roseworth Research set the
questions, scope, sources, evidential standards and publication criteria, and
reviewed the work throughout; Claude (Anthropic) was used extensively for
software development, method implementation, analysis, primary-source research
and drafting. Every claim rests on public data, published code, reconciliation
and documented review. See [docs/AI-USE.md](docs/AI-USE.md).

## 15. Corrections

Twenty-one corrections were made between the first draft and version 1.0, each
recorded with its cause and effect in [docs/CORRECTIONS.md](docs/CORRECTIONS.md).

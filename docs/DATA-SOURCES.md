# Data sources and provenance

Every external source used by the study. "Cached" means the responses are stored
on the authors' systems to freeze the observation; the cache is not distributed
(see [DATA-GOVERNANCE.md](DATA-GOVERNANCE.md)).

## Administrative and open data

| Source | Publisher | Dataset / identifier | Retrieved | Observation date | Licence | Purpose | Cached |
|---|---|---|---|---|---|---|---|
| Basic Company Data | Companies House | `BasicCompanyDataAsOneFile` bulk CSV — <https://download.companieshouse.gov.uk/en_output.html> | Published 2 March 2026 | 2 March 2026 | Open Government Licence v3.0 | Live cohort; occupancy of every London address (service-address classification) | Local copy of the published file |
| Advanced company search | Companies House | Public Data API `/advanced-search/companies` — <https://developer.company-information.service.gov.uk/> | 16–18 August 2026 | 18 August 2026 | Open Government Licence v3.0 | Full cohort, living and dissolved, walked by postcode district | Yes |
| Filing history and charges | Companies House | Public Data API `/company/{number}/filing-history`, `/charges` | 16 August – 1 October 2026 (CR0 and HA0 on 1 October) | 18 August 2026 | Open Government Licence v3.0 | Exit routes, registered-office histories, insolvency dates, secured borrowing | Yes |
| Accounts Monthly Data | Companies House | Bulk iXBRL archives, January 2018 – July 2026 — <https://download.companieshouse.gov.uk/en_monthlyaccountsdata.html> | 16–18 August 2026 | Filings to July 2026 | Open Government Licence v3.0 | Balance sheets (equity, cash, creditors, employees) | Parsed extracts |
| Postcode lookups | ONS Postcode Directory, via postcodes.io | <https://postcodes.io> | 16 August 2026 | ONSPD release current at retrieval | Open Government Licence v3.0; contains OS, Royal Mail and National Statistics data | Postcode and outward code to local authority | Yes |
| Food Hygiene Rating Scheme | Food Standards Agency | Open data API, all London local authorities — <https://ratings.food.gov.uk/open-data> | 17–18 August 2026 | 18 August 2026 | Open Government Licence v3.0 | Food establishments, their type and address (premises linkage) | Yes |
| Network demand | Transport for London | Open data: station entries and journey counts — <https://tfl.gov.uk/info-for/open-data-users/> | 17 August 2026 | 2017–2025 series | TfL open data terms (Powered by TfL Open Data) | Context only | Yes |
| Control sectors | Companies House | Advanced company search, SIC 47710, 70229, 93130, 96020, 56302 | 17 August 2026 | 17 August 2026 | Open Government Licence v3.0 | Control test for formation patterns | Yes |

## Company filings (Paper 2)

| Company | Document | Retrieved | Figures used |
|---|---|---|---|
| Greggs plc (00502851) | Annual accounts FY2017–FY2025, Companies House | 16 August 2026 | Revenue; business-to-business segment share |
| Pret A Manger (Europe) Limited (01854213) | Annual accounts FY2017–FY2025, Companies House | 16 August 2026 | Revenue |
| Costa Limited (01270695) | Annual accounts FY2018–FY2024, Companies House | 16 August 2026 | Revenue |
| Bread Holdings Limited (07570780); Grain Topco Limited (13572366) — Gail's | Annual accounts FY2017–FY2025, Companies House | 16 August 2026 | Revenue; wholesale share; operating result |
| Roofoods Limited (08167130); Uber Eats UK Limited (10078453); Stuart Delivery Limited (09790251); Just Eat Limited (06947854) | Annual accounts, Companies House | 16 August 2026 | Revenue |
| Deliveroo plc (13227665) | Annual reports and accounts 2022 and 2024, Companies House | 16 August 2026 | Gross transaction value, revenue, gross profit, orders |

Revenue was read from the filed pages and checked by arithmetic against gross
profit; the figures used are in `sources/chains/revenue_verified.json`, and the
documents consulted are indexed in `sources/*/index.json`. The source PDFs are
not redistributed.

## Legal sources (VAT review)

| Source | Publisher | Checked |
|---|---|---|
| Value Added Tax Act 1994, Schedule 8 Group 1 — <https://www.legislation.gov.uk/ukpga/1994/23/schedule/8> | The National Archives | 1 October 2026 |
| VAT Notices 700, 700/1, 700/12, 701/14, 706, 709/1, 742A | HM Revenue & Customs (gov.uk) | 1 October 2026 |
| VAT Food manual (VFOOD) | HM Revenue & Customs | 1 October 2026 |
| Revenue and Customs Brief 5 (2026) | HM Revenue & Customs | 1 October 2026 |
| *Sub One Ltd v HMRC* [2014] EWCA Civ 773 | Court of Appeal (caselaw.nationalarchives.gov.uk) | 1 October 2026 |
| Deliveroo and Uber Eats published UK terms | The platforms | 1 October 2026 |

Each answer, with its extract, is in [vat-review/](vat-review/).

## Market-rate benchmarks (Paper 3)

| Source | Used for | Checked |
|---|---|---|
| IT Jobs Watch, UK data scientist contract rates (six months to 1 October 2026) | Conventional cost estimate | 1 October 2026 |
| Anaconda, *State of Data Science 2022* | Share of analyst time spent on data preparation | 1 October 2026 |
| Institute for Fiscal Studies, published salary bands | In-house cost comparison | 1 October 2026 |

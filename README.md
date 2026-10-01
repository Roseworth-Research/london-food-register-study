# The Paper High Street

**What 119,220 London food companies reveal — and why the company register
cannot be read as a map of shops.**

Code, method and outputs behind a four-paper series by Roseworth Research
(Roseworth Limited), version 1.0, October 2026. Everything here runs on free
public data: the Companies House register, filing histories and bulk accounts,
the Food Standards Agency's food hygiene register, the ONS Postcode Directory
and Transport for London open data. No client data of any kind is used.

## The papers

The study is reported in four papers, published separately by Roseworth
Research (not in this repository):

| | Paper | For |
|---|---|---|
| 0 | **London's Food Business Scorecard** — eight years of formations and removals, borough by borough | Everyone |
| 1 | **The Paper High Street** — the register is not the high street, measured | Researchers, journalists, policy |
| 2 | **The Boundary** — what the VAT schedule actually does to a food business | Operators and the trade |
| 3 | **Controlled Research at a High-Street Practice** — reproducibility, review and correction | The profession |

This repository holds the code, method, outputs and review record behind them.

## Key findings

- **Borough rankings depend materially on how registered-office addresses are
  treated.** Counted at every registered
  address, Hackney leads London on young food companies that vanish before their
  first accounts. At addresses holding a single company, Hounslow leads and
  Hackney falls to 21st of 26. Between 25 of 26 and 28 of 30 boroughs change rank
  on that one classification step; half of the affected companies sit at 418
  addresses.
- **Two in five removals never reached their first accounts** (41.9%), and 93.6%
  of removals are strike-offs; formal insolvency is 6.3%.
- **Registered-office location can change materially during insolvency
  proceedings.** 80.8% of insolvent companies moved their registered office once
  proceedings began — typically to the office administering the proceedings.
- **Registered-office data maps only partially onto physical food premises.**
  23.1% of London's 70,470 food establishments have a cohort company registered
  at their address.
- **Formats subject to different VAT treatment show different register-survival
  patterns.** Three-year register survival
  40.4% for takeaway and bakery formats against 48.9% for restaurants and cafés;
  adjusted odds of exit 1.34 [1.31–1.37]; the gap widens among companies that
  filed accounts (67.6% v 77.3%). The difference is concentrated in
  strike-off and removal rather than formal insolvency (0.28% v 0.73%).
- **The VAT thesis the study began with was rejected.** The shift to counter
  formats dates to the first lockdown, before any VAT change, and five sectors
  with no food VAT boundary show the same pattern.
- **The familiar VAT arithmetic overstates reality about threefold.** Real counter
  chains keep £8.55–£8.82 of every £10 of consumer spending, not £10.00 (Paper 2;
  modelled).

## What this study does not establish

The study does not establish whether an individual company traded, whether a
physical premises opened or closed, why a company was struck off, why its
registered office changed, whether an individual business complied with tax
law, whether a company engaged in tax planning, or whether any person or
organisation acted improperly. It does not establish any causal effect of VAT.

The study analyses administrative records only. A registered office, a change of
address, a strike-off, an absence of accounts or an insolvency filing is not
treated as evidence of misconduct, concealment, tax avoidance or non-trading, and
every VAT figure about a named company is a model output, not that company's
actual VAT position. See [docs/INTERPRETATION.md](docs/INTERPRETATION.md).

## Repository

| Path | Contents |
|---|---|
| [`METHODOLOGY.md`](METHODOLOGY.md) | Cohort, sources, definitions, estimators, validation, limitations |
| [`docs/REPRODUCING.md`](docs/REPRODUCING.md) | Setup, run order, and where each published figure comes from |
| [`docs/CORRECTIONS.md`](docs/CORRECTIONS.md) | All 21 corrections, with severity and what caught each |
| [`docs/vat-review/`](docs/vat-review/) | Twenty VAT questions answered against primary sources |
| [`docs/INTERPRETATION.md`](docs/INTERPRETATION.md) | How to read administrative records, and what the study does not establish |
| [`docs/DATA-SOURCES.md`](docs/DATA-SOURCES.md) | Every source: publisher, dates, licence, purpose |
| [`docs/DATA-GOVERNANCE.md`](docs/DATA-GOVERNANCE.md) | Public data only, no client or person-level data, cache not distributed |
| [`docs/AI-USE.md`](docs/AI-USE.md) | How Roseworth directed the work, how Claude assisted, and how results are grounded |
| `pipeline/` | The Python pipeline: steps 01–41, shared modules, and `pack_cache.py` |
| `out/` | Aggregate CSV outputs (per-borough figures in `csv/borough_sheets.csv`), charts (`charts/`, PNG and SVG), validation worksheets |
| `sources/` | Indexes of the chain and platform accounts used, and the revenue figures read from them |

Shared modules in `pipeline/`: `config.py` (every definition that shapes the
study), `survival.py` (Kaplan–Meier, log-rank, Aalen–Johansen, Wilson — written
out so they can be checked), `ch_api.py` (rate-limited, disk-cached Companies
House client), `addresses.py` (address normalisation), `exit_rules.py`
(exit-route classification), `ixbrl.py` (accounts parsing), `remote_zip.py`
(reads members of multi-gigabyte remote ZIPs by HTTP range request).

## Quick start

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
cp .env.example .env        # add a free Companies House API key
cd pipeline && python 01_cohort_live.py
```

Full sequence in [docs/REPRODUCING.md](docs/REPRODUCING.md). The raw cache that
freezes the 18 August 2026 observation is not distributed
([docs/DATA-GOVERNANCE.md](docs/DATA-GOVERNANCE.md)); a fresh run reconstructs the
study from the original public sources as they stand on the day.

## Citation

See [`CITATION.cff`](CITATION.cff).

> Roseworth Research (2026). *The Paper High Street: what 119,220 London food
> companies reveal — and why the company register cannot be read as a map of
> shops.* Version 1.0. Roseworth Limited, London.

## Disclosures

Roseworth acts for businesses in this sector and has a commercial interest in
the subject. The research is human-directed and AI-assisted: Roseworth Research
originated and directed it, and Claude (Anthropic) was used extensively as a
research, software-engineering, analytical and drafting tool under Roseworth's
direction and review. Claude is not an author, and Anthropic did not review,
commission or endorse the research; see [docs/AI-USE.md](docs/AI-USE.md).
Security reports: [SECURITY.md](SECURITY.md). Roseworth Limited is a
licensed, supervised and professionally insured accountancy practice. The
papers are general information, not advice.

## Licence

- **Code** (`pipeline/`): MIT — [LICENSE](LICENSE).
- **Documentation, outputs and the papers:** © 2026 Roseworth Limited —
  [COPYRIGHT.md](COPYRIGHT.md). Roseworth® is a registered trade mark
  (UK00004283839).
- **Third-party data:** principally the Open Government Licence v3.0 —
  [NOTICE.md](NOTICE.md).

Roseworth Limited · 662 High Road, Finchley, London N12 0NL · info@roseworth.co · www.roseworth.co

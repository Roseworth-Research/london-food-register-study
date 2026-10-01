# Reproducing version 1.0

How to rebuild the study from the original public sources and regenerate every
published figure.

## Requirements

- Python 3.12 and the packages in `requirements.txt`.
- A free Companies House API key: <https://developer.company-information.service.gov.uk/>.
- The Companies House **Basic Company Data** bulk file (one CSV, about 2.8 GB):
  <https://download.companieshouse.gov.uk/en_output.html>. The study used the file
  published on 2 March 2026.
- About 10 GB of free disk space for the local cache the pipeline builds.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt     # Windows
cp .env.example .env                                          # then add your key
```

Set `CH_SNAPSHOT_CSV` to the bulk file's path (or place it at
`data/raw/BasicCompanyDataAsOneFile-2026-03-02.csv`) and `CH_USER_AGENT` to your
own name and contact address.

## Important: the register changes daily

Companies House data changes every day. Running the pipeline today collects
today's register, not the observation of 18 August 2026 that the papers report.
Counts will differ slightly; directions and magnitudes should not. The pipeline
caches every response under `data/raw/` as it runs, so a reproduction is itself
frozen and re-runnable. The authors' original cache is not distributed
([DATA-GOVERNANCE.md](DATA-GOVERNANCE.md)).

## Run order

Run from `pipeline/`, one step at a time: the steps share one DuckDB file and
DuckDB allows one writer. Every API-bound step caches every response and is
resumable; re-running costs nothing once the cache exists.

| Step | Script | Does | Time |
|---|---|---|---|
| 1 | `01_cohort_live.py` | Live cohort from the bulk file | 5 min |
| 2 | `02_districts.py` | Which postcode districts are London | 3 min |
| 3 | `03_cohort_register.py` | Register walk, living and dissolved, by district | 5 min |
| 4 | `04_boroughs.py` | Postcode to borough | 3 min |
| 5 | `05_address_hubs.py` | Companies per address; service addresses | 2 min |
| 6 | `06_labels.py` | Master table, fully labelled | 1 min |
| 7 | `07_life_history.py --scope exits` then `--scope live` | Filing histories and charges | hours (rate-limited) |
| 8 | `08_accounts.py`, then `08_accounts.py --load` | Balance sheets from the bulk iXBRL archives | ~2.5 h |
| 9 | `09_succession.py` | What replaced what, premises by premises | 1 min |
| 10 | `10_analysis.py` | Hypothesis tests | 1 min |
| 11 | `11_exports.py` | Plain-number CSV exports | 1 min |
| 12–14 | `12_chains.py`, `ocr_accounts.py`, `ocr_notes.py`, `13_vat_model.py`, `14_platforms.py` | Chain and platform accounts; the VAT model (Paper 2) | 30 min |
| 15 | `15_demand.py` | Transport for London context | 5 min |
| 16 | `16_competing_risks.py` | Exit routes; competing risks | 1 min |
| 17 | `17_filing_footprint.py` | Filing behaviour per company | 30 min |
| 18 | `18_fsa_premises.py` | Premises linkage | 10 min |
| 19 | `19_map_data.py` | Borough metrics for the map | 1 min |
| 20 | `20_address_history.py` | Registered-office histories | 30 min |
| 21 | `21_located_cohort.py` | Where each company was; premises tiers | 1 min |
| 22 | `22_robustness.py` | Robustness battery | 1 min |
| 23–24 | `23_control_sector.py`, `24_control_register.py` | Control sectors from the register | 25 min |
| 26–31 | `26_rank_reversal.py` … `31_fsa_reverse_full.py` | Rank reversal, address timing, stratified survival, reverse linkage | 15 min |
| 32–36, 38 | `32_validation_sheets.py` … `36_frameworks_growth.py`, `38_assisted_validation.py` | Validation samples, charges, balance-sheet series, assisted validation | 15 min |
| 39 | `39_final_fixes.py` | One row per establishment; insolvency event dates | 35 min |
| 40–41 | `40_paper_charts.py`, `41_paper2_charts.py` | Every chart in the papers (PNG and vector SVG) | 1 min |
| 42 | `42_borough_sheets.py` | Canonical per-borough file: 33 boroughs, ONS GSS codes, both readings, denominators and floors | 1 min |

Steps not listed in the table above (for example `37_predictions.py`) are not
needed to reproduce any published figure.

After step 39, re-run the steps that depend on it, in this order:

```bash
python 18_fsa_premises.py && python 39_final_fixes.py && python 21_located_cohort.py \
 && python 16_competing_risks.py && python 10_analysis.py && python 26_rank_reversal.py \
 && python 27_address_timing.py && python 28_stratified_survival.py && python 29_robustness_extra.py \
 && python 33_charges_summary.py && python 34_balance_sheets_by_sic.py && python 22_robustness.py \
 && python 11_exports.py && python 40_paper_charts.py && python 41_paper2_charts.py \n && python 42_borough_sheets.py
```

## Where each published figure comes from

| Figure | Source |
|---|---|
| Formations, removals, routes, borough table (Paper 0) | Database: `companies` and `company_exit_v2` tables |
| Three-year survival, robustness | `10_analysis.py`, `29_robustness_extra.py` |
| Adjusted odds, stratified O/E | `28_stratified_survival.py` |
| First-accounts survival; bakery 75.5% | `34_balance_sheets_by_sic.py` |
| Insolvency incidence and interval | `16_competing_risks.py` |
| Address-move timing | `27_address_timing.py` |
| Rank reversal, 418 addresses | `26_rank_reversal.py` |
| Premises linkage, 23.1% | `39_final_fixes.py`, `31_fsa_reverse_full.py` |
| Control sectors | `24_control_register.py` |
| Per-borough figures | `42_borough_sheets.py` → `out/csv/borough_sheets.csv` |
| VAT model, £10 test, Greggs range | `13_vat_model.py` → `out/csv/chain_vat_model.csv` |

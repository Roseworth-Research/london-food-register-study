# Corrections log

Every correction made between the first draft and version 1.0, with its
severity and the control that caught it. Severity is judged by what would have
reached print:

- **Headline** — a headline figure or direction in a published paper would have been wrong.
- **Count** — a count, label or table.
- **Claim** — a sentence that said more than the evidence allowed.

| # | What was wrong | What changed | Severity | Caught by |
|---|---|---|---|---|
| 1 | Kaplan–Meier treated strike-off as censoring when it is a competing exit | Replaced by Aalen–Johansen cumulative incidence | Headline | Independent review |
| 2 | A prefix match on gazette form GAZ1 also captured the voluntary GAZ1(A) | All exits reclassified; registrar and voluntary strike-off separated | Count | Development checks |
| 3 | Premises address keys built from the first address line only | Match rate at ordinary addresses rose from 1.4% to 30.4% | Count | Development checks |
| 4 | Current registered office used as the historical location | Address histories reconstructed from change-of-address filings | Count | Development checks |
| 5 | A weak accounts tag (working capital) overwrote shareholders' equity in 88% of figures | Equity preferred; balance-sheet series rebuilt | Count | Development checks |
| 6 | "2.7 times the secured borrowing" was 2.7 times the proportion with a charge | Restated as proportions only | Claim | Development checks |
| 7 | An ordering built during analysis was described as predicted in advance | Relabelled as exploratory | Claim | Independent review |
| 8 | Conditional insolvency computed on exited filers, not all filers | Recomputed on all filers; earlier figures withdrawn | Headline | Independent review |
| 9 | A stale snapshot "proposal to strike off" label overrode the register's later "dissolved" | 2,211 companies relabelled; counts reconcile | Count | Independent review (reconciliation) |
| 10 | The solvent members'-voluntary-liquidation branch of the classifier was unreachable | 134 solvent wind-ups no longer counted as insolvency | Headline | Adversarial recomputation |
| 11 | Survivors censored at one date, deaths counted to another | Single observation window; every survival level re-estimated | Headline | Adversarial recomputation |
| 12 | Two postcode districts (CR0, HA0) never collected — a loop began at one, not zero | Districts walked; cohort 116,411 → 119,220 | Headline | Adversarial recomputation |
| 13 | An address-move statistic (87.8%) not decomposed by timing | Moves after insolvency proceedings reported separately (now 80.8%) | Count | Independent review |
| 14 | A survival cut on a live-register field; a loan metric with near-zero data coverage | Both analyses discarded | Claim | Development checks |
| 15 | Certain court winding-up forms missed by the exit classifier | Classifier fixed | Count | Assisted validation |
| 16 | A register-stock projection that made older companies immortal | Projection withdrawn | Claim | Independent review |
| 17 | Bakery retail's raw survival written up as trading failure | Conditioned on filing, bakeries perform like cafés; claim withdrawn | Claim | Development checks |
| 18 | The premises table counted candidate address keys, not establishments | 231,089 rows were 70,470 establishments; establishment-side figures corrected | Headline | Independent review |
| 19 | Exits in live insolvency proceedings timed at the observation date | Event dates read from the first insolvency filing | Headline | Independent review |
| 20 | Filing histories never retrieved for the 1,452 exits in CR0 and HA0, so their routes were unclassified | Histories retrieved 1 October 2026; all 61,717 exits classified; downstream chain re-run | Headline | Pre-publication reconciliation |
| 21 | The leading borough on pre-deadline exits (Newham, 49.5%) was carried over from an early draft | Restated from the final output: Hounslow, 43.3% | Headline | Pre-publication reconciliation |

**Tally:** 8 caught by independent review; 3 by adversarial recomputation; 3 by
validation and reconciliation; 7 during development. Nine were headline errors.

## Figures that moved between the August draft and version 1.0

| Figure | August draft | Version 1.0 | Cause |
|---|---|---|---|
| Three-year register survival, counter v service | 40.6% v 49.4% (gap 8.8) | 40.4% v 48.9% (gap 8.5) | 19 |
| Adjusted odds of exit, counter formats | 1.348 | 1.336 [1.305, 1.368] | 19 |
| Three-year insolvency incidence | 0.13% v 0.35% | 0.28% v 0.73%; difference 0.45 pp [0.33, 0.56] | 19, 20 |
| Exits classified | 60,265 | 61,717 | 20 |
| Insolvent companies moving office after proceedings began | 81.1% of 4,882 | 80.8% of 4,929 | 20 |
| Rank correlation, survival measure | 0.498 | 0.525 | 19, 20 |
| Leading borough, pre-deadline exits at single-company addresses | Newham 49.5% | Hounslow 43.3% | 21 |
| Costa, kept per £10 (Paper 2) | £8.51 | £8.55 | VAT review D1: cold ready-to-drink coffee is zero-rated |

Every direction and every robustness result held through all corrections.

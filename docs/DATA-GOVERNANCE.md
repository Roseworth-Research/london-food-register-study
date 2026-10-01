# Data governance

## Sources

Every analytical source is public. The study uses Companies House records, the
Food Standards Agency's food hygiene register, the ONS Postcode Directory,
Transport for London open data and companies' filed annual accounts. Each source
is listed, with its licence and observation date, in
[DATA-SOURCES.md](DATA-SOURCES.md).

## What is not used

- **No Roseworth client data** of any kind — not raw, not aggregated, not as
  validation. Roseworth's knowledge of its own clients played no part in any
  figure.
- **No person-level data.** Officer and person-with-significant-control records
  are published on the same register and would allow individuals to be linked
  across companies. They are not collected.
- **No individual profiling.** No analysis is performed on, or reported about,
  any named individual. Company-level records are aggregated into counts, rates
  and distributions; individual companies appear only in the validation
  worksheets, which record public register entries used to check the classifiers.

## Interpreting the records

Administrative records describe filings, not behaviour. A strike-off, a change of
registered office, an absence of accounts or an insolvency filing is not
evidence of how any business traded or why. See
[INTERPRETATION.md](INTERPRETATION.md).

## The cache

Every API response the study used is cached on the authors' systems, so that the
published figures can be recomputed from the same observation. **The raw cache
is not distributed.** It contains complete filing histories, and those include
the names of individuals as they appear on public filings. Holding it is
appropriate for reproducibility; redistributing it as a dataset is not.

Anyone wishing to reproduce the study should reconstruct it from the original
public sources with the code in `pipeline/` ([REPRODUCING.md](REPRODUCING.md)).
Because the public register changes daily, a fresh run reflects the register on
the day it runs; counts will differ slightly from the 18 August 2026 observation,
while directions and magnitudes should not.

## What is published here

Only aggregate outputs (`out/csv/`), charts (`out/charts/`), the validation
worksheets (`out/validation/`), revenue figures read from filed company accounts
(`sources/`) and the code. None contains personal data beyond company names and
numbers already published on the public register.

## Licences and attribution

See [NOTICE.md](../NOTICE.md).

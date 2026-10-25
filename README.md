# VitalStream

A serverless healthcare data pipeline on AWS. It ingests synthetic FHIR R4 patient records, validates them, and publishes SQL-queryable Parquet tables in a bronze/silver/gold layout.

> All data is synthetic, generated with [Synthea](https://github.com/synthetichealth/synthea). No real patient data is used.

## Architecture

```
Synthea (local) -> S3 raw (bronze) -> Lambda (Python: parse, flatten, validate)
   -> S3 curated (silver, Parquet) -> Glue Catalog + Athena (SQL) -> gold tables
Bad records -> quarantine/ with a reason. Record counts -> CloudWatch.
```

## Stack

Python (pandas, pyarrow) · SQL (Athena, DuckDB locally) · AWS S3, Lambda, Glue Data Catalog, Athena, CloudWatch, CloudTrail · AWS SAM · GitHub Actions · FHIR R4

## Project layout

```
scripts/      Data generation and inspection helpers
src/ingest/   Lambda code: FHIR parsing and data quality checks
sql/          Athena table definitions and analytics queries
tests/        pytest unit tests
data/raw/     Local Synthea output (not committed)
docs/         Architecture diagram and screenshots
```

## Generate the data

Requires Java 17+ and Python 3.12. The script downloads a pinned Synthea release (checksum verified) and produces identical output on every run.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\generate_synthea.ps1   # 100 patients (+ deceased), ~45 s
py -3.12 scripts/inspect_bundle.py                                         # readable summary of one bundle
```

## Status

- [x] Phase 1: Setup
- [x] Phase 2: Generate synthetic data
- [ ] Phase 3: Ingest pipeline (bronze to silver)
- [ ] Phase 4: SQL analytics (gold)
- [ ] Phase 5: Security, IaC, CI, polish

## Cost

Built on the AWS Free plan. No Glue crawlers, small dataset, stack deleted after demo.

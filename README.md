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
scripts/         Data generation, local pipeline runs, gold builds
src/ingest/      Lambda code: FHIR parsing and data quality checks
src/analytics/   Athena catalog generation and local DuckDB runner
sql/             gold/ and analytics/ queries; athena/ generated DDL + CTAS
tests/           pytest unit tests
data/raw/        Local Synthea output (not committed)
docs/            Architecture diagram and screenshots
```

## Generate the data

Requires Java 17+ and Python 3.12. The script downloads a pinned Synthea release (checksum verified) and produces identical output on every run.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\generate_synthea.ps1   # 100 patients (+ deceased), ~45 s
py -3.12 scripts/inspect_bundle.py                                         # readable summary of one bundle
```

## Run the pipeline locally

Same code as the Lambda; a local folder stands in for the curated bucket.

```powershell
.\.venv\Scripts\Activate.ps1
python -m pytest                     # unit tests (no data or AWS needed)
python scripts/run_local.py          # bronze JSON -> data/curated/silver (Parquet) + quarantine (JSONL)
python scripts/check_silver.py       # DuckDB: row counts, unique keys, joins
```

Silver tables (`silver/<table>/ingest_date=YYYY-MM-DD/*.parquet`):

| Table | Grain | Notes |
|---|---|---|
| patients | one per patient | names, identifiers and street address dropped (data minimization) |
| encounters | one per visit | timestamps converted to UTC |
| observations | one per measurement | blood pressure split into systolic/diastolic rows sharing `observation_id` |
| conditions | one per diagnosis | `semantic_tag` separates disorders from findings |

Records that fail a data quality rule go to `quarantine/` with a reason (for example `invalid_timestamp` or `orphan_encounter`); the rest of the bundle still loads. `python scripts/make_bad_bundles.py` creates broken bundles to try it.

## SQL analytics (gold)

Each gold table is one SELECT in [`sql/gold/`](sql/gold/), written once and run by **DuckDB locally** and by **Athena CTAS** in AWS.

```powershell
python scripts/build_gold.py         # silver -> data/curated/gold (Parquet)
python scripts/run_queries.py        # business questions in sql/analytics/
python scripts/render_athena.py      # writes sql/athena/*.sql (no AWS calls)
```

| Gold table | What it answers | SQL skills |
|---|---|---|
| patient_summary | one row per patient: age, visits, chronic conditions, latest vitals | CTEs, LEFT JOIN, FILTER, ROW_NUMBER |
| encounters_monthly | visits per month and class, month-over-month change, YTD total | date_trunc, LAG, running SUM |
| condition_prevalence | how common each disorder is, ranked | COUNT DISTINCT, DENSE_RANK |
| a1c_trend | every HbA1c result vs the previous one, rolling average, clinical band | LAG, moving AVG, partitioned by year |

Design notes:
- Athena tables are generated from the same schemas as the Parquet files, with **partition projection** (no Glue crawler needed).
- Silver has an `_all` table (every load) and a view that keeps only the latest copy of each record, so re-processing a file never double-counts.
- Silver is partitioned by load date, gold by event date (`a1c_trend` by `result_year`).
- SQL sticks to syntax both engines share; a test fails on DuckDB-only syntax such as `::` casts or `QUALIFY`.

## Status

- [x] Phase 1: Setup
- [x] Phase 2: Generate synthetic data
- [x] Phase 3: Ingest pipeline (bronze to silver)
- [x] Phase 4: SQL analytics (gold)
- [ ] Phase 5: Security, IaC, CI, polish

## Cost

Built on the AWS Free plan. No Glue crawlers, small dataset, stack deleted after demo.

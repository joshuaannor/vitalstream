"""Gold SQL and Athena DDL, tested in DuckDB on the sample bundle (no AWS needed)."""

import copy
import re
from datetime import date

import pytest

from analytics.catalog import BUCKET_PLACEHOLDER, athena_silver_ddl
from analytics.gold import athena_ctas, load_analytics_queries, load_gold_queries
from analytics.local import build_gold, connect, output_columns
from ingest.pipeline import process_bundle
from ingest.schemas import SCHEMAS
from ingest.writer import LocalSink, write_result
from samples import TODAY, find, make_bundle, raw


@pytest.fixture(scope="module")
def curated(tmp_path_factory):
    bundle = make_bundle()
    # A second, later HbA1c test (no encounter) so trends have something to compare
    a1c_2 = copy.deepcopy(find(bundle, "obs-a1c"))
    a1c_2.update(id="obs-a1c-2", effectiveDateTime="2018-03-06T05:24:59-05:00",
                 valueQuantity={"value": 6.6, "unit": "%"})
    del a1c_2["encounter"]
    # A disorder (the sample's prediabetes is a "finding")
    htn = copy.deepcopy(find(bundle, "cond-1"))
    htn.update(id="cond-2", code={"coding": [{"system": "http://snomed.info/sct", "code": "59621000",
                                              "display": "Essential hypertension (disorder)"}]})
    bundle["entry"] += [{"resource": a1c_2}, {"resource": htn}]

    result = process_bundle(raw(bundle), "bronze/test.json", TODAY)
    assert result.counts()["quarantined"] == 0
    root = tmp_path_factory.mktemp("curated")
    sink = LocalSink(root)
    # The same bundle loaded on two days: the latest-record views must hide the older copy
    write_result(result, sink, date(2026, 10, 1), "day1")
    write_result(result, sink, date(2026, 10, 2), "day2")
    return root


@pytest.fixture(scope="module")
def con(curated):
    con = connect(curated)
    build_gold(con, load_gold_queries(), curated / "gold")
    return con


def rows(con, sql: str) -> list[dict]:
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def scalar(con, sql: str):
    return con.execute(sql).fetchall()[0][0]


# --- Silver views -----------------------------------------------------------

def test_latest_views_hide_reprocessed_copies(con):
    assert scalar(con, "SELECT count(*) FROM vitalstream_silver.patients_all") == 2
    assert scalar(con, "SELECT count(*) FROM vitalstream_silver.patients") == 1
    assert scalar(con, "SELECT count(*) FROM vitalstream_silver.observations") == 5
    assert str(scalar(con, "SELECT ingest_date FROM vitalstream_silver.patients")) == "2026-10-02"


# --- Gold tables ------------------------------------------------------------

def test_patient_summary(con):
    [p] = rows(con, "SELECT * FROM vitalstream_gold.patient_summary")
    # Born 1985-12-23; "today" = latest visit 2017-03-06 -> birthday not reached yet -> 31
    assert p["age_years"] == 31
    assert p["age_group"] == "18-39"
    assert p["encounter_count"] == 1
    assert p["has_prediabetes"] is True and p["has_hypertension"] is True and p["has_diabetes"] is False
    assert p["active_disorders"] == 1          # hypertension counts, prediabetes (a finding) doesn't
    assert (p["latest_systolic"], p["latest_diastolic"]) == (121.0, 82.0)
    assert p["latest_bmi"] is None


def test_a1c_trend(con):
    first, second = rows(con, "SELECT * FROM vitalstream_gold.a1c_trend ORDER BY test_number")
    assert (first["test_number"], first["previous_a1c_pct"], first["a1c_band"]) == (1, None, "prediabetes")
    assert second["previous_a1c_pct"] == 5.96
    assert second["change_pct_points"] == 0.64
    assert second["rolling_avg_3"] == 6.28
    assert second["a1c_band"] == "diabetes"
    assert second["result_year"] == 2018


def test_condition_prevalence_counts_disorders_only(con):
    [c] = rows(con, "SELECT * FROM vitalstream_gold.condition_prevalence")
    assert c["code"] == "59621000"
    assert (c["patients_ever"], c["pct_ever"], c["rank_ever"]) == (1, 100.0, 1)


def test_encounters_monthly(con):
    [m] = rows(con, "SELECT * FROM vitalstream_gold.encounters_monthly")
    assert str(m["month"]) == "2017-03-01"
    assert (m["class_code"], m["encounters"], m["ytd_encounters"]) == ("AMB", 1, 1)
    assert m["avg_duration_min"] == pytest.approx(51.35, abs=0.1)  # 05:24:59 -> 06:16:20
    assert m["change_vs_prev_month"] is None


def test_partition_column_is_selected_last(con):
    for q in load_gold_queries():
        if q.partitioned_by:
            assert output_columns(con, q.sql)[-1] == q.partitioned_by


def test_analytics_queries_run(con):
    queries = load_analytics_queries()
    assert queries
    for q in queries:
        con.execute(q.sql).fetchall()


# --- Portability: SQL must run on both DuckDB and Athena (Trino) ---------------

DUCKDB_ONLY = {
    r"::": "use CAST(x AS type)",
    r"\bQUALIFY\b": "filter ROW_NUMBER() in a subquery",
    r"\bEXCLUDE\b": "list columns explicitly",
    r"GROUP\s+BY\s+ALL": "list grouping columns",
    r"date_diff\(\s*'(year|month|day)'": "unit boundaries differ between engines",
}


@pytest.mark.parametrize("q", load_gold_queries() + load_analytics_queries(), ids=lambda q: q.name)
def test_sql_avoids_duckdb_only_syntax(q):
    code = "\n".join(line.split("--")[0] for line in q.sql.splitlines())  # ignore comments
    for pattern, advice in DUCKDB_ONLY.items():
        assert not re.search(pattern, code, re.IGNORECASE), f"{q.name}: {pattern!r} ({advice})"


# --- Athena DDL ---------------------------------------------------------------

def test_athena_silver_ddl_matches_schemas():
    stmts = athena_silver_ddl()
    assert len(stmts) == 2 + 2 * len(SCHEMAS)   # 2 databases + (table + view) per silver table
    for table, schema in SCHEMAS.items():
        [ddl] = [s for s in stmts if f"vitalstream_silver.{table}_all (" in s]
        for field in schema:
            assert f"    {field.name} " in ddl
        assert f"s3://{BUCKET_PLACEHOLDER}/silver/{table}/" in ddl
        assert "'projection.enabled' = 'true'" in ddl


def test_athena_ctas():
    by_name = {q.name: q for q in load_gold_queries()}
    drop, create = athena_ctas(by_name["a1c_trend"], bucket="my-bucket")
    assert drop == "DROP TABLE IF EXISTS vitalstream_gold.a1c_trend"
    assert "external_location = 's3://my-bucket/gold/a1c_trend/'" in create
    assert "partitioned_by = ARRAY['result_year']" in create
    assert "partitioned_by = ARRAY" not in athena_ctas(by_name["patient_summary"])[1]

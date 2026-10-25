"""Catalog SQL generated from the silver schemas, so Athena and DuckDB never drift apart.

Two layers per silver table:
    <table>_all   external table over every ingest_date partition (raw history)
    <table>       view keeping only the latest version of each record (dedup)
"""

import pyarrow as pa

from ingest.schemas import PRIMARY_KEYS, SCHEMAS

SILVER_DB = "vitalstream_silver"
GOLD_DB = "vitalstream_gold"
BUCKET_PLACEHOLDER = "<CURATED_BUCKET>"

_HIVE_TYPES = {
    pa.string(): "string",
    pa.float64(): "double",
    pa.date32(): "date",
    pa.timestamp("ms"): "timestamp",
}


def hive_type(arrow_type: pa.DataType) -> str:
    return _HIVE_TYPES[arrow_type]


def latest_view_sql(table: str, source: str) -> str:
    """View with one row per primary key: the copy from the most recent ingest_date.

    If a bundle is re-processed on a later day, both copies exist in <table>_all;
    ROW_NUMBER() picks the newest. Same SQL runs on DuckDB and Athena.
    """
    cols = ", ".join([*SCHEMAS[table].names, "ingest_date"])
    keys = ", ".join(PRIMARY_KEYS[table])
    return (
        f"CREATE OR REPLACE VIEW {SILVER_DB}.{table} AS\n"
        f"SELECT {cols}\n"
        f"FROM (\n"
        f"    SELECT *, row_number() OVER (PARTITION BY {keys} ORDER BY ingest_date DESC) AS rn\n"
        f"    FROM {source}\n"
        f") latest\n"
        f"WHERE rn = 1"
    )


def athena_silver_ddl(bucket: str = BUCKET_PLACEHOLDER) -> list[str]:
    """CREATE DATABASE / EXTERNAL TABLE / VIEW statements for Athena, in run order.

    Partition projection computes ingest_date partitions from the folder pattern,
    so no Glue crawler or MSCK REPAIR TABLE is needed.
    """
    stmts = [f"CREATE DATABASE IF NOT EXISTS {SILVER_DB}", f"CREATE DATABASE IF NOT EXISTS {GOLD_DB}"]
    for table, schema in SCHEMAS.items():
        location = f"s3://{bucket}/silver/{table}/"
        cols = ",\n".join(f"    {field.name} {hive_type(field.type)}" for field in schema)
        stmts.append(
            f"CREATE EXTERNAL TABLE IF NOT EXISTS {SILVER_DB}.{table}_all (\n{cols}\n)\n"
            f"PARTITIONED BY (ingest_date string)\n"
            f"STORED AS PARQUET\n"
            f"LOCATION '{location}'\n"
            f"TBLPROPERTIES (\n"
            f"    'projection.enabled' = 'true',\n"
            f"    'projection.ingest_date.type' = 'date',\n"
            f"    'projection.ingest_date.format' = 'yyyy-MM-dd',\n"
            f"    'projection.ingest_date.range' = '2026-01-01,NOW',\n"
            f"    'projection.ingest_date.interval' = '1',\n"
            f"    'projection.ingest_date.interval.unit' = 'DAYS',\n"
            f"    'storage.location.template' = '{location}ingest_date=${{ingest_date}}/'\n"
            f")"
        )
        stmts.append(latest_view_sql(table, f"{SILVER_DB}.{table}_all"))
    return stmts

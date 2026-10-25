"""Local stand-in for Glue Catalog + Athena: DuckDB over the Parquet files in data/curated."""

import shutil
from pathlib import Path

import duckdb
import pyarrow as pa

from analytics.catalog import GOLD_DB, SILVER_DB, latest_view_sql
from analytics.gold import SqlFile
from ingest.schemas import SCHEMAS


def connect(curated: Path) -> duckdb.DuckDBPyConnection:
    """DuckDB with the same schema and table names as Athena (silver views + any built gold)."""
    con = duckdb.connect()
    con.execute(f"CREATE SCHEMA {SILVER_DB}")
    con.execute(f"CREATE SCHEMA {GOLD_DB}")
    silver = Path(curated) / "silver"
    for table, schema in SCHEMAS.items():
        source = f"{SILVER_DB}.{table}_all"
        if any((silver / table).glob("*/*.parquet")):
            con.execute(
                f"CREATE VIEW {source} AS SELECT * FROM read_parquet("
                f"'{(silver / table).as_posix()}/*/*.parquet', hive_partitioning = true)")
        else:  # no data yet: empty table with the right columns
            empty = schema.append(pa.field("ingest_date", pa.string())).empty_table()
            con.register(f"empty_{table}", empty)
            con.execute(f"CREATE VIEW {source} AS SELECT * FROM empty_{table}")
        con.execute(latest_view_sql(table, source))
    attach_gold(con, Path(curated) / "gold")
    return con


def attach_gold(con: duckdb.DuckDBPyConnection, gold_root: Path) -> None:
    """Expose each built gold table as vitalstream_gold.<name>."""
    for folder in sorted(p for p in gold_root.glob("*") if p.is_dir()):
        if any(folder.rglob("*.parquet")):
            con.execute(
                f"CREATE OR REPLACE VIEW {GOLD_DB}.{folder.name} AS SELECT * FROM read_parquet("
                f"'{folder.as_posix()}/**/*.parquet', hive_partitioning = true)")


def wrap(sql: str) -> str:
    """Put a query inside brackets on its own lines (a trailing -- comment would eat the ')')."""
    return f"(\n{sql}\n)"


def output_columns(con: duckdb.DuckDBPyConnection, sql: str) -> list[str]:
    return [d[0] for d in con.execute(f"SELECT * FROM {wrap(sql)} q LIMIT 0").description]


def check_partition_last(con: duckdb.DuckDBPyConnection, query: SqlFile) -> None:
    """Athena CTAS requires partition columns to be the last ones selected."""
    if query.partitioned_by:
        cols = output_columns(con, query.sql)
        if cols[-1] != query.partitioned_by:
            raise ValueError(f"{query.name}: partition column {query.partitioned_by!r} "
                             f"must be selected last (last is {cols[-1]!r})")


def build_gold(con: duckdb.DuckDBPyConnection, queries: list[SqlFile], gold_root: Path) -> dict[str, int]:
    """Run each gold query and write it as Parquet (Hive-partitioned if configured)."""
    counts = {}
    for q in queries:
        check_partition_last(con, q)
        out = Path(gold_root) / q.name
        shutil.rmtree(out, ignore_errors=True)
        out.parent.mkdir(parents=True, exist_ok=True)
        if q.partitioned_by:
            con.execute(f"COPY {wrap(q.sql)} TO '{out.as_posix()}' "
                        f"(FORMAT parquet, PARTITION_BY ({q.partitioned_by}))").fetchall()
        else:
            out.mkdir()
            con.execute(f"COPY {wrap(q.sql)} TO '{(out / 'data.parquet').as_posix()}' "
                        f"(FORMAT parquet)").fetchall()
        counts[q.name] = con.execute(f"SELECT count(*) FROM {wrap(q.sql)} q").fetchall()[0][0]
    attach_gold(con, gold_root)
    return counts


def format_rows(cursor, max_width: int = 28) -> str:
    """Plain-text table (no box-drawing characters, so it prints in any Windows console)."""
    headers = [d[0] for d in cursor.description]
    rows = [["" if v is None else (f"{v:.2f}" if isinstance(v, float) else str(v))[:max_width] for v in row]
            for row in cursor.fetchall()]
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]
    lines = ["  ".join(h.ljust(w) for h, w in zip(headers, widths)),
             "  ".join("-" * w for w in widths)]
    lines += ["  ".join(v.ljust(w) for v, w in zip(r, widths)) for r in rows]
    return "\n".join(lines) + f"\n({len(rows)} rows)"

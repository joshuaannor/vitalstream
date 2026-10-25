"""Gold tables: one SELECT per file in sql/gold/, run by DuckDB locally and by Athena CTAS in AWS.

Each file starts with comment headers:
    -- <one-line description>
    -- partitioned_by: <column>     (or "none"; the column must be the last one selected)
"""

import re
from dataclasses import dataclass
from pathlib import Path

from analytics.catalog import BUCKET_PLACEHOLDER, GOLD_DB

REPO = Path(__file__).resolve().parents[2]
GOLD_SQL_DIR = REPO / "sql" / "gold"
ANALYTICS_SQL_DIR = REPO / "sql" / "analytics"

_META = re.compile(r"^--\s*(\w+):\s*(.+?)\s*$", re.MULTILINE)


@dataclass
class SqlFile:
    name: str
    description: str
    sql: str
    partitioned_by: str | None = None


def load_sql_files(folder: Path) -> list[SqlFile]:
    files = []
    for path in sorted(folder.glob("*.sql")):
        text = path.read_text(encoding="utf-8").strip()
        meta = dict(_META.findall(text))
        partition = meta.get("partitioned_by")
        first_line = text.splitlines()[0]
        files.append(SqlFile(
            name=path.stem,
            description=first_line.lstrip("- ").strip(),
            sql=text.rstrip(";"),
            partitioned_by=None if partition in (None, "none") else partition,
        ))
    return files


def load_gold_queries() -> list[SqlFile]:
    return load_sql_files(GOLD_SQL_DIR)


def load_analytics_queries() -> list[SqlFile]:
    return load_sql_files(ANALYTICS_SQL_DIR)


def athena_ctas(query: SqlFile, bucket: str = BUCKET_PLACEHOLDER) -> list[str]:
    """DROP + CREATE TABLE AS SELECT for Athena.

    Note: DROP TABLE leaves the old files in S3, and CTAS fails if its location
    isn't empty, so the old gold/<name>/ prefix must be emptied before re-running.
    """
    props = [
        "format = 'PARQUET'",
        "write_compression = 'SNAPPY'",
        f"external_location = 's3://{bucket}/gold/{query.name}/'",
    ]
    if query.partitioned_by:
        props.append(f"partitioned_by = ARRAY['{query.partitioned_by}']")
    with_clause = ",\n    ".join(props)
    return [
        f"DROP TABLE IF EXISTS {GOLD_DB}.{query.name}",
        f"CREATE TABLE {GOLD_DB}.{query.name}\nWITH (\n    {with_clause}\n)\nAS\n{query.sql}",
    ]

"""Write a BundleResult as Parquet (silver) and JSON Lines (quarantine).

Layout, identical locally and in S3:
    silver/<table>/ingest_date=YYYY-MM-DD/<file_id>.parquet
    quarantine/ingest_date=YYYY-MM-DD/<file_id>.jsonl

file_id is a hash of the source file name, so re-processing a bundle overwrites
its own output instead of duplicating it (idempotent).
"""

import hashlib
import json
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ingest.pipeline import BundleResult
from ingest.schemas import SCHEMAS


def file_id_for(source_file: str) -> str:
    return hashlib.sha256(source_file.encode("utf-8")).hexdigest()[:16]


def to_parquet_bytes(table: str, df) -> bytes:
    arrow = pa.Table.from_pandas(df, schema=SCHEMAS[table], preserve_index=False)
    buf = pa.BufferOutputStream()
    pq.write_table(arrow, buf, compression="snappy")
    return buf.getvalue().to_pybytes()


class LocalSink:
    """Writes keys as files under a root folder (local stand-in for the curated bucket)."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def put(self, key: str, data: bytes) -> None:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


class S3Sink:
    """Writes keys as objects in an S3 bucket."""

    def __init__(self, bucket: str, client):
        self.bucket = bucket
        self.client = client

    def put(self, key: str, data: bytes) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data)


def write_result(result: BundleResult, sink, ingest_date: date, file_id: str) -> list[str]:
    """Write non-empty tables and any quarantine records. Returns the keys written."""
    partition = f"ingest_date={ingest_date.isoformat()}"
    written = []
    for table, df in result.tables.items():
        if df.empty:
            continue
        key = f"silver/{table}/{partition}/{file_id}.parquet"
        sink.put(key, to_parquet_bytes(table, df))
        written.append(key)
    if result.quarantine:
        key = f"quarantine/{partition}/{file_id}.jsonl"
        body = "\n".join(json.dumps(rec, default=str) for rec in result.quarantine) + "\n"
        sink.put(key, body.encode("utf-8"))
        written.append(key)
    return written

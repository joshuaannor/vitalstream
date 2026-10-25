"""AWS Lambda entry point: S3 "object created" event -> silver Parquet + quarantine.

Environment:
    CURATED_BUCKET   bucket that receives silver/ and quarantine/ output
"""

import json
import os
from datetime import datetime, timezone
from urllib.parse import unquote_plus

from ingest.pipeline import process_bundle
from ingest.writer import S3Sink, file_id_for, write_result

_s3 = None


def _client():
    """Create the S3 client once per Lambda container (and lazily, so tests can swap it)."""
    global _s3
    if _s3 is None:
        import boto3
        _s3 = boto3.client("s3")
    return _s3


def lambda_handler(event, context=None, s3=None):
    s3 = s3 or _client()
    sink = S3Sink(os.environ["CURATED_BUCKET"], s3)
    summaries = []
    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = unquote_plus(record["s3"]["object"]["key"])  # S3 events URL-encode keys
        source = f"s3://{bucket}/{key}"
        today = datetime.now(timezone.utc).date()

        raw = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        result = process_bundle(raw, source_file=source, today=today)
        written = write_result(result, sink, ingest_date=today, file_id=file_id_for(source))

        summary = {"event": "bundle_processed", "source_file": source,
                   **result.counts(), "files_written": len(written)}
        print(json.dumps(summary))  # one JSON line per bundle -> CloudWatch Logs
        summaries.append(summary)
    return {"processed": len(summaries), "results": summaries}

"""AWS Lambda entry point: S3 "object created" event -> silver Parquet + quarantine.

Environment:
    CURATED_BUCKET      bucket that receives silver/ and quarantine/ output
    METRICS_NAMESPACE   CloudWatch namespace for record-count metrics (default VitalStream)
"""

import json
import os
import time
from datetime import datetime, timezone
from urllib.parse import unquote_plus

from ingest.pipeline import process_bundle
from ingest.writer import S3Sink, file_id_for, write_result

# CloudWatch metric name -> key in the bundle summary. 6 metrics (free tier allows 10).
METRICS = {
    "BundlesProcessed": "bundles",
    "PatientRows": "rows_patients",
    "EncounterRows": "rows_encounters",
    "ObservationRows": "rows_observations",
    "ConditionRows": "rows_conditions",
    "QuarantinedRecords": "quarantined",
}

_s3 = None


def _client():
    """Create the S3 client once per Lambda container (and lazily, so tests can swap it)."""
    global _s3
    if _s3 is None:
        import boto3
        _s3 = boto3.client("s3")
    return _s3


def log_line(summary: dict, namespace: str) -> str:
    """One JSON log line that is also a CloudWatch Embedded Metric Format (EMF) record.

    CloudWatch reads the "_aws" block and turns the listed fields into metrics,
    so no PutMetricData call (or permission) is needed.
    """
    record = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [{
                "Namespace": namespace,
                "Dimensions": [["Pipeline"]],
                "Metrics": [{"Name": name, "Unit": "Count"} for name in METRICS],
            }],
        },
        "Pipeline": "ingest",
        **summary,
        **{name: summary.get(key, 0) for name, key in METRICS.items()},
    }
    return json.dumps(record, default=str)


def lambda_handler(event, context=None, s3=None):
    s3 = s3 or _client()
    sink = S3Sink(os.environ["CURATED_BUCKET"], s3)
    namespace = os.environ.get("METRICS_NAMESPACE", "VitalStream")
    summaries = []
    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = unquote_plus(record["s3"]["object"]["key"])  # S3 events URL-encode keys
        source = f"s3://{bucket}/{key}"
        today = datetime.now(timezone.utc).date()

        raw = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        result = process_bundle(raw, source_file=source, today=today)
        written = write_result(result, sink, ingest_date=today, file_id=file_id_for(source))

        summary = {"event": "bundle_processed", "source_file": source, "bundles": 1,
                   **result.counts(), "files_written": len(written)}
        print(log_line(summary, namespace))  # -> CloudWatch Logs + metrics
        summaries.append(summary)
    return {"processed": len(summaries), "results": summaries}

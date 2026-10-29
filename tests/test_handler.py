"""Lambda handler with a fake S3 client: no AWS account or network needed."""

import io
import json

from ingest.handler import METRICS, lambda_handler
from samples import find, raw


class FakeS3:
    def __init__(self, objects: dict):
        self.objects = dict(objects)  # (bucket, key) -> bytes

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    def put_object(self, Bucket, Key, Body):
        self.objects[(Bucket, Key)] = Body


def s3_event(bucket: str, key: str) -> dict:
    return {"Records": [{"s3": {"bucket": {"name": bucket}, "object": {"key": key}}}]}


def run(monkeypatch, capsys, bundle):
    monkeypatch.setenv("CURATED_BUCKET", "curated")
    s3 = FakeS3({("raw", "fhir/Ana Test.json"): raw(bundle)})
    # S3 events URL-encode keys: a space arrives as "+"
    out = lambda_handler(s3_event("raw", "fhir/Ana+Test.json"), s3=s3)
    log = json.loads(capsys.readouterr().out.strip())
    return out, s3, log


def test_handler_reads_bronze_and_writes_silver(bundle, monkeypatch, capsys):
    out, s3, _ = run(monkeypatch, capsys, bundle)
    summary = out["results"][0]
    assert summary["source_file"] == "s3://raw/fhir/Ana Test.json"
    assert summary["rows_observations"] == 4
    assert summary["quarantined"] == 0
    written = [k for (b, k) in s3.objects if b == "curated"]
    assert len(written) == 4 and all(k.startswith("silver/") for k in written)


def test_log_line_is_cloudwatch_emf(bundle, monkeypatch, capsys):
    find(bundle, "obs-a1c")["valueQuantity"]["value"] = "high"   # one quarantined record
    _, _, log = run(monkeypatch, capsys, bundle)

    [directive] = log["_aws"]["CloudWatchMetrics"]
    assert directive["Namespace"] == "VitalStream"
    assert directive["Dimensions"] == [["Pipeline"]]
    assert {m["Name"] for m in directive["Metrics"]} == set(METRICS)
    assert log["Pipeline"] == "ingest"
    assert (log["BundlesProcessed"], log["ObservationRows"], log["QuarantinedRecords"]) == (1, 3, 1)
    assert log["quarantine_reasons"] == {"invalid_value": 1}   # extra context stays in the log

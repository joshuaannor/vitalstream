"""Lambda handler with a fake S3 client: no AWS account or network needed."""

import io

from samples import raw
from ingest.handler import lambda_handler


class FakeS3:
    def __init__(self, objects: dict):
        self.objects = dict(objects)  # (bucket, key) -> bytes

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    def put_object(self, Bucket, Key, Body):
        self.objects[(Bucket, Key)] = Body


def s3_event(bucket: str, key: str) -> dict:
    return {"Records": [{"s3": {"bucket": {"name": bucket}, "object": {"key": key}}}]}


def test_handler_reads_bronze_and_writes_silver(bundle, monkeypatch, capsys):
    monkeypatch.setenv("CURATED_BUCKET", "curated")
    s3 = FakeS3({("raw", "fhir/Ana Test.json"): raw(bundle)})

    # S3 events URL-encode keys: a space arrives as "+"
    out = lambda_handler(s3_event("raw", "fhir/Ana+Test.json"), s3=s3)

    summary = out["results"][0]
    assert summary["source_file"] == "s3://raw/fhir/Ana Test.json"
    assert summary["rows_observations"] == 4
    assert summary["quarantined"] == 0
    written = [k for (b, k) in s3.objects if b == "curated"]
    assert len(written) == 4 and all(k.startswith("silver/") for k in written)
    assert '"event": "bundle_processed"' in capsys.readouterr().out  # log line for CloudWatch

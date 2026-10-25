import json
from datetime import date

import pyarrow as pa
import pyarrow.parquet as pq

from samples import TODAY, find, raw
from ingest.pipeline import process_bundle
from ingest.writer import LocalSink, file_id_for, write_result

INGEST = date(2026, 10, 24)


def test_writes_partitioned_parquet_with_exact_types(bundle, tmp_path):
    result = process_bundle(raw(bundle), "bronze/test.json", TODAY)
    keys = write_result(result, LocalSink(tmp_path), INGEST, "abc")

    assert sorted(keys) == [f"silver/{t}/ingest_date=2026-10-24/abc.parquet"
                            for t in ("conditions", "encounters", "observations", "patients")]
    patients = pq.read_table(tmp_path / "silver/patients/ingest_date=2026-10-24/abc.parquet")
    assert patients.schema.field("birth_date").type == pa.date32()
    assert patients.schema.field("deceased_at").type == pa.timestamp("ms")
    obs = pq.read_table(tmp_path / "silver/observations/ingest_date=2026-10-24/abc.parquet")
    assert obs.num_rows == 4
    assert obs.schema.field("value_num").type == pa.float64()


def test_quarantine_written_as_json_lines_and_empty_tables_skipped(bundle, tmp_path):
    find(bundle, "pat-1")["gender"] = "f"  # whole bundle ends up quarantined
    result = process_bundle(raw(bundle), "bronze/test.json", TODAY)
    keys = write_result(result, LocalSink(tmp_path), INGEST, "abc")

    assert keys == ["quarantine/ingest_date=2026-10-24/abc.jsonl"]
    lines = (tmp_path / keys[0]).read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines]
    assert len(records) == 6
    assert {"source_file", "resource_type", "resource_id", "reason", "detail", "resource"} <= set(records[0])


def test_file_id_is_deterministic_and_hides_file_name():
    a = file_id_for("s3://raw/Jammie261_Maggio310_6e6a.json")
    assert a == file_id_for("s3://raw/Jammie261_Maggio310_6e6a.json")
    assert a != file_id_for("s3://raw/other.json")
    assert "Jammie" not in a and len(a) == 16

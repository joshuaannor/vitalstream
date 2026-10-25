from datetime import date, datetime

import pytest

from ingest.fhir import QualityError, parse_date, parse_ts, ref_id, semantic_tag


@pytest.mark.parametrize("ref, expected", [
    ({"reference": "urn:uuid:abc-123"}, "abc-123"),
    ({"reference": "Patient/abc-123"}, "abc-123"),
    ({"reference": "Organization?identifier=x|1"}, None),  # conditional: outside the bundle
    ({}, None),
    (None, None),
])
def test_ref_id(ref, expected):
    assert ref_id(ref) == expected


def test_parse_ts_converts_offset_to_utc():
    assert parse_ts("2017-03-06T05:24:59-05:00", "f") == datetime(2017, 3, 6, 10, 24, 59)


def test_parse_ts_accepts_z_and_truncates_to_milliseconds():
    assert parse_ts("2020-01-01T00:00:00.123456Z", "f") == datetime(2020, 1, 1, 0, 0, 0, 123000)


def test_parse_ts_missing_is_none():
    assert parse_ts(None, "f") is None


@pytest.mark.parametrize("bad", ["not-a-date", "2020-13-01T00:00:00Z", 12345])
def test_parse_ts_rejects_garbage(bad):
    with pytest.raises(QualityError) as exc:
        parse_ts(bad, "period.start")
    assert exc.value.reason == "invalid_timestamp"
    assert "period.start" in exc.value.detail


def test_parse_date():
    assert parse_date("1985-12-23", "birthDate") == date(1985, 12, 23)
    with pytest.raises(QualityError):
        parse_date("23/12/1985", "birthDate")


@pytest.mark.parametrize("text, tag", [
    ("Prediabetes (finding)", "finding"),
    ("Otitis media (disorder)", "disorder"),
    ("Something without a tag", None),
    (None, None),
])
def test_semantic_tag(text, tag):
    assert semantic_tag(text) == tag

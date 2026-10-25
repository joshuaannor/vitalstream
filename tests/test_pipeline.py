"""End-to-end behaviour of process_bundle: what loads, what gets quarantined, and why."""

import copy
import json

import pytest

from samples import TODAY, find, raw
from ingest.pipeline import process_bundle


def run(bundle_or_bytes):
    data = bundle_or_bytes if isinstance(bundle_or_bytes, (bytes, str)) else raw(bundle_or_bytes)
    return process_bundle(data, source_file="bronze/test.json", today=TODAY)


def reasons(result) -> list[str]:
    return sorted(q["reason"] for q in result.quarantine)


def test_valid_bundle_loads_everything(bundle):
    result = run(bundle)
    counts = result.counts()
    assert counts["rows_patients"] == 1
    assert counts["rows_encounters"] == 1
    assert counts["rows_observations"] == 4  # A1c + 2 BP components + smoking
    assert counts["rows_conditions"] == 1
    assert counts["quarantined"] == 0


# --- Bundle-level problems: nothing loads --------------------------------

def test_invalid_json():
    result = run(b'{"resourceType": "Bundle", "entry": [')
    assert reasons(result) == ["invalid_json"]
    assert all(df.empty for df in result.tables.values())


def test_not_a_bundle(bundle):
    result = run(json.dumps(find(bundle, "pat-1")))
    assert reasons(result) == ["not_a_bundle"]


def test_two_patients(bundle):
    bundle["entry"].append(copy.deepcopy(bundle["entry"][0]))
    result = run(bundle)
    assert reasons(result) == ["expected_one_patient"]
    assert all(df.empty for df in result.tables.values())


# --- Record-level problems: the bad record is quarantined, the rest loads --

def _mutate(path_value):
    """Helper: (resource id, field, new value) -> function that applies it."""
    rid, key, value = path_value

    def apply(bundle):
        resource = find(bundle, rid)
        if value is DELETE:
            del resource[key]
        else:
            resource[key] = value
    return apply


DELETE = object()


@pytest.mark.parametrize("damage, reason", [
    (("obs-a1c", "valueQuantity", {"value": "high"}), "invalid_value"),
    (("obs-a1c", "subject", DELETE), "missing_subject"),
    (("obs-a1c", "subject", {"reference": "urn:uuid:someone-else"}), "orphan_subject"),
    (("obs-a1c", "encounter", {"reference": "urn:uuid:no-such-visit"}), "orphan_encounter"),
    (("obs-a1c", "effectiveDateTime", DELETE), "missing_effective_time"),
    (("obs-a1c", "valueQuantity", DELETE), "missing_value"),
    (("obs-a1c", "code", {"text": "no coding"}), "missing_code"),
    (("cond-1", "onsetDateTime", DELETE), "missing_onset"),
    (("cond-1", "abatementDateTime", "2000-01-01T00:00:00Z"), "abatement_before_onset"),
    (("cond-1", "onsetDateTime", "yesterday"), "invalid_timestamp"),
])
def test_bad_record_is_quarantined_alone(bundle, damage, reason):
    _mutate(damage)(bundle)
    result = run(bundle)
    assert reasons(result) == [reason]
    q = result.quarantine[0]
    assert q["resource_id"] == damage[0]
    assert q["resource"]["id"] == damage[0]          # raw copy kept for debugging
    assert result.counts()["rows_patients"] == 1     # everything else still loads
    assert result.counts()["rows_encounters"] == 1


def test_missing_id(bundle):
    del find(bundle, "obs-a1c")["id"]
    assert reasons(run(bundle)) == ["missing_id"]


def test_duplicate_id_keeps_first_copy(bundle):
    bundle["entry"].append(copy.deepcopy(bundle["entry"][2]))  # obs-a1c again
    result = run(bundle)
    assert reasons(result) == ["duplicate_id"]
    assert (result.tables["observations"]["observation_id"] == "obs-a1c").sum() == 1


def test_bad_encounter_orphans_its_children(bundle):
    find(bundle, "enc-1")["period"]["end"] = "2000-01-01T00:00:00Z"  # before start
    result = run(bundle)
    assert reasons(result) == ["end_before_start"] + ["orphan_encounter"] * 4
    assert result.counts()["rows_patients"] == 1


@pytest.mark.parametrize("field, value, reason", [
    ("gender", "f", "invalid_gender"),
    ("birthDate", "2099-01-01", "birth_date_in_future"),
    ("deceasedDateTime", "1950-01-01T00:00:00Z", "deceased_before_birth"),
])
def test_bad_patient_quarantines_whole_bundle_as_orphans(bundle, field, value, reason):
    find(bundle, "pat-1")[field] = value
    result = run(bundle)
    got = reasons(result)
    assert reason in got
    assert got.count("orphan_subject") == 5  # encounter, 3 observations, condition
    assert all(df.empty for df in result.tables.values())

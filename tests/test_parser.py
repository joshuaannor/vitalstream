from datetime import date, datetime

import pytest

from samples import CONDITION, ENCOUNTER, OBS_A1C, OBS_BP, OBS_SMOKING, PATIENT
from ingest.fhir import QualityError
from ingest.parser import flatten_condition, flatten_encounter, flatten_observation, flatten_patient
from ingest.schemas import SCHEMAS

SRC = "bronze/test.json"


def test_patient_row_keeps_analytics_fields_and_drops_pii():
    [row] = flatten_patient(PATIENT, SRC)
    assert row["patient_id"] == "pat-1"
    assert row["birth_date"] == date(1985, 12, 23)
    assert row["race"] == "White"
    assert row["city"] == "Boston"
    flat = str(row)
    for pii in ("999-99-9999", "Ana", "1 Main St"):  # SSN, name, street
        assert pii not in flat


def test_encounter_row():
    [row] = flatten_encounter(ENCOUNTER, SRC)
    assert row["patient_id"] == "pat-1"          # urn:uuid: stripped
    assert row["class_code"] == "AMB"
    assert row["type_code"] == "162673000"
    assert row["start_at"] == datetime(2017, 3, 6, 10, 24, 59)  # converted to UTC
    assert row["service_provider"] == "Test Clinic"
    assert row["reason_code"] is None             # optional field, missing is fine


def test_quantity_observation():
    [row] = flatten_observation(OBS_A1C, SRC)
    assert (row["code"], row["value_type"], row["value_num"], row["value_unit"]) == \
        ("4548-4", "quantity", 5.96, "%")
    assert row["panel_code"] is None


def test_blood_pressure_explodes_into_one_row_per_component():
    rows = flatten_observation(OBS_BP, SRC)
    assert {r["code"]: r["value_num"] for r in rows} == {"8462-4": 82.0, "8480-6": 121.0}
    assert all(r["panel_code"] == "85354-9" and r["observation_id"] == "obs-bp" for r in rows)


def test_coded_observation():
    [row] = flatten_observation(OBS_SMOKING, SRC)
    assert row["value_type"] == "codeable_concept"
    assert row["value_code"] == "266919005"
    assert row["value_num"] is None


def test_non_numeric_quantity_is_rejected():
    bad = {**OBS_A1C, "valueQuantity": {"value": "high", "unit": "%"}}
    with pytest.raises(QualityError) as exc:
        flatten_observation(bad, SRC)
    assert exc.value.reason == "invalid_value"


def test_condition_row():
    [row] = flatten_condition(CONDITION, SRC)
    assert row["code"] == "714628002"
    assert row["semantic_tag"] == "finding"
    assert row["clinical_status"] == "active"
    assert row["abatement_at"] is None


@pytest.mark.parametrize("flatten, resource, table", [
    (flatten_patient, PATIENT, "patients"),
    (flatten_encounter, ENCOUNTER, "encounters"),
    (flatten_observation, OBS_BP, "observations"),
    (flatten_condition, CONDITION, "conditions"),
])
def test_rows_match_schema_columns(flatten, resource, table):
    for row in flatten(resource, SRC):
        assert set(row) == set(SCHEMAS[table].names)

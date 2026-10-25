"""A tiny hand-made FHIR bundle shaped like Synthea output, shared by the tests."""

import copy
import json
from datetime import date

TODAY = date(2026, 1, 1)
PATIENT_ID = "pat-1"
ENC_ID = "enc-1"


def _ref(rid: str) -> dict:
    return {"reference": f"urn:uuid:{rid}"}


def _loinc(code: str, label: str) -> dict:
    return {"coding": [{"system": "http://loinc.org", "code": code, "display": label}], "text": label}


def _snomed(code: str, label: str) -> dict:
    return {"coding": [{"system": "http://snomed.info/sct", "code": code, "display": label}], "text": label}


def _category(code: str) -> list[dict]:
    return [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category",
                         "code": code}]}]


PATIENT = {
    "resourceType": "Patient",
    "id": PATIENT_ID,
    "extension": [{
        "url": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-race",
        "extension": [{"url": "text", "valueString": "White"}],
    }],
    "identifier": [{"type": {"coding": [{"code": "SS"}]}, "value": "999-99-9999"}],
    "name": [{"use": "official", "family": "Test", "given": ["Ana"]}],
    "gender": "female",
    "birthDate": "1985-12-23",
    "address": [{"line": ["1 Main St"], "city": "Boston", "state": "MA", "postalCode": "02109"}],
}

ENCOUNTER = {
    "resourceType": "Encounter",
    "id": ENC_ID,
    "status": "finished",
    "class": {"code": "AMB"},
    "type": [_snomed("162673000", "General examination of patient (procedure)")],
    "subject": _ref(PATIENT_ID),
    "period": {"start": "2017-03-06T05:24:59-05:00", "end": "2017-03-06T06:16:20-05:00"},
    "serviceProvider": {"reference": "Organization?identifier=x|1", "display": "Test Clinic"},
}

OBS_A1C = {
    "resourceType": "Observation",
    "id": "obs-a1c",
    "status": "final",
    "category": _category("laboratory"),
    "code": _loinc("4548-4", "Hemoglobin A1c"),
    "subject": _ref(PATIENT_ID),
    "encounter": _ref(ENC_ID),
    "effectiveDateTime": "2017-03-06T05:24:59-05:00",
    "valueQuantity": {"value": 5.96, "unit": "%"},
}

OBS_BP = {
    "resourceType": "Observation",
    "id": "obs-bp",
    "status": "final",
    "category": _category("vital-signs"),
    "code": _loinc("85354-9", "Blood pressure panel"),
    "subject": _ref(PATIENT_ID),
    "encounter": _ref(ENC_ID),
    "effectiveDateTime": "2017-03-06T05:24:59-05:00",
    "component": [
        {"code": _loinc("8462-4", "Diastolic Blood Pressure"), "valueQuantity": {"value": 82, "unit": "mm[Hg]"}},
        {"code": _loinc("8480-6", "Systolic Blood Pressure"), "valueQuantity": {"value": 121, "unit": "mm[Hg]"}},
    ],
}

OBS_SMOKING = {
    "resourceType": "Observation",
    "id": "obs-smoke",
    "status": "final",
    "category": _category("social-history"),
    "code": _loinc("72166-2", "Tobacco smoking status"),
    "subject": _ref(PATIENT_ID),
    "encounter": _ref(ENC_ID),
    "effectiveDateTime": "2017-03-06T05:24:59-05:00",
    "valueCodeableConcept": _snomed("266919005", "Never smoked tobacco (finding)"),
}

CONDITION = {
    "resourceType": "Condition",
    "id": "cond-1",
    "clinicalStatus": {"coding": [{"code": "active"}]},
    "verificationStatus": {"coding": [{"code": "confirmed"}]},
    "category": [{"coding": [{"code": "encounter-diagnosis"}]}],
    "code": _snomed("714628002", "Prediabetes (finding)"),
    "subject": _ref(PATIENT_ID),
    "encounter": _ref(ENC_ID),
    "onsetDateTime": "2017-03-06T05:24:59-05:00",
}

RESOURCES = [PATIENT, ENCOUNTER, OBS_A1C, OBS_BP, OBS_SMOKING, CONDITION]


def make_bundle() -> dict:
    """A fresh, valid bundle each test can modify freely."""
    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [{"fullUrl": f"urn:uuid:{r['id']}", "resource": copy.deepcopy(r)} for r in RESOURCES],
    }


def find(bundle: dict, rid: str) -> dict:
    """The resource with this id inside a bundle (for targeted damage in tests)."""
    return next(e["resource"] for e in bundle["entry"] if e["resource"]["id"] == rid)


def raw(bundle: dict) -> bytes:
    return json.dumps(bundle).encode("utf-8")

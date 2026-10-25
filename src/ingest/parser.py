"""Flatten FHIR R4 resources into silver-table rows (plain dicts).

Each flatten_* function takes one resource and returns its rows. It raises QualityError
when a value is malformed (e.g. an unparseable timestamp). Business rules such as
"must have a subject" live in quality.py.

Deliberately dropped (data minimization): names, identifiers (SSN, MRN, passport...),
telecom, street address, and other extensions we don't analyse.
"""

from ingest.fhir import (
    LOINC,
    SNOMED,
    QualityError,
    coding,
    display,
    first,
    parse_date,
    parse_ts,
    ref_id,
    semantic_tag,
    system_name,
    us_core_text,
)

VALUE_COLUMNS = ("value_type", "value_num", "value_unit", "value_code", "value_display", "value_text")


def flatten_patient(r: dict, source_file: str) -> list[dict]:
    addr = first(r.get("address")) or {}
    return [{
        "patient_id": r.get("id"),
        "gender": r.get("gender"),
        "birth_date": parse_date(r.get("birthDate"), "birthDate"),
        "deceased_at": parse_ts(r.get("deceasedDateTime"), "deceasedDateTime"),
        "race": us_core_text(r, "us-core-race"),
        "ethnicity": us_core_text(r, "us-core-ethnicity"),
        "marital_status": coding(r.get("maritalStatus")).get("code"),
        "city": addr.get("city"),
        "state": addr.get("state"),
        "postal_code": addr.get("postalCode"),
        "source_file": source_file,
    }]


def flatten_encounter(r: dict, source_file: str) -> list[dict]:
    period = r.get("period") or {}
    etype = first(r.get("type"))
    type_c = coding(etype, SNOMED)
    reason = first(r.get("reasonCode"))
    reason_c = coding(reason, SNOMED)
    return [{
        "encounter_id": r.get("id"),
        "patient_id": ref_id(r.get("subject")),
        "status": r.get("status"),
        "class_code": (r.get("class") or {}).get("code"),
        "type_code": type_c.get("code"),
        "type_display": display(etype, type_c),
        "reason_code": reason_c.get("code"),
        "reason_display": display(reason, reason_c),
        "service_provider": (r.get("serviceProvider") or {}).get("display"),
        "start_at": parse_ts(period.get("start"), "period.start"),
        "end_at": parse_ts(period.get("end"), "period.end"),
        "source_file": source_file,
    }]


def extract_value(src: dict) -> dict:
    """Normalize FHIR's value[x] (one of several shapes) into fixed columns."""
    out = dict.fromkeys(VALUE_COLUMNS)
    if "valueQuantity" in src:
        q = src["valueQuantity"] or {}
        num = q.get("value")
        if isinstance(num, bool) or not isinstance(num, (int, float)):
            raise QualityError("invalid_value", f"valueQuantity.value={num!r}")
        out.update(value_type="quantity", value_num=float(num), value_unit=q.get("unit") or q.get("code"))
    elif "valueCodeableConcept" in src:
        cc = src["valueCodeableConcept"] or {}
        c = coding(cc)
        out.update(value_type="codeable_concept", value_code=c.get("code"), value_display=display(cc, c))
    elif "valueString" in src:
        out.update(value_type="string", value_text=src["valueString"])
    elif "valueBoolean" in src:
        out.update(value_type="boolean", value_text=str(src["valueBoolean"]).lower())
    elif "valueInteger" in src:
        out.update(value_type="quantity", value_num=float(src["valueInteger"]))
    return out


def flatten_observation(r: dict, source_file: str) -> list[dict]:
    effective = r.get("effectiveDateTime") or (r.get("effectivePeriod") or {}).get("start")
    base = {
        "observation_id": r.get("id"),
        "patient_id": ref_id(r.get("subject")),
        "encounter_id": ref_id(r.get("encounter")),
        "status": r.get("status"),
        "category": coding(first(r.get("category"))).get("code"),
        "effective_at": parse_ts(effective, "effectiveDateTime"),
        "source_file": source_file,
    }

    def make_row(concept: dict | None, panel_code: str | None, value_src: dict) -> dict:
        c = coding(concept, LOINC)
        return {
            **base,
            "panel_code": panel_code,
            "code_system": system_name(c.get("system")),
            "code": c.get("code"),
            "code_display": display(concept, c),
            **extract_value(value_src),
        }

    components = r.get("component") or []
    has_own_value = any(k.startswith("value") for k in r)
    rows = []
    if has_own_value or not components:
        rows.append(make_row(r.get("code"), None, r))
    panel_code = coding(r.get("code"), LOINC).get("code")
    for comp in components:
        rows.append(make_row(comp.get("code"), panel_code, comp))
    return rows


def flatten_condition(r: dict, source_file: str) -> list[dict]:
    concept = r.get("code")
    c = coding(concept, SNOMED)
    label = display(concept, c)
    return [{
        "condition_id": r.get("id"),
        "patient_id": ref_id(r.get("subject")),
        "encounter_id": ref_id(r.get("encounter")),
        "clinical_status": coding(r.get("clinicalStatus")).get("code"),
        "verification_status": coding(r.get("verificationStatus")).get("code"),
        "category": coding(first(r.get("category"))).get("code"),
        "code_system": system_name(c.get("system")),
        "code": c.get("code"),
        "code_display": label,
        "semantic_tag": semantic_tag(label),
        "onset_at": parse_ts(r.get("onsetDateTime"), "onsetDateTime"),
        "abatement_at": parse_ts(r.get("abatementDateTime"), "abatementDateTime"),
        "source_file": source_file,
    }]


# Processing order matters: patient first, then encounters, so later resources
# can be checked against the ids that were accepted.
FLATTENERS = {
    "Patient": ("patients", flatten_patient),
    "Encounter": ("encounters", flatten_encounter),
    "Observation": ("observations", flatten_observation),
    "Condition": ("conditions", flatten_condition),
}

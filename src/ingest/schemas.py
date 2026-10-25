"""Silver table schemas. Explicit types keep Parquet output identical across pandas versions.

Timestamps are stored in UTC without a time zone (columns ending in _at).
The partition column (ingest_date) lives in the folder name, not inside the files.
"""

import pyarrow as pa

STR = pa.string()
TS = pa.timestamp("ms")
DATE = pa.date32()

SCHEMAS = {
    "patients": pa.schema([
        ("patient_id", STR),
        ("gender", STR),
        ("birth_date", DATE),
        ("deceased_at", TS),
        ("race", STR),
        ("ethnicity", STR),
        ("marital_status", STR),
        ("city", STR),
        ("state", STR),
        ("postal_code", STR),
        ("source_file", STR),
    ]),
    "encounters": pa.schema([
        ("encounter_id", STR),
        ("patient_id", STR),
        ("status", STR),
        ("class_code", STR),
        ("type_code", STR),
        ("type_display", STR),
        ("reason_code", STR),
        ("reason_display", STR),
        ("service_provider", STR),
        ("start_at", TS),
        ("end_at", TS),
        ("source_file", STR),
    ]),
    # One row per measurement: blood pressure becomes two rows (systolic, diastolic)
    # sharing an observation_id, with panel_code set to the parent panel's code.
    "observations": pa.schema([
        ("observation_id", STR),
        ("patient_id", STR),
        ("encounter_id", STR),
        ("status", STR),
        ("category", STR),
        ("panel_code", STR),
        ("code_system", STR),
        ("code", STR),
        ("code_display", STR),
        ("value_type", STR),
        ("value_num", pa.float64()),
        ("value_unit", STR),
        ("value_code", STR),
        ("value_display", STR),
        ("value_text", STR),
        ("effective_at", TS),
        ("source_file", STR),
    ]),
    "conditions": pa.schema([
        ("condition_id", STR),
        ("patient_id", STR),
        ("encounter_id", STR),
        ("clinical_status", STR),
        ("verification_status", STR),
        ("category", STR),
        ("code_system", STR),
        ("code", STR),
        ("code_display", STR),
        ("semantic_tag", STR),
        ("onset_at", TS),
        ("abatement_at", TS),
        ("source_file", STR),
    ]),
}

PRIMARY_KEYS = {
    "patients": ["patient_id"],
    "encounters": ["encounter_id"],
    "observations": ["observation_id", "code"],
    "conditions": ["condition_id"],
}

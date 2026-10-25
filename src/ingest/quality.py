"""Row-level data quality rules for the silver tables.

Each rule is (reason, check). check(row, ctx) returns True when the row passes.
The first failing rule's reason is what lands in quarantine.
"""

from dataclasses import dataclass, field
from datetime import date

VALID_GENDERS = {"male", "female", "other", "unknown"}


@dataclass
class BundleContext:
    """What we know about the bundle so far, for cross-record checks."""

    today: date
    patient_id: str | None = None                      # the accepted Patient
    encounter_ids: set[str] = field(default_factory=set)  # accepted Encounters


def _in_order(earlier, later) -> bool:
    """True unless both values exist and are out of order."""
    return earlier is None or later is None or earlier <= later


_SUBJECT_RULES = [
    ("missing_subject", lambda r, c: r["patient_id"] is not None),
    ("orphan_subject", lambda r, c: r["patient_id"] == c.patient_id),
]
_ENCOUNTER_RULES = [
    ("orphan_encounter", lambda r, c: r["encounter_id"] is None or r["encounter_id"] in c.encounter_ids),
]

RULES = {
    "patients": [
        ("missing_birth_date", lambda r, c: r["birth_date"] is not None),
        ("invalid_gender", lambda r, c: r["gender"] in VALID_GENDERS),
        ("birth_date_in_future", lambda r, c: r["birth_date"] <= c.today),
        ("deceased_before_birth",
         lambda r, c: r["deceased_at"] is None or r["deceased_at"].date() >= r["birth_date"]),
    ],
    "encounters": [
        *_SUBJECT_RULES,
        ("missing_start", lambda r, c: r["start_at"] is not None),
        ("end_before_start", lambda r, c: _in_order(r["start_at"], r["end_at"])),
    ],
    "observations": [
        *_SUBJECT_RULES,
        *_ENCOUNTER_RULES,
        ("missing_code", lambda r, c: r["code"] is not None),
        ("missing_effective_time", lambda r, c: r["effective_at"] is not None),
        ("missing_value", lambda r, c: r["value_type"] is not None),
    ],
    "conditions": [
        *_SUBJECT_RULES,
        *_ENCOUNTER_RULES,
        ("missing_code", lambda r, c: r["code"] is not None),
        ("missing_onset", lambda r, c: r["onset_at"] is not None),
        ("abatement_before_onset", lambda r, c: _in_order(r["onset_at"], r["abatement_at"])),
    ],
}


def first_failure(table: str, row: dict, ctx: BundleContext) -> str | None:
    """Reason code of the first rule this row breaks, or None if it passes all of them."""
    for reason, check in RULES[table]:
        if not check(row, ctx):
            return reason
    return None

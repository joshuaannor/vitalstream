"""Small helpers for reading FHIR R4 JSON. Pure Python, no pandas."""

import re
from datetime import date, datetime, timezone

LOINC = "http://loinc.org"
SNOMED = "http://snomed.info/sct"

SYSTEM_NAMES = {
    LOINC: "LOINC",
    SNOMED: "SNOMED",
    "http://www.nlm.nih.gov/research/umls/rxnorm": "RxNorm",
}

# "Otitis media (disorder)" -> "disorder"
_SEMANTIC_TAG = re.compile(r"\(([^()]+)\)\s*$")


class QualityError(Exception):
    """A record failed a data quality check. `reason` is a short code used in quarantine."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


def first(items):
    """First element of a list, or None for a missing/empty list."""
    return items[0] if items else None


def ref_id(ref_obj: dict | None) -> str | None:
    """Turn a FHIR reference into a plain id usable as a join key.

    'urn:uuid:abc' -> 'abc', 'Patient/abc' -> 'abc'.
    Conditional references ('Organization?identifier=...') point outside the bundle -> None.
    """
    ref = (ref_obj or {}).get("reference")
    if not ref or "?" in ref:
        return None
    if ref.startswith("urn:uuid:"):
        return ref[len("urn:uuid:"):]
    return ref.rsplit("/", 1)[-1]


def parse_ts(value, field: str) -> datetime | None:
    """ISO 8601 timestamp -> naive datetime in UTC, millisecond precision.

    '2017-03-06T05:24:59-05:00' -> datetime(2017, 3, 6, 10, 24, 59).
    Missing stays None; anything unparseable raises QualityError.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise QualityError("invalid_timestamp", f"{field}={value!r}")
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise QualityError("invalid_timestamp", f"{field}={value!r}") from None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.replace(microsecond=dt.microsecond // 1000 * 1000)


def parse_date(value, field: str) -> date | None:
    """'1985-12-23' -> date. Missing stays None; anything unparseable raises QualityError."""
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise QualityError("invalid_date", f"{field}={value!r}") from None


def coding(concept: dict | None, prefer: str | None = None) -> dict:
    """First Coding of a CodeableConcept, preferring the `prefer` system. {} if there is none."""
    codings = (concept or {}).get("coding") or []
    if prefer:
        for c in codings:
            if c.get("system") == prefer:
                return c
    return codings[0] if codings else {}


def display(concept: dict | None, c: dict) -> str | None:
    """Human-readable label: the coding's display, else the concept's free text."""
    return c.get("display") or (concept or {}).get("text")


def system_name(url: str | None) -> str | None:
    """'http://loinc.org' -> 'LOINC'; unknown systems are kept as-is."""
    return SYSTEM_NAMES.get(url, url)


def semantic_tag(text: str | None) -> str | None:
    """SNOMED display suffix: 'Prediabetes (finding)' -> 'finding'."""
    match = _SEMANTIC_TAG.search(text or "")
    return match.group(1) if match else None


def us_core_text(resource: dict, name: str) -> str | None:
    """Text value of a US Core extension such as 'us-core-race' -> 'White'."""
    for ext in resource.get("extension") or []:
        if ext.get("url", "").endswith("/" + name):
            for sub in ext.get("extension") or []:
                if sub.get("url") == "text":
                    return sub.get("valueString")
    return None

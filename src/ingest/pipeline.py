"""Bronze -> silver for one FHIR bundle: parse, validate, flatten, quarantine.

No I/O here: takes raw bytes, returns DataFrames + quarantine records.
The same function runs locally (scripts/run_local.py) and in Lambda (handler.py).
"""

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from ingest.fhir import QualityError
from ingest.parser import FLATTENERS
from ingest.quality import BundleContext, first_failure
from ingest.schemas import SCHEMAS


@dataclass
class BundleResult:
    tables: dict[str, pd.DataFrame]
    quarantine: list[dict] = field(default_factory=list)

    def counts(self) -> dict:
        out = {f"rows_{name}": len(df) for name, df in self.tables.items()}
        out["quarantined"] = len(self.quarantine)
        out["quarantine_reasons"] = dict(Counter(q["reason"] for q in self.quarantine))
        return out


def _frame(table: str, rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=SCHEMAS[table].names)


def process_bundle(raw: bytes | str, source_file: str, today: date) -> BundleResult:
    rows: dict[str, list[dict]] = {table: [] for table, _ in FLATTENERS.values()}
    quarantine: list[dict] = []

    def reject(reason: str, resource: dict | None = None, detail: str = "") -> None:
        quarantine.append({
            "source_file": source_file,
            "resource_type": (resource or {}).get("resourceType"),
            "resource_id": (resource or {}).get("id"),
            "reason": reason,
            "detail": detail,
            "resource": resource,  # raw copy for debugging; bundle-level failures stay in bronze
        })

    def result() -> BundleResult:
        return BundleResult({t: _frame(t, r) for t, r in rows.items()}, quarantine)

    # --- Bundle-level checks: if these fail, nothing in the file is trusted ---
    try:
        bundle = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        reject("invalid_json", detail=str(exc)[:200])
        return result()
    if not isinstance(bundle, dict) or bundle.get("resourceType") != "Bundle":
        reject("not_a_bundle")
        return result()

    by_type: dict[str, list[dict]] = {}
    for entry in bundle.get("entry") or []:
        resource = (entry or {}).get("resource")
        if isinstance(resource, dict):
            by_type.setdefault(resource.get("resourceType"), []).append(resource)
        else:
            reject("entry_without_resource")

    n_patients = len(by_type.get("Patient", []))
    if n_patients != 1:
        reject("expected_one_patient", detail=f"found {n_patients}")
        return result()

    # --- Resource-level checks: bad records are quarantined, the rest load ---
    ctx = BundleContext(today=today)
    for rtype, (table, flatten) in FLATTENERS.items():
        seen: set[str] = set()
        for resource in by_type.get(rtype, []):
            rid = resource.get("id")
            if not rid:
                reject("missing_id", resource)
                continue
            if rid in seen:
                reject("duplicate_id", resource)
                continue
            seen.add(rid)

            try:
                new_rows = flatten(resource, source_file)
            except QualityError as exc:
                reject(exc.reason, resource, exc.detail)
                continue
            failure = next((f for f in (first_failure(table, row, ctx) for row in new_rows) if f), None)
            if failure:
                reject(failure, resource)  # all-or-nothing per resource
                continue

            rows[table].extend(new_rows)
            if rtype == "Patient":
                ctx.patient_id = rid
            elif rtype == "Encounter":
                ctx.encounter_ids.add(rid)

    return result()

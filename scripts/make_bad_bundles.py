"""Create deliberately broken bundles in data/raw/bad to see the quarantine work on real data.

Takes one real Synthea bundle and damages copies of it in known ways.

Usage (from the repo root):
    python scripts/make_bad_bundles.py
"""

import copy
import json
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "data" / "raw" / "synthea" / "fhir"
OUT = REPO / "data" / "raw" / "bad"


def of_type(bundle: dict, rtype: str) -> list[dict]:
    return [e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == rtype]


def main() -> None:
    files = sorted(SRC.glob("*.json"), key=lambda p: p.stat().st_size)
    source = files[len(files) // 2]  # mid-sized: enough records that most still load
    good = json.loads(source.read_text(encoding="utf-8"))
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    def save(name: str, content) -> None:
        text = content if isinstance(content, str) else json.dumps(content)
        (OUT / name).write_text(text, encoding="utf-8")

    # 1. Truncated file -> invalid_json
    save("01_truncated.json", json.dumps(good)[:5000])

    # 2. A bare Patient instead of a Bundle -> not_a_bundle
    save("02_not_a_bundle.json", of_type(good, "Patient")[0])

    # 3. Two patients in one bundle -> expected_one_patient
    two = copy.deepcopy(good)
    two["entry"].append(copy.deepcopy(two["entry"][0]))
    save("03_two_patients.json", two)

    # 4. Mostly fine bundle with individual bad records (the rest should still load)
    mixed = copy.deepcopy(good)
    enc = of_type(mixed, "Encounter")
    obs = of_type(mixed, "Observation")
    cond = of_type(mixed, "Condition")
    enc[0]["period"]["start"] = "not-a-date"                      # invalid_timestamp (+ its children orphaned)
    enc[1]["period"]["end"] = "1900-01-01T00:00:00Z"              # end_before_start (+ children orphaned)
    broken_encounters = {"urn:uuid:" + e["id"] for e in enc[:2]}
    obs_q = [o for o in obs if "valueQuantity" in o
             and o.get("encounter", {}).get("reference") not in broken_encounters]
    obs_q[0]["valueQuantity"]["value"] = "high"                   # invalid_value
    del obs_q[1]["subject"]                                       # missing_subject
    mixed["entry"].append({"resource": copy.deepcopy(obs_q[2])})  # duplicate_id
    cond_ok = [c for c in cond if c.get("encounter", {}).get("reference") not in broken_encounters]
    cond_ok[0]["abatementDateTime"] = "1900-01-01T00:00:00Z"      # abatement_before_onset
    save("04_mixed_errors.json", mixed)

    print(f"Wrote 4 broken bundles to {OUT} (based on {source.name})")


if __name__ == "__main__":
    main()

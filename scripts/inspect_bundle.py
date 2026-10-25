"""Print a readable summary of one Synthea FHIR R4 patient bundle.

Uses only the standard library, so it runs without the venv.

Usage (from the repo root):
    py -3.12 scripts/inspect_bundle.py              # picks a mid-sized bundle from data/raw/synthea/fhir
    py -3.12 scripts/inspect_bundle.py PATH.json    # inspect a specific bundle
"""

import json
import sys
from collections import Counter
from pathlib import Path

FHIR_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / "synthea" / "fhir"

# Short names for the code systems Synthea uses most.
SYSTEMS = {
    "http://loinc.org": "LOINC",
    "http://snomed.info/sct": "SNOMED",
    "http://www.nlm.nih.gov/research/umls/rxnorm": "RxNorm",
    "http://terminology.hl7.org/CodeSystem/v3-ActCode": "ActCode",
}


def pick_bundle(args: list[str]) -> Path:
    if args:
        return Path(args[0])
    files = sorted(FHIR_DIR.glob("*.json"), key=lambda p: p.stat().st_size)
    files = [p for p in files if not p.name.startswith(("hospital", "practitioner"))]
    if not files:
        sys.exit(f"No bundles found in {FHIR_DIR}. Run scripts/generate_synthea.ps1 first.")
    return files[len(files) // 2]  # median size: realistic but not huge


def coding(concept: dict | None) -> str:
    """'SNOMED 44054006 Diabetes mellitus type 2' from a CodeableConcept."""
    if not concept:
        return "-"
    codings = concept.get("coding") or []
    if not codings:
        return concept.get("text", "-")
    c = codings[0]
    system = SYSTEMS.get(c.get("system", ""), c.get("system", "?"))
    return f"{system} {c.get('code', '?')} {c.get('display', '')}".strip()


def code_only(concept: dict | None) -> str:
    """Just the code, e.g. 'vital-signs' or 'active'; '-' if missing."""
    codings = (concept or {}).get("coding") or [{}]
    return codings[0].get("code", "-")


def obs_value(obs: dict) -> str:
    """Observation values come in several shapes ('value[x]')."""
    if "valueQuantity" in obs:
        q = obs["valueQuantity"]
        return f"{q.get('value')} {q.get('unit', '')}".strip()
    if "valueCodeableConcept" in obs:
        return coding(obs["valueCodeableConcept"])
    if "valueString" in obs:
        return obs["valueString"]
    if "component" in obs:  # e.g. blood pressure = systolic + diastolic
        parts = []
        for comp in obs["component"]:
            q = comp.get("valueQuantity", {})
            name = comp.get("code", {}).get("coding", [{}])[0].get("display", "?")
            parts.append(f"{name}={q.get('value')} {q.get('unit', '')}".strip())
        return "; ".join(parts)
    return "(no value)"


def section(title: str) -> None:
    print(f"\n=== {title} " + "=" * max(0, 60 - len(title)))


def main() -> None:
    path = pick_bundle(sys.argv[1:])
    bundle = json.loads(path.read_text(encoding="utf-8"))
    entries = bundle.get("entry", [])
    by_type: dict[str, list[dict]] = {}
    for e in entries:
        r = e["resource"]
        by_type.setdefault(r["resourceType"], []).append(r)

    section("Bundle")
    print(f"file:         {path.name} ({path.stat().st_size / 1024:.0f} KB)")
    print(f"resourceType: {bundle.get('resourceType')}   type: {bundle.get('type')}   entries: {len(entries)}")
    print("resources by type:")
    for rtype, n in Counter({k: len(v) for k, v in by_type.items()}).most_common():
        marker = "  <-- we flatten this" if rtype in {"Patient", "Encounter", "Observation", "Condition"} else ""
        print(f"  {rtype:<28}{n:>6}{marker}")

    section("Patient")
    p = by_type["Patient"][0]
    name = next((n for n in p.get("name", []) if n.get("use") == "official"), p.get("name", [{}])[0])
    addr = (p.get("address") or [{}])[0]
    print(f"id:          {p['id']}")
    print(f"name:        {' '.join(name.get('given', []))} {name.get('family', '')}")
    print(f"gender:      {p.get('gender')}   birthDate: {p.get('birthDate')}")
    print(f"deceased:    {p.get('deceasedDateTime', 'no')}")
    print(f"address:     {addr.get('city')}, {addr.get('state')} {addr.get('postalCode', '')}")
    # Identifier values (SSN, MRN, ...) are synthetic here, but we only print their types:
    # a good habit when the same code later runs on real data.
    id_types = [coding(i.get("type")) for i in p.get("identifier", []) if i.get("type")]
    print(f"identifiers: {len(p.get('identifier', []))} ({', '.join(id_types) or 'untyped'})")

    encounters = by_type.get("Encounter", [])
    section(f"Encounters ({len(encounters)})")
    if encounters:
        starts = sorted(e["period"]["start"] for e in encounters if "period" in e)
        print(f"date range:  {starts[0][:10]} -> {starts[-1][:10]}")
        print("by class:    " + ", ".join(f"{k}={v}" for k, v in
                                          Counter(e.get("class", {}).get("code") for e in encounters).most_common()))
        print("examples:")
        for e in encounters[:3]:
            print(f"  {e['period']['start'][:10]}  class={e.get('class', {}).get('code'):<6} "
                  f"type={coding((e.get('type') or [None])[0])}")

    observations = by_type.get("Observation", [])
    section(f"Observations ({len(observations)})")
    if observations:
        cats = Counter(code_only((o.get("category") or [None])[0]) for o in observations)
        print("by category: " + ", ".join(f"{k}={v}" for k, v in cats.most_common()))
        print("most common codes:")
        for code, n in Counter(coding(o.get("code")) for o in observations).most_common(5):
            print(f"  {n:>4}x  {code}")
        print("examples:")
        for o in observations[:4]:
            print(f"  {o.get('effectiveDateTime', '?')[:10]}  {coding(o.get('code'))[:55]:<55} = {obs_value(o)}")

    conditions = by_type.get("Condition", [])
    section(f"Conditions ({len(conditions)})")
    for c in conditions[:10]:
        status = code_only(c.get("clinicalStatus"))
        print(f"  onset {c.get('onsetDateTime', '?')[:10]}  {status:<9} {coding(c.get('code'))}")
    if len(conditions) > 10:
        print(f"  ... and {len(conditions) - 10} more")

    # How resources point at each other: subject/encounter references use the "urn:uuid:..."
    # fullUrl of another entry in the same bundle. Our flattener will turn these into join keys.
    section("References")
    full_urls = {e.get("fullUrl") for e in entries}
    resolved, external = Counter(), Counter()
    for rtype in ("Encounter", "Observation", "Condition"):
        for r in by_type.get(rtype, []):
            for field in ("subject", "encounter", "serviceProvider"):
                ref = (r.get(field) or {}).get("reference")
                if ref:
                    (resolved if ref in full_urls else external)[f"{rtype}.{field}"] += 1
    for key in sorted(set(resolved) | set(external)):
        print(f"  {key:<28} in-bundle={resolved[key]:<6} external={external[key]}")
    sample = next((o for o in observations if o.get("encounter")), None)
    if sample:
        print(f"\nexample: Observation {sample['id'][:8]}...")
        print(f"  subject   -> {sample['subject']['reference']}")
        print(f"  encounter -> {sample['encounter']['reference']}")


if __name__ == "__main__":
    main()

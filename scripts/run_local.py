"""Run the ingest pipeline locally: bronze FHIR JSON -> silver Parquet + quarantine.

Uses the same code as the Lambda; a local folder stands in for the curated bucket.

Usage (from the repo root, venv active):
    python scripts/run_local.py
    python scripts/run_local.py --input data/raw/bad --output data/curated_bad
"""

import argparse
import shutil
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ingest.pipeline import process_bundle  # noqa: E402
from ingest.writer import LocalSink, file_id_for, write_result  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--input", default="data/raw/synthea/fhir", help="folder of bundle .json files")
    ap.add_argument("--output", default="data/curated", help="local stand-in for the curated bucket")
    ap.add_argument("--ingest-date", type=date.fromisoformat, default=date.today(),
                    help="partition date, YYYY-MM-DD (default: today)")
    ap.add_argument("--keep", action="store_true", help="keep existing output instead of starting clean")
    args = ap.parse_args()

    in_dir, out_dir = REPO / args.input, REPO / args.output
    files = sorted(in_dir.glob("*.json"))
    if not files:
        print(f"No .json files in {in_dir}")
        return 1
    if out_dir.exists() and not args.keep:
        shutil.rmtree(out_dir)

    sink = LocalSink(out_dir)
    totals, reasons = Counter(), Counter()
    started = time.perf_counter()
    for path in files:
        source = path.relative_to(REPO).as_posix()  # lineage: which bronze file a row came from
        result = process_bundle(path.read_bytes(), source_file=source, today=args.ingest_date)
        write_result(result, sink, ingest_date=args.ingest_date, file_id=file_id_for(source))
        counts = result.counts()
        reasons.update(counts.pop("quarantine_reasons"))
        totals.update(counts)
    elapsed = time.perf_counter() - started

    print(f"Processed {len(files)} bundles in {elapsed:.1f}s -> {out_dir}")
    for name in ("patients", "encounters", "observations", "conditions"):
        print(f"  {name:<13}{totals[f'rows_{name}']:>8} rows")
    print(f"  {'quarantined':<13}{totals['quarantined']:>8} records")
    for reason, n in reasons.most_common():
        print(f"      {reason:<26}{n:>5}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

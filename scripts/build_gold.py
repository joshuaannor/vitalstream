"""Build the gold tables locally with DuckDB: silver Parquet -> data/curated/gold/<table>/.

Runs the exact SQL in sql/gold/ that Athena will run as CTAS in AWS.

Usage (from the repo root, venv active, after run_local.py):
    python scripts/build_gold.py
"""

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from analytics.catalog import GOLD_DB  # noqa: E402
from analytics.gold import load_gold_queries  # noqa: E402
from analytics.local import build_gold, connect, format_rows  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--curated", default="data/curated")
    ap.add_argument("--preview", type=int, default=3, help="rows to show per table")
    args = ap.parse_args()
    curated = REPO / args.curated

    con = connect(curated)
    queries = load_gold_queries()
    counts = build_gold(con, queries, curated / "gold")

    print(f"Built {len(queries)} gold tables in {curated / 'gold'}")
    for q in queries:
        part = f"partitioned by {q.partitioned_by}" if q.partitioned_by else "not partitioned"
        print(f"  {q.name:<22}{counts[q.name]:>7} rows  ({part})")
    for q in queries:
        print(f"\n=== {GOLD_DB}.{q.name}: {q.description}")
        print(format_rows(con.execute(f"SELECT * FROM {GOLD_DB}.{q.name} LIMIT {args.preview}")))
    return 0


if __name__ == "__main__":
    sys.exit(main())

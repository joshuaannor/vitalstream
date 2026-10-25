"""Run the analytics questions in sql/analytics/ against the local silver and gold tables.

Usage (from the repo root, venv active, after build_gold.py):
    python scripts/run_queries.py            # all questions
    python scripts/run_queries.py 02         # only files whose name contains "02"
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from analytics.gold import load_analytics_queries  # noqa: E402
from analytics.local import connect, format_rows  # noqa: E402


def main() -> int:
    match = sys.argv[1] if len(sys.argv) > 1 else ""
    con = connect(REPO / "data" / "curated")
    queries = [q for q in load_analytics_queries() if match in q.name]
    if not queries:
        print(f"No query in sql/analytics matches {match!r}")
        return 1
    for q in queries:
        print(f"\n=== {q.description}")
        print(format_rows(con.execute(q.sql)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

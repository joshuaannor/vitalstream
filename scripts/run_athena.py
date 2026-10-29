"""Create the Athena tables, build gold with CTAS, and run the analytics questions, in AWS.

Uses the same SQL as the local DuckDB run (sql/gold, sql/analytics) and the deployed
stack's bucket and workgroup. Every query reports how much data it scanned (Athena
bills per TB scanned; the workgroup stops any query over 1 GB).

Usage (from the repo root, venv active, after the bundles are uploaded):
    python scripts/run_athena.py              # silver + gold + questions
    python scripts/run_athena.py silver       # only CREATE EXTERNAL TABLE / views
    python scripts/run_athena.py gold         # only rebuild the gold tables
    python scripts/run_athena.py questions    # only the analytics questions
"""

import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from analytics.catalog import athena_silver_ddl  # noqa: E402
from analytics.gold import athena_ctas, load_analytics_queries, load_gold_queries  # noqa: E402
from stack import session, stack_outputs  # noqa: E402


class Athena:
    def __init__(self, sess, workgroup: str):
        self.client = sess.client("athena")
        self.workgroup = workgroup
        self.scanned_bytes = 0

    def run(self, sql: str) -> dict:
        """Run one statement and wait for it. Raises with Athena's error message on failure."""
        qid = self.client.start_query_execution(QueryString=sql, WorkGroup=self.workgroup)["QueryExecutionId"]
        while True:
            q = self.client.get_query_execution(QueryExecutionId=qid)["QueryExecution"]
            state = q["Status"]["State"]
            if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
                break
            time.sleep(1)
        if state != "SUCCEEDED":
            reason = q["Status"].get("StateChangeReason", state)
            raise RuntimeError(f"Athena query {state}: {reason}\n--- SQL ---\n{sql[:800]}")
        self.scanned_bytes += q["Statistics"].get("DataScannedInBytes", 0)
        return q

    def rows(self, query: dict) -> list[list[str]]:
        """Result rows (header first) as strings."""
        out = []
        paginator = self.client.get_paginator("get_query_results")
        for page in paginator.paginate(QueryExecutionId=query["QueryExecutionId"]):
            for row in page["ResultSet"]["Rows"]:
                out.append([c.get("VarCharValue", "") for c in row["Data"]])
        return out


def print_rows(rows: list[list[str]], max_width: int = 28) -> None:
    rows = [[v[:max_width] for v in r] for r in rows]
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    for n, r in enumerate(rows):
        print("  ".join(v.ljust(w) for v, w in zip(r, widths)))
        if n == 0:
            print("  ".join("-" * w for w in widths))
    print(f"({len(rows) - 1} rows)")


def empty_prefix(s3, bucket: str, prefix: str) -> int:
    """Delete current objects under a prefix (CTAS needs an empty location). Old versions expire via lifecycle."""
    deleted = 0
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
        if keys:
            s3.delete_objects(Bucket=bucket, Delete={"Objects": keys})
            deleted += len(keys)
    return deleted


def main() -> int:
    step = sys.argv[1] if len(sys.argv) > 1 else "all"
    if step not in ("all", "silver", "gold", "questions"):
        print(__doc__)
        return 1

    sess = session()
    out = stack_outputs(sess)
    bucket, workgroup = out["CuratedBucketName"], out["AthenaWorkGroupName"]
    athena = Athena(sess, workgroup)
    print(f"Workgroup {workgroup}, bucket {bucket}")

    if step in ("all", "silver"):
        stmts = athena_silver_ddl(bucket)
        print(f"\nSilver: {len(stmts)} statements (databases, external tables, latest-record views)")
        for sql in stmts:
            athena.run(sql)
        for table in ("patients", "encounters", "observations", "conditions"):
            q = athena.run(f"SELECT count(*) FROM vitalstream_silver.{table}")
            print(f"  vitalstream_silver.{table:<13}{athena.rows(q)[1][0]:>8} rows")

    if step in ("all", "gold"):
        s3 = sess.client("s3")
        print("\nGold: CREATE TABLE AS SELECT")
        for query in load_gold_queries():
            empty_prefix(s3, bucket, f"gold/{query.name}/")
            for sql in athena_ctas(query, bucket):
                athena.run(sql)
            q = athena.run(f"SELECT count(*) FROM vitalstream_gold.{query.name}")
            print(f"  vitalstream_gold.{query.name:<22}{athena.rows(q)[1][0]:>7} rows")

    if step in ("all", "questions"):
        for query in load_analytics_queries():
            print(f"\n=== {query.description}")
            print_rows(athena.rows(athena.run(query.sql)))

    print(f"\nData scanned this run: {athena.scanned_bytes / 1024 / 1024:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())

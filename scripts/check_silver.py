"""Check the local silver tables with DuckDB: row counts, unique keys, joins that must line up.

Usage (from the repo root, venv active, after run_local.py):
    python scripts/check_silver.py
    python scripts/check_silver.py --root data/curated_bad
"""

import argparse
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ingest.schemas import PRIMARY_KEYS, SCHEMAS  # noqa: E402

# Each check counts "bad" rows; 0 means pass.
CHECKS = {
    "encounters -> patients": """
        SELECT count(*) FROM encounters e LEFT JOIN patients p USING (patient_id)
        WHERE p.patient_id IS NULL""",
    "observations -> encounters": """
        SELECT count(*) FROM observations o LEFT JOIN encounters e USING (encounter_id)
        WHERE o.encounter_id IS NOT NULL AND e.encounter_id IS NULL""",
    "conditions -> encounters": """
        SELECT count(*) FROM conditions c LEFT JOIN encounters e USING (encounter_id)
        WHERE c.encounter_id IS NOT NULL AND e.encounter_id IS NULL""",
    "encounter end >= start": "SELECT count(*) FROM encounters WHERE end_at < start_at",
    "quantity rows have a number": """
        SELECT count(*) FROM observations WHERE value_type = 'quantity' AND value_num IS NULL""",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data/curated")
    silver = REPO / ap.parse_args().root / "silver"

    con = duckdb.connect()

    def scalar(sql: str):
        return con.execute(sql).fetchall()[0][0]

    for table in PRIMARY_KEYS:
        if any((silver / table).glob("*/*.parquet")):
            con.execute(f"""CREATE VIEW {table} AS SELECT * FROM read_parquet(
                '{silver.as_posix()}/{table}/*/*.parquet', hive_partitioning = true)""")
        else:  # no files yet: an empty table with the right columns
            con.register(table, SCHEMAS[table].empty_table())

    print("Row counts")
    for table in PRIMARY_KEYS:
        print(f"  {table:<13}{scalar(f'SELECT count(*) FROM {table}'):>8}")

    failures = 0
    print("\nChecks (0 bad rows = pass)")
    for table, keys in PRIMARY_KEYS.items():
        cols = ", ".join(keys)
        CHECKS[f"{table} key unique ({cols})"] = (
            f"SELECT count(*) - count(DISTINCT ({cols})) FROM {table}")
    for name, sql in CHECKS.items():
        bad = scalar(sql)
        failures += bad > 0
        print(f"  {'PASS' if bad == 0 else 'FAIL'}  {name:<48} {bad}")

    print("\nSample: latest blood pressure per patient (first 5)")
    rows = con.execute("""
        SELECT left(patient_id, 8) AS patient, effective_at::DATE AS date,
               max(value_num) FILTER (code = '8480-6') AS systolic,
               max(value_num) FILTER (code = '8462-4') AS diastolic
        FROM observations WHERE panel_code = '85354-9'
        GROUP BY patient_id, effective_at
        QUALIFY row_number() OVER (PARTITION BY patient_id ORDER BY effective_at DESC) = 1
        ORDER BY patient LIMIT 5""").fetchall()
    print(f"  {'patient':<10}{'date':<12}{'systolic':>9}{'diastolic':>10}")
    for patient, day, sys_bp, dia_bp in rows:
        print(f"  {patient:<10}{day.isoformat():<12}{sys_bp:>9.0f}{dia_bp:>10.0f}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

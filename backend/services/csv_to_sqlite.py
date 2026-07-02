#!/usr/bin/env python3
"""
CSV → SQLite auto-converter for data analysis workflow.

Creates a temporary SQLite database from an uploaded CSV file,
ready for sqlite_execute queries via the sql-analyst skill.
"""
import csv
import io
import sqlite3
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Directory for analysis SQLite databases
ANALYSIS_DB_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "analysis_dbs"


def csv_to_sqlite(
    csv_path: str,
    table_name: str = "data",
    db_path: Optional[str] = None,
) -> str:
    """
    Convert a CSV file to a SQLite database.

    Args:
        csv_path: Path to the CSV file (with header row)
        table_name: Name for the SQLite table
        db_path: Optional path for the .db file. If None, auto-generates
                 as data/analysis_dbs/{csv_name}.db

    Returns:
        Absolute path to the created/updated .db file
    """
    csv_file = Path(csv_path)
    if not csv_file.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    # Read CSV content
    with open(csv_path, "r", encoding="utf-8") as f:
        # Try reading a sample to detect BOM and encoding issues
        csv_content = f.read()

    reader = csv.DictReader(io.StringIO(csv_content))
    rows = list(reader)
    if not rows:
        raise ValueError(f"CSV file has no data rows: {csv_path}")

    col_names = list(rows[0].keys())

    # Determine DB path
    if db_path is None:
        ANALYSIS_DB_DIR.mkdir(parents=True, exist_ok=True)
        db_stem = csv_file.stem
        # Avoid collisions
        db_path = str(ANALYSIS_DB_DIR / f"{db_stem}.db")
        counter = 1
        while Path(db_path).exists():
            db_path = str(ANALYSIS_DB_DIR / f"{db_stem}_{counter}.db")
            counter += 1

    db_file = Path(db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)

    # Create table — infer types from data (simple heuristic: TEXT or REAL)
    col_types = {}
    for col in col_names:
        sample_values = [r.get(col, "") for r in rows[:100] if r.get(col, "") != ""]
        all_numeric = True
        for v in sample_values:
            try:
                float(v)
            except (ValueError, TypeError):
                all_numeric = False
                break
        col_types[col] = "REAL" if all_numeric and sample_values else "TEXT"

    col_defs = ", ".join(f'"{c}" {col_types[c]}' for c in col_names)
    placeholders = ", ".join("?" for _ in col_names)

    # Connect and create
    conn = sqlite3.connect(str(db_path))

    # Drop existing table if re-creating
    cursor = conn.cursor()
    # Use safe table name (remove special chars)
    safe_table = "".join(c for c in table_name if c.isalnum() or c == "_")
    if not safe_table:
        safe_table = "data"

    cursor.execute(f"DROP TABLE IF EXISTS \"{safe_table}\"")
    cursor.execute(f'CREATE TABLE "{safe_table}" ({col_defs})')

    # Insert rows
    col_list = ", ".join(f'"{c}"' for c in col_names)
    for row in rows:
        values = [row.get(c, "") for c in col_names]
        cursor.execute(
            f'INSERT INTO "{safe_table}" ({col_list}) VALUES ({placeholders})',
            values,
        )

    conn.commit()
    conn.close()

    logger.info(
        f"CSV→SQLite: {csv_path} → {db_path} "
        f"({len(rows)} rows, {len(col_names)} cols in '{safe_table}')"
    )

    return str(db_path)


def csv_to_sqlite_from_bytes(
    csv_bytes: bytes,
    csv_filename: str,
    table_name: str = "data",
) -> str:
    """
    Convert CSV bytes to a SQLite database.

    Args:
        csv_bytes: Raw CSV file content as bytes
        csv_filename: Original filename (used to generate .db name)
        table_name: Name for the SQLite table

    Returns:
        Absolute path to the created .db file
    """
    ANALYSIS_DB_DIR.mkdir(parents=True, exist_ok=True)
    db_stem = Path(csv_filename).stem
    db_path = str(ANALYSIS_DB_DIR / f"{db_stem}.db")

    # Avoid collisions
    counter = 1
    while Path(db_path).exists():
        db_path = str(ANALYSIS_DB_DIR / f"{db_stem}_{counter}.db")
        counter += 1

    # Write CSV temp file
    csv_path = str(ANALYSIS_DB_DIR / f"{db_stem}_temp.csv")
    Path(csv_path).write_bytes(csv_bytes)

    try:
        result = csv_to_sqlite(csv_path, table_name=table_name, db_path=db_path)
    finally:
        # Clean up temp CSV
        Path(csv_path).unlink(missing_ok=True)

    return result

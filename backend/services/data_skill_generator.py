"""
Data Skill Generator — auto-generates a .skill.md companion file from a CSV dataset.

When a user uploads a CSV, this service reads its schema and sample rows,
then produces a structured .skill.md file describing column semantics, basic
business logic, and common analysis patterns. The companion is saved alongside
the CSV in the sandbox so the analysis agent can use it as dataset-specific context.

Usage:
    from services.data_skill_generator import generate_data_skill
    skill_path = generate_data_skill("/path/to/data.csv", "/path/to/sandbox")
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _describe_dtype(dtype: str) -> str:
    """Map pandas dtype string to a user-friendly type label."""
    dtype_lower = dtype.lower()
    if "int" in dtype_lower or "float" in dtype_lower:
        return "numeric"
    if "datetime" in dtype_lower or "datetimetz" in dtype_lower:
        return "datetime"
    if "bool" in dtype_lower:
        return "boolean"
    if "object" in dtype_lower or "str" in dtype_lower or "string" in dtype_lower:
        return "categorical / text"
    if "category" in dtype_lower:
        return "categorical"
    return "other"


def _generate_frontmatter(stem: str, columns: list, row_count: int) -> str:
    """Generate YAML frontmatter for the .skill.md file."""
    col_names = [c["name"] for c in columns]
    desc = f"Auto-generated companion skill for {stem}. "
    desc += f"Columns: {', '.join(col_names)}. "
    desc += f"{row_count} rows."

    tags = ["data-analysis", "auto-generated", stem.replace(" ", "-").lower()]
    # Detect relevant tags from column names
    col_lower = " ".join(col_names).lower()
    for keyword in ["revenue", "sales", "price", "cost", "amount"]:
        if keyword in col_lower:
            tags.append("finance")
            break
    for keyword in ["date", "time", "year", "month", "day"]:
        if keyword in col_lower:
            tags.append("time-series")
            break
    for keyword in ["region", "country", "city", "state", "location"]:
        if keyword in col_lower:
            tags.append("geographic")
            break

    tags_str = "\n" + "\n".join(f"  - {t!r}" for t in tags)
    return (
        "---\n"
        f"name: {stem}\n"
        f"description: >-\n"
        f"  {desc}\n"
        f"tags:{tags_str}\n"
        "triggers:\n"
        f'  - "when user uploaded {stem}.csv"\n'
        '  - "when user asks about this dataset"\n'
        "allowed-tools: [read_file, execute, save_analysis_result]\n"
        "author: Auto-generated\n"
        "---\n"
    )


def _generate_column_definitions(columns: list, sample_data: dict) -> str:
    """Generate Column Definitions markdown table."""
    lines = [
        "## Column Definitions\n",
        "| Column | Type | Sample Values | Null % |",
        "|---|---|---|---|",
    ]
    for c in columns:
        name = c["name"]
        dtype = _describe_dtype(c["dtype"])
        samples = c["sample_values"]
        # Format sample values for display
        sample_str = ", ".join(str(v) for v in samples[:3])
        if len(sample_str) > 60:
            sample_str = sample_str[:57] + "..."
        null_pct = c.get("null_pct", 0)
        null_str = f"{null_pct}%" if null_pct > 0 else "0%"
        lines.append(f"| `{name}` | {dtype} | {sample_str} | {null_str} |")

    lines.append("")  # trailing blank line
    return "\n".join(lines)


def _generate_basic_profile(df_metadata: dict) -> str:
    """Generate a basic data profile section."""
    lines = ["## Basic Data Profile\n"]
    lines.append(f"- **Rows**: {df_metadata['row_count']}")
    lines.append(f"- **Columns**: {df_metadata['column_count']}")
    lines.append(f"- **Numeric columns**: {df_metadata['numeric_count']}")
    lines.append(f"- **Categorical / text columns**: {df_metadata['categorical_count']}")
    lines.append(f"- **Columns with null values**: {df_metadata['columns_with_null']}")
    lines.append(f"- **Total null cells**: {df_metadata['total_null_cells']}")

    # Auto-detect if there are ID-like columns
    id_cols = df_metadata.get("id_like_columns", [])
    if id_cols:
        lines.append(f"- **Likely ID columns**: {', '.join(f'`{c}`' for c in id_cols)}")

    lines.append("")
    return "\n".join(lines)


def _generate_sample_queries(columns: list) -> str:
    """Generate sample SQL queries based on detected column types."""
    lines = ["## Sample SQL Queries\n"]
    lines.append("```sql")

    # Basic select
    col_names = [c["name"] for c in columns]
    sample_cols = ", ".join(col_names[:5])
    if len(col_names) > 5:
        sample_cols += ", ..."
    lines.append(f"-- View all data")
    lines.append(f"SELECT {sample_cols}")
    lines.append("FROM <table_name>")
    lines.append("LIMIT 100;")
    lines.append("")

    # Count
    lines.append("-- Row count")
    lines.append("SELECT COUNT(*) as row_count")
    lines.append("FROM <table_name>;")
    lines.append("")

    # Group by on categorical columns
    cat_cols = [c["name"] for c in columns if _describe_dtype(c["dtype"]) in ("categorical", "categorical / text")]
    num_cols = [c["name"] for c in columns if _describe_dtype(c["dtype"]) == "numeric"]
    if cat_cols and num_cols:
        cat = cat_cols[0]
        num = num_cols[0]
        escaped = f'"{cat}"' if " " in cat else cat
        escaped_num = f'"{num}"' if " " in num else num
        lines.append(f"-- Aggregation by {cat}")
        lines.append(f"SELECT {escaped}, SUM({escaped_num}) as total, AVG({escaped_num}) as avg")
        lines.append("FROM <table_name>")
        lines.append(f"GROUP BY {escaped}")
        lines.append("ORDER BY total DESC;")
        lines.append("")

    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def _generate_edge_cases(columns: list) -> str:
    """Generate edge case section based on column analysis."""
    lines = ["## Edge Cases & Notes\n"]

    null_cols = [c["name"] for c in columns if c.get("null_count", 0) > 0]
    if null_cols:
        lines.append(f"- **Null values** exist in columns: {', '.join(f'`{c}`' for c in null_cols)}")
        lines.append("  - Handle missing values before aggregation (fill or drop).")

    space_cols = [c["name"] for c in columns if " " in c["name"]]
    if space_cols:
        lines.append(f"- **Column names with spaces**: {', '.join(f'`{c}`' for c in space_cols)}")
        lines.append("  - Must be quoted in SQL. Use backticks or double quotes.")
        lines.append("  - In pandas, access via `df['column name']`.")

    has_dates = any(_describe_dtype(c["dtype"]) == "datetime" for c in columns)
    if not has_dates and any("date" in c["name"].lower() or "time" in c["name"].lower() for c in columns):
        lines.append("- **Date/time columns** detected by name but stored as strings.")
        lines.append("  - Cast to datetime using `pd.to_datetime()` for time-series operations.")

    lines.append("")
    return "\n".join(lines)


def generate_data_skill(csv_path: str, sandbox_dir: str) -> Optional[str]:
    """
    Generate a .skill.md companion file for a CSV dataset.

    Args:
        csv_path: Absolute path to the CSV file.
        sandbox_dir: Sandbox directory where the .skill.md will be saved.

    Returns:
        Path to the generated .skill.md file, or None on failure.
    """
    import pandas as pd

    csv_path = Path(csv_path)
    if not csv_path.exists():
        logger.warning(f"CSV not found: {csv_path}")
        return None

    sandbox_dir = Path(sandbox_dir)
    output_path = sandbox_dir / f"{csv_path.stem}.skill.md.pending"

    # Don't overwrite an existing companion (e.g. user-provided).
    if output_path.exists():
        logger.info(f"Companion .skill.md already exists: {output_path}")
        return str(output_path)

    try:
        # Read just enough for schema + sample data
        df = pd.read_csv(csv_path, nrows=50)
        if df.empty:
            logger.warning(f"CSV is empty: {csv_path}")
            return None
    except Exception as e:
        logger.warning(f"Failed to read CSV for skill generation: {e}")
        return None

    # Extract column metadata
    columns = []
    sample_data = {}
    for col in df.columns:
        non_null = df[col].dropna()
        samples = non_null.head(3).tolist()
        null_count = int(df[col].isna().sum())
        null_pct = round(null_count / max(len(df), 1) * 100, 1)
        columns.append({
            "name": str(col),
            "dtype": str(df[col].dtype),
            "sample_values": samples,
            "null_count": null_count,
            "null_pct": null_pct,
        })
        sample_data[str(col)] = {
            "values": samples,
            "dtype": str(df[col].dtype),
        }

    # Build metadata summary
    numeric_count = sum(1 for c in columns if _describe_dtype(c["dtype"]) == "numeric")
    cat_count = sum(1 for c in columns if _describe_dtype(c["dtype"]) in ("categorical", "categorical / text"))
    columns_with_null = sum(1 for c in columns if c["null_count"] > 0)
    total_null = sum(c["null_count"] for c in columns)

    id_like = [
        c["name"] for c in columns
        if c["name"].lower() in ("id", "key", "pk", "primary_key")
        or c["name"].lower().endswith("_id")
    ]

    df_metadata = {
        "row_count": len(df),
        "column_count": len(columns),
        "numeric_count": numeric_count,
        "categorical_count": cat_count,
        "columns_with_null": columns_with_null,
        "total_null_cells": total_null,
        "id_like_columns": id_like,
    }

    try:
        # Read full row count (for accuracy)
        # Use wc -l or similar for efficiency on large files
        full_count = len(df)
        try:
            import subprocess
            result = subprocess.run(
                ["wc", "-l", str(csv_path)], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                full_count = int(result.stdout.strip().split()[0]) - 1  # minus header
        except Exception:
            pass  # fall back to sampled count
        df_metadata["row_count"] = max(full_count, len(df))
    except Exception:
        pass

    # Build the .skill.md content
    sections = []

    # Frontmatter
    sections.append(_generate_frontmatter(csv_path.stem, columns, df_metadata["row_count"]))

    # Overview
    sections.append(
        f"Auto-generated companion skill for `{csv_path.name}`. "
        f"Use alongside the system `data-analysis` skill.\n"
    )

    # Column Definitions
    sections.append(_generate_column_definitions(columns, sample_data))

    # Basic Profile
    sections.append(_generate_basic_profile(df_metadata))

    # Sample Queries
    sections.append(_generate_sample_queries(columns))

    # Edge Cases
    sections.append(_generate_edge_cases(columns))

    content = "\n".join(sections)

    # Write the companion file
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
        logger.info(f"Generated data skill companion: {output_path}")
        return str(output_path)
    except Exception as e:
        logger.warning(f"Failed to write data skill companion: {e}")
        return None

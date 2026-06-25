"""
Generic CSV transformation wizard.

Reads a YAML rules file + input CSV → outputs cleaned CSV validated against
a Pydantic schema.

RULES FORMAT (YAML):
```yaml
schema: CleanedSalesRow          # Pydantic model name (from schemas/registry)
source: enterprise_data/*.csv     # input path(s)
target: enterprise_data/cleaned.csv

# Column mapping (source alias → canonical name + type)
mapping:
  - from: [tx_id, TransactionID]
    to: transaction_id
    type: str
  - from: [market, Region]
    to: region
    type: str
    transform: upper.strip
  - from: [price_per_unit, Unit_Price]
    to: unit_price
    type: float
    transform: strip_dollar_comma
```

SUPPORTED TRANSFORMS (whitelist, not arbitrary expressions):
- upper           : "us" → "US"
- lower           : "US" → "us"
- strip           : " US " → "US"
- upper.strip     : combined
- strip_dollar_comma : "$1,250.00" → 1250.0
- strip_percent   : "15%" → 15.0
- to_int          : "20" → 20
- to_float        : "500.0" → 500.0

NOT a DSL — keep it simple, predictable, safe.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from pydantic import BaseModel, ValidationError

from schemas.sales import get_schema


# ── Transform primitives ─────────────────────────────────────────────

def _strip_dollar_comma(s: Any) -> float:
    """'$1,250.00' → 1250.0"""
    if pd.isna(s):
        return 0.0
    return float(str(s).replace("$", "").replace(",", "").strip())


def _strip_percent(s: Any) -> float:
    """'15%' → 15.0"""
    if pd.isna(s):
        return 0.0
    return float(str(s).replace("%", "").strip())


_TRANSFORMS = {
    "upper": lambda s: str(s).upper(),
    "lower": lambda s: str(s).lower(),
    "strip": lambda s: str(s).strip(),
    "upper.strip": lambda s: str(s).upper().strip(),
    "strip_dollar_comma": _strip_dollar_comma,
    "strip_percent": _strip_percent,
    "to_int": lambda s: int(float(s)) if pd.notna(s) else 0,
    "to_float": lambda s: float(s) if pd.notna(s) else 0.0,
}


# ── Rules loading ─────────────────────────────────────────────────────

@dataclass
class MappingRule:
    """One column mapping rule."""
    from_aliases: list[str]
    to: str
    type: str  # str, int, float
    transform: str | None = None
    default: Any = None


@dataclass
class CleaningSpec:
    """Loaded YAML rules."""
    schema_name: str
    source: str
    target: str
    mapping: list[MappingRule]

    @property
    def schema_class(self) -> type[BaseModel]:
        return get_schema(self.schema_name)


def load_spec(yaml_path: Path) -> CleaningSpec:
    """Load cleaning rules from YAML.

    Source/target paths are resolved relative to the YAML file's directory,
    so the rules are portable across machines and cwd.
    """
    yaml_path = Path(yaml_path).resolve()
    base_dir = yaml_path.parent

    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))

    def _resolve(p: str) -> Path:
        pp = Path(p)
        if pp.is_absolute():
            return pp
        return base_dir / pp

    rules = []
    for r in data.get("mapping", []):
        # YAML list can be a single string or list
        aliases = r["from"]
        if isinstance(aliases, str):
            aliases = [aliases]
        rules.append(MappingRule(
            from_aliases=aliases,
            to=r["to"],
            type=r["type"],
            transform=r.get("transform"),
            default=r.get("default"),
        ))

    return CleaningSpec(
        schema_name=data["schema"],
        source=str(_resolve(data["source"]).resolve()),
        target=str(_resolve(data["target"]).resolve()),
        mapping=rules,
    )


# ── Wizard core ───────────────────────────────────────────────────────

def _find_source_column(df: pd.DataFrame, aliases: list[str]) -> str | None:
    """Find which alias exists in the dataframe."""
    for alias in aliases:
        if alias in df.columns:
            return alias
    return None


def _apply_transform(values: pd.Series, transform: str | None) -> pd.Series:
    """Apply a single named transform."""
    if not transform:
        return values
    if transform not in _TRANSFORMS:
        raise ValueError(f"Unknown transform: {transform}. Available: {list(_TRANSFORMS)}")
    return values.apply(_TRANSFORMS[transform])


def _coerce_type(values: pd.Series, target_type: str) -> pd.Series:
    """Cast to target type, filling NaN with sensible defaults."""
    if target_type == "str":
        return values.astype(str).fillna("")
    if target_type == "int":
        # Int64 supports NaN; fill with 0
        return pd.to_numeric(values, errors="coerce").fillna(0).astype("Int64")
    if target_type == "float":
        return pd.to_numeric(values, errors="coerce").fillna(0.0).astype(float)
    raise ValueError(f"Unsupported type: {target_type}")


def apply_spec(spec: CleaningSpec, input_csv: Path) -> tuple[pd.DataFrame, list[str]]:
    """Apply cleaning spec to a single CSV file. Returns (cleaned_df, warnings)."""
    df = pd.read_csv(input_csv)
    warnings = []
    cleaned = pd.DataFrame()

    for rule in spec.mapping:
        src_col = _find_source_column(df, rule.from_aliases)
        if src_col is None:
            warnings.append(f"No source column found for {rule.to} (tried {rule.from_aliases})")
            # Use default if provided
            if rule.default is not None:
                cleaned[rule.to] = rule.default
            continue

        values = df[src_col]
        values = _apply_transform(values, rule.transform)
        values = _coerce_type(values, rule.type)
        cleaned[rule.to] = values

    return cleaned, warnings


def validate_against_schema(df: pd.DataFrame, schema_class: type[BaseModel]) -> list[str]:
    """Validate each row against Pydantic schema. Returns list of error messages."""
    errors = []
    for idx, row in df.iterrows():
        try:
            schema_class.model_validate(row.to_dict())
        except ValidationError as e:
            errors.append(f"Row {idx}: {e.error_messages()[0] if hasattr(e, 'error_messages') else e}")
    return errors


def run(spec_path: Path, input_path: Path | None = None) -> dict:
    """Main entry point: load spec, apply to input, validate, save.

    Returns a result dict with status, row counts, warnings, errors.
    """
    spec = load_spec(spec_path)
    input_csv = input_path or Path(spec.source)
    if "*" in str(input_csv):
        # Glob pattern — process first match
        matches = list(input_csv.parent.glob(input_csv.name))
        if not matches:
            return {"status": "error", "error": f"No files match {input_csv}"}
        input_csv = matches[0]

    df, warnings = apply_spec(spec, input_csv)

    # Validate against schema
    errors = validate_against_schema(df, spec.schema_class)

    # Save only if no validation errors (or save with warning flag)
    output = Path(spec.target)
    if not errors:
        output.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output, index=False)
        status = "ok"
    else:
        status = "validation_failed"

    return {
        "status": status,
        "input": str(input_csv),
        "output": str(output) if status == "ok" else None,
        "rows_in": len(df),
        "rows_valid": len(df) - len(errors),
        "warnings": warnings,
        "errors": errors,
        "schema": spec.schema_name,
    }


# ── CLI ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m core.data_prep.wizard <rules.yaml> [input.csv]")
        sys.exit(1)

    spec_path = Path(sys.argv[1])
    input_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    result = run(spec_path, input_path)
    print(json.dumps(result, indent=2, default=str))
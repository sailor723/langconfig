"""Seed the `ontology_verify_stage` BUILTIN tool row (is_builtin = true).

Why this tool exists: the manager dispatches one expert per rung and gets back a JSON receipt — a CLAIM.
Nothing checked the claim. Measured 2026-11-25: the builder's `tables` expert still carried `db_query`,
a tool deleted hours earlier, and no gate noticed; a `metrics` expert can return "done" while the board
names a metric nobody declared. The manager needs a mechanical answer to "did that expert actually meet
its target?", and it must not be the same model that just did the work.

What it does: `features/ontology/stage_checks.py` — file presence, parsed JSON, set inclusion, exact row
counts, and the existing gate scripts' own verdicts. Read-only: it never fixes anything.

What it deliberately does NOT do: write declarations, build databases, or install anything. A check that
repairs is not a check.

Idempotent: re-running updates the row in place.

    cd backend && .venv/bin/python scripts/seeds/in/seed_ontology_verify_tool.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

for _p in Path(__file__).resolve().parents:
    if (_p / "_seedpaths.py").exists():
        sys.path.insert(0, str(_p))
        break
from _seedpaths import BACKEND, REPO  # noqa: E402,F401

from db.database import SessionLocal  # noqa: E402
from sqlalchemy import text  # noqa: E402

TOOL_ID = "ontology_verify_stage"

DESCRIPTION = (
    "Verify that the rung you just delegated actually landed — mechanically, before you report it. "
    "Pass `stage` (plan | build | structure | metrics | board | publish) and the key/db it concerns: "
    "plan checks a plan file covers every sheet AND that no database was created yet; build checks the "
    "database exists with the promised row counts per table; structure/metrics/board run the repo's own "
    "gate scripts (check_structure / check_samples / check_dashboard) plus declaration-vs-board id "
    "coverage; publish checks the profile exists and its version is registered. "
    "Read-only — it never fixes anything. A FAIL lists the named checks that failed; do not advance to "
    "the next rung, re-dispatch the expert with those names."
)

CODE = r'''# --- imports ---
def ontology_verify_stage(stage: str, ontology_key: str = "", db_name: str = "",
                          plan_path: str = "", expect: str = "", sheets: str = "") -> str:
    """Check one rung of the ontology pipeline against what that rung promised.

    `expect` is a JSON object of {table: rows} (used by the build stage); `sheets` is a comma-separated
    list of sheet names (used by the plan stage). Returns PASS/FAIL plus every check that ran.
    """
    import json as _json

    from features.ontology import stage_checks as sc

    try:
        parsed_expect = _json.loads(expect) if str(expect or "").strip() else None
    except Exception as exc:                                    # noqa: BLE001
        return f"ERROR: `expect` must be JSON like {{\"orders\": 4}} — {type(exc).__name__}: {exc}"
    sheet_list = [s.strip() for s in str(sheets or "").split(",") if s.strip()]

    try:
        out = sc.run_stage(stage, ontology_key=ontology_key, db_name=db_name,
                           plan_path=plan_path, expect=parsed_expect, sheets=sheet_list)
    except sc.StageCheckError as exc:
        return f"REFUSED: {exc}"
    except Exception as exc:                                    # noqa: BLE001
        return f"ERROR: {type(exc).__name__}: {exc}"

    lines = [f"{out['verdict'].upper()}  stage={out['stage']}"
             + (f"  key={ontology_key}" if ontology_key else "")
             + (f"  db={db_name}" if db_name else "")]
    for c in out["checks"]:
        lines.append(f"  {'PASS' if c['ok'] else 'FAIL'}  {c['name']}"
                     + (f"  —— {c['detail']}" if c.get("detail") else ""))
    if out["failed"]:
        lines.append("")
        lines.append("下一步：不要往下走。把上面 FAIL 的名字带回给同一个专家重派，"
                     "或者把需要人决定的部分写进 needs_human。")
    return "\n".join(lines)
'''

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "stage": {"type": "string",
                  "enum": ["plan", "build", "structure", "metrics", "board", "publish"],
                  "description": "Which rung to verify (the rung you just delegated)."},
        "ontology_key": {"type": "string",
                         "description": "Registered key, e.g. store_monthly_v1 (needed by "
                                        "structure / metrics / board / publish).", "default": ""},
        "db_name": {"type": "string",
                    "description": "Database the rung concerns (plan: must NOT exist yet; build: must "
                                   "exist with the promised rows).", "default": ""},
        "plan_path": {"type": "string",
                      "description": "Path to the plan file the `tables` expert produced "
                                     "(plan stage).", "default": ""},
        "expect": {"type": "string",
                   "description": "JSON object {table: rows} the build stage must match exactly.",
                   "default": ""},
        "sheets": {"type": "string",
                   "description": "Comma-separated sheet names the plan must name (plan stage).",
                   "default": ""},
    },
    "required": ["stage"],
}

ARGS_SCHEMA = {
    "stage": {"type": "string", "description": "plan | build | structure | metrics | board | publish"},
    "ontology_key": {"type": "string", "description": "Registered key.", "default": ""},
    "db_name": {"type": "string", "description": "Database name.", "default": ""},
    "plan_path": {"type": "string", "description": "Plan file path (plan stage).", "default": ""},
    "expect": {"type": "string", "description": "JSON {table: rows} (build stage).", "default": ""},
    "sheets": {"type": "string", "description": "Comma-separated sheets (plan stage).", "default": ""},
}

DEFINITION = {
    "category": "ontology",
    "order": 0,
    "section": None,
    "is_concurrency_safe": True,
    "output_schema": None,
    "guard": {"approval": False, "confirmation": False},
    "presentation": {},
}

INSERT_SQL = text(
    """
    INSERT INTO custom_tools
        (tool_id, name, description, tool_type, template_type, category, is_builtin,
         is_public, output_format, definition, input_schema, implementation_config,
         requires_api_key, tags, version, usage_count, error_count,
         is_template_based, is_advanced_mode, created_at, updated_at)
    VALUES
        (:tool_id, :name, :description, 'python_function', 'custom', 'ontology', true,
         false, 'string', CAST(:definition AS json), CAST(:input_schema AS json),
         CAST(:impl AS json), false, CAST(:tags AS json), '1.0.0', 0, 0,
         true, true, now(), now())
    ON CONFLICT (tool_id) DO UPDATE SET
        name = EXCLUDED.name,
        description = EXCLUDED.description,
        definition = EXCLUDED.definition,
        input_schema = EXCLUDED.input_schema,
        implementation_config = EXCLUDED.implementation_config,
        category = EXCLUDED.category,
        is_builtin = true,
        updated_at = now()
    """
)


def main() -> int:
    db = SessionLocal()
    try:
        db.execute(INSERT_SQL, {
            "tool_id": TOOL_ID,
            "name": "Ontology Verify Stage (mechanical acceptance)",
            "description": DESCRIPTION,
            "definition": json.dumps(DEFINITION),
            "input_schema": json.dumps(INPUT_SCHEMA, ensure_ascii=False),
            "impl": json.dumps({
                "function_name": "ontology_verify_stage",
                "code": CODE,
                "args_schema": ARGS_SCHEMA,
            }, ensure_ascii=False),
            "tags": json.dumps(["ontology", "verify", "gate", "acceptance"]),
        })
        db.commit()
        row = db.execute(text(
            "SELECT tool_id, name, category, is_builtin, "
            "length(implementation_config->>'code') AS code_len "
            "FROM custom_tools WHERE tool_id = :t"), {"t": TOOL_ID}).fetchone()
        print("row:", row)
        print("next: bind it to the builder agent (native_tools) and restart")
        return 0 if row else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

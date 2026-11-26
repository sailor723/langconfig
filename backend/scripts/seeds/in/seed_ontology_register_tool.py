"""Seed the `ontology_register` BUILTIN tool row (is_builtin = true).

Why a builtin: registering an ontology writes into the REPOSITORY — a profile directory, `gates.json`, the
Settings document and the version registry. An untrusted (UI-created) tool is deliberately denied that, so
the write path has to be a platform row, like `ontology_publish`.

What it does: `services.ontology_register.register()` — the customer's NAME in, `<name>_v<N>` out, with the
profile skeleton, `_brief.md`, the gate declaration (marked `pending_install`) and the Settings row. It is
the rung the four-rung flow was missing: without it, every uploaded spreadsheet needed a person at a shell
running `add_ontology_builder.py --no-agent`.

What it deliberately does NOT do: build the database (`db_build_from_file` does that), write declarations
(the builder ladder does that), or install anything (`ontology_publish` only stages).

Idempotent: re-running updates the row in place.

    cd backend && .venv/bin/python scripts/seeds/in/seed_ontology_register_tool.py
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

TOOL_ID = "ontology_register"

DESCRIPTION = (
    "Register a NEW ontology key — the customer gives a NAME, the platform assigns the version "
    "(`<name>_v<N>`, never reused) and writes the four artefacts registration means: the profile "
    "directory with a skeleton `*_settings.json`, a `_brief.md` recording the facts you were given, a "
    "`gates.json` declaration marked pending_install, and the Settings → Ontology row. Use it once the "
    "database exists (db_build_from_file) and before writing any declaration. It refuses a name that is "
    "not an ASCII slug, a database that does not answer, and a key that already has a build; a retry "
    "before the first build returns the SAME key instead of minting v2. It never builds a database and "
    "never publishes."
)

CODE = r'''# --- imports ---
import json as _json


def ontology_register(name: str, datasource: str, theme: str = "", kind: str = "customer",
                      note: str = "", dsn_json: str = "") -> str:
    """Register a new ontology key and report what was written."""
    from services import ontology_register as _reg

    dsn = None
    if dsn_json.strip():
        try:
            dsn = _json.loads(dsn_json)
        except Exception as exc:                                # noqa: BLE001
            return f"REFUSED: dsn_json is not JSON ({type(exc).__name__}: {exc})"
        if not isinstance(dsn, dict) or not dsn.get("host"):
            return "REFUSED: dsn_json must be an object like {\"host\": ..., \"port\": ..., \"user\": ..., \"password\": ...}"

    try:
        out = _reg.register(name, datasource, theme=theme, kind=kind, note=note, dsn=dsn)
    except _reg.RegisterError as exc:
        return f"REFUSED: {exc}"
    except Exception as exc:                                    # noqa: BLE001
        return f"ERROR: {type(exc).__name__}: {exc}"

    lines = []
    if out.get("in_progress"):
        lines.append(f"{out['key']} is ALREADY registered and not built yet — continue it, do not open a "
                     f"new version.")
    else:
        lines.append(f"registered {out['key']}  (kind={out.get('kind')}, database={out.get('datasource')})")
    for path in out.get("wrote") or []:
        lines.append(f"  wrote {path}")
    if out.get("settings"):
        lines.append(f"  Settings → Ontology: {out['settings']}")
    lines.append("")
    lines.append(out.get("next") or "")
    return "\n".join(lines)
'''

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": "The customer's short name, ASCII lowercase letters/digits/underscore "
                           "(e.g. 'sunhing'). The platform appends the version.",
        },
        "datasource": {
            "type": "string",
            "description": "The database this ontology is built from — the name db_build_from_file created.",
        },
        "theme": {
            "type": "string",
            "description": "Human label for Settings → Ontology (e.g. '音乐零售').",
            "default": "",
        },
        "kind": {
            "type": "string",
            "description": "Why this key exists: customer | demo | trial | tutorial.",
            "default": "customer",
        },
        "note": {
            "type": "string",
            "description": "One line for the record (who asked, what for).",
            "default": "",
        },
        "dsn_json": {
            "type": "string",
            "description": "Only when this ontology's database is NOT the platform's own: a JSON object "
                           "{host, port, user, password} in profile style, e.g. "
                           "{\"host\": \"${TPCH_DB_HOST:-127.0.0.1}\", \"port\": \"${TPCH_DB_PORT:-5432}\", "
                           "\"user\": \"${TPCH_DB_USER}\", \"password\": \"${TPCH_DB_PASSWORD}\"}. "
                           "dbname comes from `datasource`. Empty = the platform's ONTOLOGY_DB_*.",
            "default": "",
        },
    },
    "required": ["name", "datasource"],
}

ARGS_SCHEMA = {
    "name": {"type": "string",
             "description": "The customer's short name, ASCII (e.g. 'sunhing'); the version is the "
                            "platform's to assign."},
    "datasource": {"type": "string",
                   "description": "Database name this ontology is built from."},
    "theme": {"type": "string", "description": "Human label for Settings → Ontology.", "default": ""},
    "kind": {"type": "string", "description": "customer | demo | trial | tutorial.",
             "default": "customer"},
    "note": {"type": "string", "description": "One line for the record.", "default": ""},
}

DEFINITION = {
    "category": "ontology",
    "order": 0,
    "section": None,
    "is_concurrency_safe": False,
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
            "name": "Ontology Register (new key)",
            "description": DESCRIPTION,
            "definition": json.dumps(DEFINITION),
            "input_schema": json.dumps(INPUT_SCHEMA, ensure_ascii=False),
            "impl": json.dumps({
                "function_name": "ontology_register",
                "code": CODE,
                "args_schema": ARGS_SCHEMA,
            }, ensure_ascii=False),
            "tags": json.dumps(["ontology", "register", "version", "semantic-layer"]),
        })
        db.commit()
        row = db.execute(text(
            "SELECT tool_id, name, category, is_builtin, "
            "length(implementation_config->>'code') AS code_len "
            "FROM custom_tools WHERE tool_id = :t"), {"t": TOOL_ID}).fetchone()
        print("row:", row)
        print("next: give the builder agent this tool, then restart so the tool registry reloads")
        return 0 if row else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

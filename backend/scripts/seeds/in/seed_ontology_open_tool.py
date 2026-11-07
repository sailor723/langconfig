"""Seed the `ontology_open` BUILTIN tool row (is_builtin = true).

The editing half of the publish channel. `ontology_publish` can only stage what is already
in the agent's workspace, and an agent that edits an ontology has to READ the installed
declarations first. Agent workspaces are private trees and the ontology repo is not inside
them, so "read the repo" would either break the workspace boundary or be done with a shell
`cp` nobody can audit.

`ontology_open` is the one legal door: it copies `ontologies/<key>/` from the repo into the
agent's workspace and tells the agent what it got. Read-only on the repo side — the copy is
the thing that gets edited, and `ontology_publish` is the only way back in.

Idempotent: re-running updates the row in place.

    cd backend && .venv/bin/python scripts/seeds/in/seed_ontology_open_tool.py
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

TOOL_ID = "ontology_open"

CODE = r'''# --- imports ---
import json as _json
import pathlib as _pl
import shutil as _shutil
import time as _time

_TEXT_SUFFIXES = {
    ".ttl", ".json", ".py", ".md", ".html", ".htm", ".css", ".js", ".txt", ".csv",
    ".tsv", ".yml", ".yaml", ".sql", ".owl", ".jsonl",
}
_SKIP_DIRS = {".staging", ".backup", "__pycache__", ".git", ".pytest_cache", ".mypy_cache",
              "node_modules", ".venv"}
_SKIP_NAMES = {".gitignore"}
_MAX_FILE_BYTES = 4 * 1024 * 1024


def _workspace_root():
    from services.user_roots import current_root
    return _pl.Path(current_root())


def _copy_tree(src, dst):
    """Copy the ontology's text files (never staging/backup scratch). Returns (paths, skipped)."""
    written, skipped = [], []
    for path in sorted(src.rglob("*")):
        if not path.is_file():
            continue
        parts = path.relative_to(src).parts
        rel = "/".join(parts)
        if any(p in _SKIP_DIRS for p in parts) or path.name in _SKIP_NAMES:
            continue
        if path.suffix.lower() not in _TEXT_SUFFIXES:
            skipped.append(rel + " (not text)")
            continue
        if path.stat().st_size > _MAX_FILE_BYTES:
            skipped.append(rel + " (too large)")
            continue
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        _shutil.copy2(path, target)
        written.append(rel)
    return written, skipped


def _profile_summary(folder):
    """The bits an editor must know before touching a declaration."""
    candidates = sorted(folder.glob("*_settings.json")) or sorted(folder.glob("settings.json"))
    if not candidates:
        return None
    try:
        d = _json.loads(candidates[0].read_text(encoding="utf-8"))
    except Exception as exc:
        return {"profile": candidates[0].name, "error": "unreadable: %s" % exc}
    dsn = d.get("dsn") or {}
    guard = d.get("guard") or {}
    return {
        "profile": candidates[0].name,
        "title": d.get("title"),
        "ns": d.get("ns"),
        "ontology_dir": d.get("ontology_dir", "ontology"),
        "overlay": d.get("overlay"),
        "database": dsn.get("dbname") or dsn.get("database"),
        "guard": {k: guard.get(k) for k in
                  ("enabled", "max_rows", "statement_timeout_ms", "max_plan_rows",
                   "default_window_days") if k in guard},
        "big_tables": list((guard.get("big_tables") or {}) or []) or None,
        "features": d.get("features") or {},
        "samples": len(d.get("samples") or []),
        "aliases": len(d.get("aliases") or {}),
    }


def ontology_open(ontology_key: str, dest: str = "", overwrite: bool = False) -> str:
    """Open a published ontology for editing: copy it from the repo into your workspace.

    The installed ontology is the truth and it does not live in your workspace. This copies
    `ontologies/<key>/` (declarations, overlay, profile, tutorial, build reports) into
    `work/<key>/` so you can READ it and edit the COPY. The repo itself is never written:
    `ontology_publish` is the only way back, and it stages rather than installs.

    Ask, then edit, then publish — never the other way round. Editing a copy whose profile or
    declarations you have not read is how a grain or a threshold gets invented.

    Arguments:
      ontology_key  the ontology's folder name under ontologies/, e.g. "logistics".
      dest          where to put it, relative to your workspace (default "work/<key>").
      overwrite     false (default) refuses a destination that already exists, so a re-open
                    cannot silently throw away edits you have not published. Pass true when
                    you mean to start again from the installed truth.

    Returns the copied file list plus the profile facts an editor needs first: namespace,
    ontology dir, overlay file, database name, guard limits, features, sample/alias counts.
    """
    key = (ontology_key or "").strip()
    if not key or "/" in key or key.startswith("."):
        return "ERROR: ontology_key must be a folder name under ontologies/, e.g. 'logistics'."

    try:
        from services import ontology_publish as _pub
    except Exception as exc:
        return "ERROR: the ontology repo is not available in this install (%s)." % exc

    src = _pl.Path(_pub.ONTOLOGIES) / key
    if not src.is_dir():
        try:
            available = sorted(p.name for p in _pl.Path(_pub.ONTOLOGIES).iterdir()
                               if p.is_dir() and not p.name.startswith("."))
        except Exception:
            available = []
        return ("ERROR: no installed ontology %r. Available: %s"
                % (key, ", ".join(available) or "(none)"))

    try:
        root = _workspace_root()
    except Exception as exc:
        return "ERROR: could not resolve your workspace root (%s)" % exc

    target = _pl.Path(dest).expanduser() if dest else root / "work" / key
    if not target.is_absolute():
        target = root / target
    if key not in [p.name for p in target.parents] and key != target.name:
        return ("ERROR: dest must be a folder for %r (got %s). Use work/%s."
                % (key, target, key))

    if target.exists() and any(target.iterdir()):
        if not overwrite:
            stamp = _time.strftime("%Y%m%d-%H%M%S")
            return ("REFUSED: %s already exists and holds files. Your edits there are the ones "
                    "you have not published yet, so this does not overwrite them.\n"
                    "- keep working on it, or\n"
                    "- copy it aside yourself (`work/%s.edited-%s`) and pass overwrite=true to "
                    "start again from the installed truth." % (target, key, stamp))

    written, skipped = _copy_tree(src, target)
    profile = _profile_summary(target)
    lines = ["OPENED %s into %s (%d file(s)) - the repo itself was not touched."
             % (key, target, len(written))]
    lines.append("")
    lines.append("files: " + ", ".join(written))
    if skipped:
        lines.append("skipped: " + ", ".join(skipped))
    if profile:
        lines.append("")
        lines.append("profile: " + _json.dumps(profile, ensure_ascii=False))
        if profile.get("database"):
            lines.append("the profile's dsn names database %r - the verification scripts take "
                         "--profile and read this; never type the password anywhere."
                         % profile["database"])
    lines.append("")
    lines.append("Next: read the profile and the declaration file you mean to change "
                 "(%s), make the edit in %s, then call ontology_publish with "
                 "source_dir=%s. Do not edit the installed ontology, and do not publish "
                 "without reading the file you touched."
                 % (profile.get("overlay") if profile and profile.get("overlay")
                    else "the .ttl file", target, target))
    return "\n".join(lines)
'''

DESCRIPTION = (
    "Open a published ontology for editing: copies ontologies/<key>/ from the ontology repo into "
    "your workspace (work/<key>/ by default) and reports the profile facts an editor needs first "
    "(namespace, ontology dir, overlay file, database, guard limits, features, sample/alias "
    "counts). The repo is read-only here: you edit the COPY and hand it back with ontology_publish, "
    "which stages rather than installs. Refuses to overwrite a destination that already holds "
    "unpublished edits unless overwrite=true. Use this instead of shell-copying the repo, which "
    "breaks the workspace boundary and leaves no audit trail."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "ontology_key": {
            "type": "string",
            "description": "The ontology's folder name under ontologies/, e.g. 'logistics'.",
        },
        "dest": {
            "type": "string",
            "description": "Destination folder relative to your workspace (default work/<key>).",
            "default": "",
        },
        "overwrite": {
            "type": "boolean",
            "description": "Replace an existing copy (default false: refuse, so unpublished edits survive).",
            "default": False,
        },
    },
    "required": ["ontology_key"],
}

DEFINITION = {
    "category": "ontology",
    "order": 2,
    "section": None,
    "is_concurrency_safe": False,
    "output_schema": None,
    "guard": {"approval": False, "confirmation": False},
    "presentation": {},
}

ARGS_SCHEMA = {
    "ontology_key": {
        "type": "string",
        "description": "The ontology's folder name under ontologies/, e.g. 'logistics'.",
    },
    "dest": {
        "type": "string",
        "description": "Destination folder relative to your workspace (default work/<key>).",
        "default": "",
    },
    "overwrite": {
        "type": "boolean",
        "description": "Replace an existing copy (default false).",
        "default": False,
    },
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
            "name": "Ontology Open (edit a copy)",
            "description": DESCRIPTION,
            "definition": json.dumps(DEFINITION),
            "input_schema": json.dumps(INPUT_SCHEMA),
            "impl": json.dumps({
                "function_name": "ontology_open",
                "code": CODE,
                "args_schema": ARGS_SCHEMA,
            }),
            "tags": json.dumps(["ontology", "edit", "workspace", "semantic-layer"]),
        })
        db.commit()

        row = db.execute(text(
            "SELECT tool_id, name, category, is_builtin, "
            "length(implementation_config->>'code') AS code_len "
            "FROM custom_tools WHERE tool_id = :t"
        ), {"t": TOOL_ID}).fetchone()
        print("row:", row)
        return 0 if row else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

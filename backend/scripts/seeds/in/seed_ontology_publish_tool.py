"""Seed the `ontology_publish` BUILTIN tool row (is_builtin = true).

Why a builtin: the tool reads the ontology repo and runs the compile/gate suite as a
subprocess — that needs the backend's own `services.ontology_publish`, which an untrusted
(UI-created) python_function tool is deliberately denied. Builtin rows run with the full
namespace.

What it does — and deliberately does NOT do:

* **stage only.** It collects the ontology files an agent produced, hands them to
  `services.ontology_publish.stage()`, which copies them over the INSTALLED ontology inside a
  staging directory and runs the real gates there. The installed ontology, the workbench, and
  git are untouched.
* **never apply.** Installing a staged publish needs a human (`confirmed=true`) and the
  `ontology_editor` role. That asymmetry is the point: the agent does the work, the human
  decides that a number's meaning changes for everyone.

Before this tool existed an agent's artifacts reached the workbench by someone copying files
by hand — which meant no gates ran, and nothing recorded who changed a definition.

Idempotent: re-running updates the row in place.

    cd backend && .venv/bin/python scripts/seeds/in/seed_ontology_publish_tool.py
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

TOOL_ID = "ontology_publish"

CODE = r'''# --- imports ---
import json as _json
import pathlib as _pl

# What a publish may carry: declarations, the profile, the tutorial, the generated pages and
# scripts. Anything else (images, databases, .pyc) is named and skipped rather than silently
# dropped or force-encoded.
_TEXT_SUFFIXES = {
    ".ttl", ".json", ".py", ".md", ".html", ".htm", ".css", ".js", ".txt", ".csv",
    ".tsv", ".yml", ".yaml", ".sql", ".owl", ".jsonl",
}
# An agent's workspace also holds things that are NOT the ontology. Publishing those would
# install skill bundles and transcripts into an ontology folder, so they never travel.
_SKIP_DIRS = {".staging", ".backup", "__pycache__", ".git", ".pytest_cache", ".mypy_cache",
              "node_modules", ".venv", "skills", "conversation_history", "upload", "uploads"}
_SKIP_NAMES = {"AGENTS.md", "CLAUDE.md"}
_MAX_FILE_BYTES = 2 * 1024 * 1024


def _declaration_noise(parts, name):
    """True for paths that are scaffolding (an agent's workspace), never ontology content."""
    return any(part in _SKIP_DIRS for part in parts) or (len(parts) == 1 and name in _SKIP_NAMES)


def _matches(rel, wanted):
    """Does `rel` fall under one of the `include` entries (exact, inside a folder, or a glob)?"""
    for w in wanted:
        if rel == w or rel.startswith(w + "/"):
            return True
        try:
            if _pl.PurePosixPath(rel).match(w):
                return True
        except Exception:
            pass
    return False


def _collect_from_dir(source, include=""):
    """Read the ontology's text files into {rel_path: content}. Returns (files, skipped)."""
    root = _pl.Path(source).expanduser()
    if not root.is_dir():
        return None, [str(root) + " is not a directory"]

    wanted = [w.strip().strip("/") for w in (include or "").split(",") if w.strip()]

    files, skipped = {}, []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        parts = path.relative_to(root).parts
        rel = "/".join(parts)
        if _declaration_noise(parts, path.name):
            continue
        if wanted and not _matches(rel, wanted):
            skipped.append(rel + " (not named in include)")
            continue
        if path.suffix.lower() not in _TEXT_SUFFIXES:
            skipped.append(rel + " (not a declaration/profile/text type)")
            continue
        size = path.stat().st_size
        if size > _MAX_FILE_BYTES:
            skipped.append(rel + " (%d bytes is over the %d limit)" % (size, _MAX_FILE_BYTES))
            continue
        try:
            files[rel] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            skipped.append(rel + " (not UTF-8 text)")
    if wanted:
        for w in wanted:
            if not any(_matches(r, [w]) for r in files):
                skipped.append(w + " (named in include but found nothing)")
    return files, skipped


def _resolve_source(source):
    """Relative paths are taken from the workspace root, not from the server's cwd."""
    path = _pl.Path(source).expanduser()
    if path.is_absolute():
        return path
    try:
        from services.user_roots import current_root
        return _pl.Path(current_root()) / path
    except Exception:
        return path


def ontology_publish(ontology_key: str, source_dir: str = "", files_json: str = "",
                     include: str = "", note: str = "", profile_name: str = "") -> str:
    """Publish (stage) an ontology build or edit through the validated channel.

    Use me when the ontology files are written and the gates you can run locally are green -
    this hands them to the platform's publish channel, which re-runs the whole compile + gate
    suite against a STAGING copy of the installed ontology and records the result.

    I stage, I never install: the installed ontology, the running workbench and git are
    untouched. A human with the ontology_editor role confirms the apply (one click in
    Settings -> Ontology -> pending publishes), and only then does the workbench reload.

    Pass either or both of:

    source_dir
        a directory holding the ontology (01-structure.ttl, 02-meaning.ttl, metrics_ext.ttl,
        *_settings.json, tutorial.json, ...). A relative path is taken from your workspace
        root. Text files are collected, binaries are named and skipped, and an agent
        workspace's scaffolding (AGENTS.md, CLAUDE.md, skills/, conversation_history/) never
        travels.
    include
        optional comma-separated paths relative to source_dir that ARE the ontology, e.g.
        "ontology, metrics_ext.ttl, logistics_settings.json, tutorial.json". Use it when your
        workspace root also holds drafts and notes. Empty = every text file.
    files_json
        a JSON object {relative path: full file content}, for a small edit where you already
        have the new file text. These override files from source_dir.

    Read the returned report: new_refusals is the list of things this publish would BREAK (a
    metric that stops compiling, a gate that goes red) and a staged publish with any of them is
    refused. Carried refusals were already refused before you started - they are not yours.
    """
    try:
        from services import ontology_publish as _pub
    except Exception as exc:
        return ("ERROR: the publish channel is not available in this install (%s). "
                "The harness needs backend/services/ontology_publish.py." % exc)
    try:
        from services.user_roots import subject_user_id
        _uid = subject_user_id()
        actor = "agent:user%d" % _uid if _uid is not None else "agent"
    except Exception:
        actor = "agent"

    key = (ontology_key or "").strip()
    if not key:
        return "ERROR: ontology_key is required (the folder name under ontologies/, e.g. 'logistics')."

    files, skipped = {}, []
    if source_dir and source_dir.strip():
        resolved = _resolve_source(source_dir.strip())
        got, skipped = _collect_from_dir(resolved, include=include or "")
        if got is None:
            return ("ERROR: " + skipped[0] + ". Pass the directory that holds the ontology "
                    "files, or use files_json for a single-file edit.")
        files.update(got)

    if files_json and files_json.strip():
        try:
            extra = _json.loads(files_json)
        except Exception as exc:
            return "ERROR: files_json is not valid JSON (%s)" % exc
        if not isinstance(extra, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in extra.items()):
            return "ERROR: files_json must be a JSON object of {relative path: file content}"
        files.update(extra)

    if not files:
        return ("ERROR: nothing to publish. Pass source_dir (the folder with the TTL/profile) "
                "or files_json ({path: content}), or widen `include` - it named nothing that exists.")

    live_dir = _pl.Path(getattr(_pub, "ONTOLOGIES", "")) / key
    is_installed_copy = False
    if source_dir and source_dir.strip():
        try:
            is_installed_copy = _resolve_source(source_dir.strip()).resolve() == live_dir.resolve()
        except Exception:
            is_installed_copy = False

    res = _pub.stage(key, files, actor=actor, note=(note or "").strip() or "staged by an agent",
                     profile_name=(profile_name or "").strip() or None)

    lines = []
    staged_id = res.get("staged_id")
    if not res.get("ok"):
        lines.append("REFUSED at stage time for " + key + ": "
                     + str(res.get("error") or "see the report"))
    else:
        lines.append("STAGED " + key + " as " + str(staged_id) + " - installed ontology untouched.")
    report = res.get("report") or {}
    if report:
        comp = report.get("compile") or {}
        lines.append("")
        lines.append("compile: %d of %d metric(s) compiled, %d refused by name" % (
            int(comp.get("compiled") or 0), int(comp.get("metrics") or 0),
            len(comp.get("refused") or [])))
        for row in (comp.get("refused") or [])[:10]:
            lines.append("  REFUSED %s: %s" % (row.get("name"), row.get("why")))
        if comp.get("error"):
            lines.append("  compiler error: " + str(comp["error"]))
        if report.get("new_refusals"):
            lines.append("NEW refusals introduced by this publish (this is why it is refused): "
                         + ", ".join(report["new_refusals"]))
        if report.get("carried_refusals"):
            lines.append("carried refusals (already refused in the installed ontology): "
                         + ", ".join(report["carried_refusals"]))
        lines.append("gates: " + ("PASS" if report.get("gates_ok") else
                                  "FAIL - " + "; ".join(report.get("gates_fails") or [])))
        if report.get("gates_not_run"):
            lines.append("gates NOT RUN (named, not passed): " + ", ".join(report["gates_not_run"]))
        lines.append("")
        lines.append("files (%d): %s" % (len(report.get("files") or []),
                                         ", ".join(report.get("files") or [])))
        if skipped:
            lines.append("skipped %d: %s" % (len(skipped), ", ".join(skipped[:10])))

    lines.append("")
    if res.get("ok"):
        lines.append("Next step (a human, one click): Settings -> Ontology -> Pending publishes "
                     "-> apply " + str(staged_id) + ". That re-runs the gates on the installed "
                     "copy, commits with the gate summary, and reloads the workbench. Do NOT copy "
                     "files into the ontology repo yourself - that skips the gates.")
        if is_installed_copy:
            lines.append("Note: source_dir IS the installed ontology folder. Staging re-validates "
                         "the installed truth; there is nothing new to install unless it differs, "
                         "so an apply here would restore identical bytes.")
    else:
        lines.append("Nothing was installed. Fix what the report names and publish again - a "
                     "refusal is the ontology's contract, not a tool failure.")
    return "\n".join(lines)
'''

DESCRIPTION = (
    "Publish an ontology build or edit through the validated channel (stage only, never install). "
    "Pass source_dir (the folder holding 01-structure.ttl / 02-meaning.ttl / metrics_ext.ttl / "
    "*_settings.json / tutorial.json) plus `include` when that folder also holds drafts, and "
    "optionally files_json ({relative path: content}) for a small edit. The platform copies the "
    "files over a STAGING copy of the installed ontology and re-runs the whole suite there: every "
    "metric compiled or refused by name, every gate. A publish that introduces a new refusal or a "
    "failing gate is refused. The installed ontology, the running workbench and git are untouched: "
    "a human with the ontology_editor role confirms the apply, and only then does the workbench "
    "reload. Use this instead of copying files into the ontology repo by hand."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "ontology_key": {
            "type": "string",
            "description": "The ontology's folder name under ontologies/, e.g. 'logistics'.",
        },
        "source_dir": {
            "type": "string",
            "description": "Directory holding the ontology files to publish (relative paths resolve against your workspace root).",
            "default": "",
        },
        "include": {
            "type": "string",
            "description": "Comma-separated paths relative to source_dir that ARE the ontology (e.g. 'ontology, metrics_ext.ttl, logistics_settings.json, tutorial.json'); empty = every text file.",
            "default": "",
        },
        "files_json": {
            "type": "string",
            "description": "JSON object {relative path: full file content} for a small edit; overrides source_dir.",
            "default": "",
        },
        "note": {
            "type": "string",
            "description": "One line on what changed and why — this is the audit trail a reviewer reads.",
            "default": "",
        },
        "profile_name": {
            "type": "string",
            "description": "Profile file name if the ontology has more than one (*_settings.json). Empty = the single one.",
            "default": "",
        },
    },
    "required": ["ontology_key"],
}

DEFINITION = {
    "category": "ontology",
    "order": 1,
    "section": None,
    "is_concurrency_safe": False,
    "output_schema": None,
    "guard": {"approval": False, "confirmation": False},
    "presentation": {},
}

# The builder prefers implementation_config.args_schema verbatim; the JSON-Schema translation
# it applies to input_schema drops `default`, which would make every argument required.
ARGS_SCHEMA = {
    "ontology_key": {
        "type": "string",
        "description": "The ontology's folder name under ontologies/, e.g. 'logistics'.",
    },
    "source_dir": {
        "type": "string",
        "description": "Directory holding the ontology files to publish.",
        "default": "",
    },
    "include": {
        "type": "string",
        "description": "Comma-separated paths relative to source_dir that ARE the ontology (empty = every text file).",
        "default": "",
    },
    "files_json": {
        "type": "string",
        "description": "JSON object {relative path: full file content} for a small edit.",
        "default": "",
    },
    "note": {
        "type": "string",
        "description": "One line on what changed and why.",
        "default": "",
    },
    "profile_name": {
        "type": "string",
        "description": "Profile file name if the ontology has more than one (*_settings.json).",
        "default": "",
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
            "name": "Ontology Publish (stage)",
            "description": DESCRIPTION,
            "definition": json.dumps(DEFINITION),
            "input_schema": json.dumps(INPUT_SCHEMA),
            "impl": json.dumps({
                "function_name": "ontology_publish",
                "code": CODE,
                "args_schema": ARGS_SCHEMA,
            }),
            "tags": json.dumps(["ontology", "publish", "gates", "semantic-layer"]),
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

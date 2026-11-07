"""Seed the `ontology_inspect` BUILTIN tool: ask the COMPILER about an ontology, don't read it.

The failure this exists to prevent, measured on the Ontology Editor's first real turn: asked to
add a must-refuse sample question, it read ~1,000 lines of `retail_graph/nl.py` to work out how
matching behaves, and then answered with a dump of source code. The information it actually needed
is three facts away — which metrics the compiler refuses and why, what one metric compiles to, what
number it returns, and what a question resolves to — and every one of them is cheap to produce
without the source.

So this tool is the reading replacement:

* `ontology_inspect("logistics")` — the metric list plus every refusal, BY NAME;
* `ontology_inspect("logistics", metric="tripCount")` — the declaration it compiles from, the
  compiled SQL, the number under the guardrails, the plan estimate and the guard's own notes; for
  a refused metric, the compiler's sentence;
* `ontology_inspect("logistics", question="高风险线路数")` — what the NL layer resolves it to, or
  the refusal, verbatim.

`source_dir` points it at a workspace COPY (`work/logistics`) instead of the installed ontology, so
"before vs after my edit" is two calls and one comparison rather than a re-read of the repo.

It is a thin wrapper around the real compiler (`sqlgen`), the real guardrails (`guard`) and the real
NL pipeline (`nl.ask`) — all in a child process under the profile's own venv, because that is the
venv with psycopg2 and rdflib. Nothing here re-implements a rule; if this tool and the workbench
disagree, this tool is wrong.

Idempotent: re-running updates the row in place.

    cd backend && .venv/bin/python scripts/seeds/in/seed_ontology_inspect_tool.py
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

TOOL_ID = "ontology_inspect"

CODE = r'''# --- imports ---
import json as _json
import os as _os
import pathlib as _pl
import subprocess as _sp
import sys as _sys

# The child runs the ontology repo's own compiler/guardrails/NL, under the venv that has
# psycopg2 + rdflib. Keep this script here (not in the repo) so the tool carries its own contract.
_CHILD = r"""
import json, os, pathlib, sys
REPO = pathlib.Path(os.environ["ONTOLOGY_REPO"])
sys.path.insert(0, str(REPO / "retail_graph"))
payload = json.loads(sys.argv[1])
import sqlgen, guard, nl, actions

g = sqlgen.load()
mode = payload.get("mode") or "list"
out = {"ok": True, "mode": mode}
names = sorted(sqlgen.metrics(g))
refused = []
for name in names:
    try:
        sqlgen.compile_metric(g, name)
    except Exception as exc:
        refused.append({"name": name, "why": str(exc).splitlines()[0]})
compiled = [n for n in names if n not in {r["name"] for r in refused}]
out["metrics"] = compiled
out["refused"] = refused

if mode == "metric":
    name = payload["name"]
    if name not in names:
        out["ok"] = False
        out["error"] = name + " is not a declared metric"
        out["near"] = [n for n in names if name.lower() in n.lower()][:10]
    else:
        try:
            c = sqlgen.compile_metric(g, name)
            out["sql"] = c.sql
            out["notes"] = c.notes
            import psycopg2
            conn = psycopg2.connect(**actions.DSN)
            conn.autocommit = True
            cfg = guard.config()
            # the PROFILE's limits, not the defaults: a tool that reports a 1000-row page cap while
            # the profile says 500 would make every "the guard is on" claim wrong
            prof = json.loads(pathlib.Path(os.environ["APP_SETTINGS"]).read_text())
            if isinstance(prof.get("guard"), dict):
                cfg.update({k: v for k, v in prof["guard"].items() if v is not None})
            with conn.cursor() as cur:
                r = guard.run(cur, c.sql, cfg=cfg, mode="declared")
                rows = r.get("rows") or []
                out["value"] = str(rows[0][0]) if rows and rows[0] else None
                out["plan_rows"] = r.get("plan_rows")
                out["guard_notes"] = r.get("notes") or []
            conn.close()
        except Exception as exc:
            out["ok"] = False
            out["refused"] = str(exc).splitlines()[0]

if mode == "question":
    try:
        res = nl.ask(payload["question"], record=False)
        out["intent"] = res.get("intent")
        out["value"] = str((res.get("result") or {}).get("value"))
        out["answer"] = res.get("answer") or ""
    except Exception as exc:
        out["ok"] = False
        out["refused"] = str(exc)[:800]

print(json.dumps(out, ensure_ascii=False))
"""


def _profile(folder):
    folder = _pl.Path(folder)
    for pat in ("*_settings.json", "settings.json"):
        found = sorted(folder.glob(pat))
        if found:
            return found[0]
    return None


def _repo_root():
    from services import ontology_publish
    return _pl.Path(ontology_publish.REPO)


def _python():
    from services import ontology_publish
    return ontology_publish.PYTHON


def ontology_inspect(ontology_key: str, metric: str = "", question: str = "",
                     source_dir: str = "") -> str:
    """Ask the compiler about an ontology — instead of reading its source.

    Use me before you change a declaration and after, and instead of opening sqlgen.py / nl.py:
    the answers below are produced by running the real compiler, the real guardrails and the real
    NL pipeline against the profile.

    Arguments:
      ontology_key  the folder name under ontologies/, e.g. "logistics".
      metric        one metric: its compiled SQL, its value under the guardrails, the plan estimate
                    and the guard's notes — or the compiler's refusal sentence. Empty = list.
      question      a user question: what it resolves to and the number (or the refusal, verbatim).
      source_dir    inspect a COPY instead of the installed ontology (e.g. "work/logistics"),
                    so before/after is two calls. Relative paths resolve against your workspace.
    """
    key = (ontology_key or "").strip()
    if not key or "/" in key or key.startswith("."):
        return "ERROR: ontology_key must be a folder name under ontologies/, e.g. 'logistics'."

    repo = _repo_root()
    if source_dir and source_dir.strip():
        folder = _pl.Path(source_dir).expanduser()
        if not folder.is_absolute():
            try:
                from services.user_roots import current_root
                folder = _pl.Path(current_root()) / folder
            except Exception:
                pass
    else:
        folder = repo / "ontologies" / key
        if not folder.is_dir():
            try:
                available = sorted(p.name for p in (repo / "ontologies").iterdir()
                                   if p.is_dir() and not p.name.startswith("."))
            except Exception:
                available = []
            return ("ERROR: no installed ontology %r. Available: %s"
                    % (key, ", ".join(available) or "(none)"))

    profile = _profile(folder)
    if profile is None:
        return ("ERROR: no *_settings.json in %s — that folder is not an ontology profile"
                % folder)

    mode = "question" if question.strip() else ("metric" if metric.strip() else "list")
    payload = {"mode": mode}
    if mode == "metric":
        payload["name"] = metric.strip()
    if mode == "question":
        payload["question"] = question.strip()

    env = dict(_os.environ)
    env["APP_SETTINGS"] = str(profile)
    env["ONTOLOGY_REPO"] = str(repo)
    env["NL_ANSWER_LLM"] = "0"          # deterministic: rules + the compiler, no prose model
    try:
        p = _sp.run([_python(), "-c", _CHILD, _json.dumps(payload)],
                    capture_output=True, text=True, timeout=180,
                    cwd=str(repo / "retail_graph"), env=env)
    except Exception as exc:
        return "ERROR: could not run the compiler (%s: %s)" % (type(exc).__name__, exc)

    lines_out = (p.stdout or "").strip().splitlines()
    if not lines_out:
        tail = (p.stderr or "").strip().splitlines()
        return ("ERROR: the compiler printed nothing%s"
                % (": " + tail[-1] if tail else " (exit %s)" % p.returncode))
    try:
        data = _json.loads(lines_out[-1])
    except Exception:
        return "ERROR: the compiler's answer was not JSON: %s" % lines_out[-1][:400]

    head = "ontology %s  (%s)\nprofile: %s" % (key if not source_dir else key + " · copy",
                                               mode, profile)
    body = []
    if mode == "list":
        body.append("compiled (%d): %s" % (len(data.get("metrics") or []),
                                           ", ".join(data.get("metrics") or []) or "(none)"))
        refused = data.get("refused") or []
        body.append("")
        body.append("refused by name (%d):" % len(refused))
        for r in refused:
            body.append("  REFUSED %s: %s" % (r.get("name"), r.get("why")))
        body.append("")
        body.append("Ask for one metric (metric=...) or a question (question=...) next; that is "
                    "cheaper and more precise than reading the engine.")
    elif mode == "metric":
        if not data.get("ok"):
            body.append("REFUSED: %s" % data.get("refused") or data.get("error"))
            if data.get("near"):
                body.append("did you mean: %s" % ", ".join(data["near"]))
        else:
            body.append("compiled SQL:\n%s" % (data.get("sql") or "").strip())
            body.append("")
            body.append("value: %s   (plan_rows=%s)" % (data.get("value"), data.get("plan_rows")))
            for note in data.get("guard_notes") or []:
                body.append("  guard: %s" % note)
            if data.get("notes"):
                body.append("notes: %s" % " · ".join(str(n) for n in data["notes"]))
        rest = data.get("refused")
        if isinstance(rest, list) and rest:
            body.append("")
            body.append("refused by name (%d): %s" % (len(rest),
                                                      ", ".join(r["name"] for r in rest)))
    else:
        q = payload["question"]
        if data.get("ok"):
            intent = data.get("intent") or {}
            body.append("resolved: %s %s" % (intent.get("kind"), intent.get("name")))
            body.append("value: %s" % data.get("value"))
            if data.get("answer"):
                body.append("answer: %s" % data["answer"])
        else:
            body.append("REFUSED: %s" % (data.get("refused") or "see the compiler"))
        body.append("")
        body.append("A refusal names the declaration that is missing. Declare it; never type SQL "
                    "for it, and never widen a guard to get past it.")

    if source_dir:
        body.append("")
        body.append("(inspected the COPY at %s — the installed ontology is unchanged)" % folder)
    return head + "\n\n" + "\n".join(body)
'''

DESCRIPTION = (
    "Ask the compiler about an ontology instead of reading its source: list every metric and every "
    "refusal by name, or inspect ONE metric (the declaration it compiles from, the compiled SQL, the "
    "number under the guardrails, the plan estimate and the guard's notes — or the compiler's "
    "refusal sentence), or ask what a user question resolves to. Runs the real compiler, guardrails "
    "and NL pipeline under the profile's venv. Pass source_dir='work/<key>' to inspect a workspace "
    "copy, so before/after an edit is two calls. Use this instead of opening sqlgen.py / nl.py: the "
    "answer you need is three facts away, and reading the engine costs a context window."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "ontology_key": {
            "type": "string",
            "description": "The ontology's folder name under ontologies/, e.g. 'logistics'.",
        },
        "metric": {
            "type": "string",
            "description": "One metric to inspect (empty = list everything).",
            "default": "",
        },
        "question": {
            "type": "string",
            "description": "A user question to resolve (empty = ignore).",
            "default": "",
        },
        "source_dir": {
            "type": "string",
            "description": "Inspect this copy instead of the installed ontology (e.g. 'work/logistics').",
            "default": "",
        },
    },
    "required": ["ontology_key"],
}

DEFINITION = {
    "category": "ontology",
    "order": 3,
    "section": None,
    "is_concurrency_safe": True,
    "output_schema": None,
    "guard": {"approval": False, "confirmation": False},
    "presentation": {},
}

ARGS_SCHEMA = {
    "ontology_key": {
        "type": "string",
        "description": "The ontology's folder name under ontologies/, e.g. 'logistics'.",
    },
    "metric": {
        "type": "string",
        "description": "One metric to inspect (empty = list everything).",
        "default": "",
    },
    "question": {
        "type": "string",
        "description": "A user question to resolve (empty = ignore).",
        "default": "",
    },
    "source_dir": {
        "type": "string",
        "description": "Inspect this copy instead of the installed ontology.",
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
            "name": "Ontology Inspect (ask the compiler)",
            "description": DESCRIPTION,
            "definition": json.dumps(DEFINITION),
            "input_schema": json.dumps(INPUT_SCHEMA),
            "impl": json.dumps({
                "function_name": "ontology_inspect",
                "code": CODE,
                "args_schema": ARGS_SCHEMA,
            }),
            "tags": json.dumps(["ontology", "inspect", "metrics", "refusals"]),
        })
        db.commit()
        row = db.execute(text(
            "SELECT tool_id, name, category, is_builtin, "
            "length(implementation_config->>'code') AS code_len "
            "FROM custom_tools WHERE tool_id = :t"), {"t": TOOL_ID}).fetchone()
        print("row:", row)
        return 0 if row else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

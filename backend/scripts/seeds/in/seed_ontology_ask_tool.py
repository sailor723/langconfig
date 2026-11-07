"""Seed the `ontology_ask` BUILTIN tool: ask an ontology a question, through its own Query pipeline.

The query agent's whole job is this one call. `ontology_ask` runs the ontology's pipeline — the same one
its Query section (`<workbench>/query` → `POST /api/nl`) serves — and returns what it found:

  1 menu       built from that ontology's declarations
  2 interpret  rules first; a model only when the rules are unsure — never SQL
  3 validate   an off-menu name is REFUSED BY NAME
  4 execute    the ontology's compiler builds the SQL; the guardrails bound it
  5 answer     prose about a number the compiler produced (a polish is verified, else the template)

Three properties that make it safe for an agent to hold:

* **it never writes SQL** — the tool has no SQL path at all;
* **a refusal is a result, not an error** — it comes back as text naming what is missing, so the agent
  can report it instead of inventing a number (or a query);
* **a constraint the question states is carried** — "last 90 days" either becomes a slot that reaches the
  SQL or the call returns `needs_confirmation` with the understanding, and only `confirm=true` runs it.

Profiles are resolved from the ontology key (`ontologies/<key>/<key>_settings.json`, or
`retail_graph/<key>_settings.json` for the built-in datasets), so the database connection comes from the
profile rather than from the agent.

Idempotent: re-running updates the row in place.

    cd backend && .venv/bin/python scripts/seeds/in/seed_ontology_ask_tool.py
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

TOOL_ID = "ontology_ask"

CODE = r'''# --- imports ---
import json as _json
import os as _os
import pathlib as _pl
import subprocess as _sp

_CHILD = r"""
import json, os, pathlib, sys
REPO = pathlib.Path(os.environ["ONTOLOGY_REPO"])
sys.path.insert(0, str(REPO / "retail_graph"))
import nl

payload = json.loads(sys.argv[1])
try:
    out = nl.ask(payload["question"], confirm=bool(payload.get("confirm")), record=True)
    print(json.dumps({"ok": True, **{k: out.get(k) for k in
        ("intent", "result", "answer", "answer_source", "steps", "needs_confirmation",
         "understanding", "total_ms")}}, ensure_ascii=False, default=str))
except nl.NlRefusal as exc:
    print(json.dumps({"ok": False, "refused": str(exc),
                      "text": getattr(exc, "polished", None) or str(exc)}, ensure_ascii=False))
except Exception as exc:
    print(json.dumps({"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}, ensure_ascii=False))
"""


def _repo():
    from services import ontology_publish
    return _pl.Path(ontology_publish.REPO)


def _python():
    from services import ontology_publish
    return ontology_publish.PYTHON


def _profile_for(repo, key):
    """A key can be an ontology folder OR one of the built-in datasets in retail_graph/."""
    candidates = [repo / "ontologies" / key / (key + "_settings.json"),
                  repo / "ontologies" / key / "settings.json",
                  repo / "retail_graph" / (key + "_settings.json")]
    if key == "retail":
        candidates.append(repo / "retail_graph" / "settings.json")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _installed(repo):
    keys = set()
    try:
        keys |= {p.name for p in (repo / "ontologies").iterdir()
                 if p.is_dir() and not p.name.startswith(".")}
    except OSError:
        pass
    try:
        keys |= {p.name[:-len("_settings.json")] for p in (repo / "retail_graph").glob("*_settings.json")}
        if (repo / "retail_graph" / "settings.json").is_file():
            keys.add("retail")
    except OSError:
        pass
    return sorted(k for k in keys if k not in ("ontologies",))


def ontology_ask(question: str, ontology_key: str = "logistics", confirm: bool = False,
                 polish: bool = True) -> str:
    """Ask an ontology a business question and get the number, or the refusal BY NAME.

    Use me for EVERY question that needs a number from a database covered by an ontology. I run the
    ontology's own pipeline (the one its Query page serves): the words are matched to a declared
    metric/class/action (rules first, a model only when unsure), the ontology's compiler builds the SQL,
    the guardrails bound it, and the answer is written as prose about that number. I never type SQL and
    never compute.

    Arguments:
      question       the user's words, verbatim — do not clean them up first; the words are the evidence
      ontology_key   which ontology answers (default logistics); any key under ontologies/ works
      confirm        a question that states a period or a customer comes back as `needs_confirmation`
                     with the understanding; call again with confirm=true to run it
      polish         false = the deterministic template writes the prose (faster, no model)

    What you get back is one of three things, and all three are useful:
      * the number, the definition it came from and the compiled SQL (so it can be quoted);
      * a REFUSAL that names the declaration which is missing — report it; do not invent a number;
      * `needs_confirmation` with the understanding — show it to the user and ask before running.
    """
    text = (question or "").strip()
    if not text:
        return "ERROR: ask a question; an empty one has no answer."
    key = (ontology_key or "logistics").strip()
    repo = _repo()
    profile = _profile_for(repo, key)
    if profile is None:
        return ("ERROR: no ontology %r — available: %s"
                % (key, ", ".join(_installed(repo)) or "(none)"))

    env = dict(_os.environ)
    env["APP_SETTINGS"] = str(profile)
    env["ONTOLOGY_REPO"] = str(repo)
    env["NL_ANSWER_LLM"] = "1" if polish else "0"
    try:
        p = _sp.run([_python(), "-c", _CHILD, _json.dumps({"question": text, "confirm": bool(confirm)})],
                    capture_output=True, text=True, timeout=300,
                    cwd=str(repo / "retail_graph"), env=env)
    except Exception as exc:
        return "ERROR: the pipeline did not run (%s: %s)" % (type(exc).__name__, exc)

    lines = (p.stdout or "").strip().splitlines()
    if not lines:
        tail = (p.stderr or "").strip().splitlines()
        return ("ERROR: the pipeline printed nothing%s"
                % (": " + tail[-1] if tail else " (exit %s)" % p.returncode))
    try:
        data = _json.loads(lines[-1])
    except Exception:
        return "ERROR: the pipeline's answer was not JSON: %s" % lines[-1][:400]

    head = "ontology %s  ·  question: %s" % (key, text)
    if data.get("error"):
        return head + "\n\nERROR: " + str(data["error"])
    if not data.get("ok"):
        return (head + "\n\nREFUSED (this is the answer, not a failure — it names what is missing):\n  "
                + str(data.get("text") or data.get("refused")))

    intent = data.get("intent") or {}
    result = data.get("result") or {}
    body = []
    body.append("intent: %s %s%s" % (intent.get("kind"), intent.get("name"),
                                     (" slots=" + _json.dumps(intent.get("slots"), ensure_ascii=False))
                                     if intent.get("slots") else ""))
    if data.get("needs_confirmation"):
        understanding = (data.get("understanding") or {}).get("text")
        body.append("")
        body.append("NEEDS CONFIRMATION — the question states a constraint; this is how it was understood:")
        body.append("  " + (understanding or "(no echo)"))
        body.append("  Re-ask with confirm=true to run it.")
        return head + "\n\n" + "\n".join(body)
    rows = result.get("rows")
    if rows:
        body.append("rows (%d):" % len(rows))
        for row in rows[:20]:
            if isinstance(row, dict):
                body.append("  %s = %s" % (row.get("key"), row.get("value")))
            else:
                body.append("  " + " / ".join(str(c) for c in row))
        if len(rows) > 20:
            body.append("  … %d more" % (len(rows) - 20))
    else:
        body.append("value: %s" % result.get("value"))
    if result.get("sql"):
        body.append("")
        body.append("compiled SQL (from the declarations, not typed by anyone):")
        body.append("  " + str(result["sql"]).replace("\n", " ").strip())
    for note in result.get("notes") or []:
        body.append("guard: " + str(note))
    body.append("")
    body.append("answer (%s):" % data.get("answer_source"))
    body.append("  " + str(data.get("answer") or "").replace("\n", "\n  "))
    steps = data.get("steps") or []
    if steps:
        body.append("")
        body.append("trace: " + " · ".join("%s %sms" % (s.get("step"), s.get("ms")) for s in steps))
    return head + "\n\n" + "\n".join(body)
'''

DESCRIPTION = (
    "Ask an ontology a business question and get the number, or a refusal BY NAME. Runs the ontology's "
    "own Query pipeline (menu → rules-first intent → validate → compile → guardrails → verified prose): "
    "the words are matched to a declared metric/class/action, the ontology's compiler builds the SQL, and "
    "no SQL is ever typed by a model. Returns the value (or grouped rows), the definition it came from, "
    "the compiled SQL and the guard's notes; a question the ontology cannot answer comes back as a "
    "refusal naming the missing declaration; a question with a period/customer comes back as "
    "needs_confirmation with the understanding (re-ask with confirm=true). Use this for every numeric "
    "question instead of writing a query."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "question": {"type": "string", "description": "The user's words, verbatim."},
        "ontology_key": {"type": "string",
                         "description": "Which ontology answers (default logistics).",
                         "default": "logistics"},
        "confirm": {"type": "boolean",
                    "description": "Run a question that states a period/customer (after showing the understanding).",
                    "default": False},
        "polish": {"type": "boolean",
                   "description": "false = deterministic prose, no model (faster).",
                   "default": True},
    },
    "required": ["question"],
}

DEFINITION = {
    "category": "ontology",
    "order": 4,
    "section": None,
    "is_concurrency_safe": True,
    "output_schema": None,
    "guard": {"approval": False, "confirmation": False},
    "presentation": {},
}

ARGS_SCHEMA = {
    "question": {"type": "string", "description": "The user's words, verbatim."},
    "ontology_key": {"type": "string", "description": "Which ontology answers (default logistics).",
                     "default": "logistics"},
    "confirm": {"type": "boolean", "description": "Run a slot question after confirming it.",
                "default": False},
    "polish": {"type": "boolean", "description": "false = deterministic prose.", "default": True},
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
            "name": "Ontology Ask (business question → number or refusal)",
            "description": DESCRIPTION,
            "definition": json.dumps(DEFINITION),
            "input_schema": json.dumps(INPUT_SCHEMA),
            "impl": json.dumps({"function_name": "ontology_ask", "code": CODE,
                                "args_schema": ARGS_SCHEMA}),
            "tags": json.dumps(["ontology", "query", "natural-language", "answer"]),
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

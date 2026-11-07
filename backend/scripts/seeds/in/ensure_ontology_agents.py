"""Keep the ontology agents visible and correctly pointed — idempotently, without rewriting them.

Why this exists. Agent 349 ("Ontology Builder (logistics)") was created with `is_public = false`, and
`GET /api/deepagents/` defaults to `public_only=true` — so it existed, ran, published ontologies, and was
invisible in the UI. A row that works but cannot be found is indistinguishable from a missing row, and
the only thing that made it visible was a manual UPDATE.

So the invariants that a manual UPDATE fixed are stated here once:

* every ontology agent is **visible** (`is_public = true`) — they are shared project agents, not personal
  ones;
* each carries the skill it runs, and the **parameters** that skill declared (datasource, ontology_key,
  workbench) — `core/skills/params.py` is where those are resolved and validated;
* a builder is wired to its `datasource`, an editor is not (it edits whatever ontology it is pointed at).

It PRESERVES everything else: prompts, agent docs, the workbench contract, tools. This script is a
"make sure", not a "rebuild" — a rebuild would throw away the hard-won contract text in those rows.
Creating an agent from scratch is `seed_ontology_editor_agent.py`'s job.

    cd backend && .venv/bin/python scripts/seeds/in/ensure_ontology_agents.py
    cd backend && .venv/bin/python scripts/seeds/in/ensure_ontology_agents.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

for _p in Path(__file__).resolve().parents:
    if (_p / "_seedpaths.py").exists():
        sys.path.insert(0, str(_p))
        break
from _seedpaths import BACKEND, REPO  # noqa: E402,F401

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND.parent / ".env")

from db.database import SessionLocal  # noqa: E402
from sqlalchemy import text  # noqa: E402

# What each agent MUST be, minimal and non-negotiable. Everything not listed is left alone.
EXPECTED = {
    "Ontology Builder (TPC-H / clinic)": {
        "skills": ["build-ontology-from-db"],
        "skill_params": {"build-ontology-from-db": {"datasource": "clinic", "ontology_key": "clinic"}},
        "datasource": "clinic",
    },
    "Ontology Builder (logistics)": {
        # + generate-mock-dataset: this is the one builder whose database is SYNTHETIC, so it must be
        # able to (re)generate it and re-verify the story's claims before it declares anything.
        "skills": ["build-ontology-from-db", "generate-mock-dataset"],
        "skill_params": {"build-ontology-from-db": {"datasource": "logistics",
                                                   "ontology_key": "logistics"},
                         "generate-mock-dataset": {"dataset_name": "abc_coldchain",
                                                   "generator": "retail_graph/abc/gen_abc.py"}},
        "datasource": "logistics",
    },
    "logics_query": {
        "skills": ["answer-ontology-question"],
        "skill_params": {"answer-ontology-question": {"ontology_key": "logistics",
                                                     "workbench": "http://127.0.0.1:8098"}},
    },
    # The two skills as their own agents: one turns a story into a checked dataset, the other turns an
    # ontology into a checked board. Both invariants are the same as every other ontology agent — visible,
    # carrying the skill, carrying the skill's declared parameters.
    "Mock Data Agent": {
        # The dataset name is ASKED (skill step 0c), so the configuration carries a placeholder rather than a
        # name: a baked-in name is how a second brief lands in the first brief's database.
        "skills": ["generate-mock-dataset"],
        "skill_params": {"generate-mock-dataset": {
            "dataset_name": "(ask the user — propose one from the brief)",
            "generator": "generated/<confirmed>/gen.py",
        }},
        "datasource": "doc_demo",
        "native_tools_must_include": ["read_any_file"],
    },
    "Ontology Builder (new_coldchain)": {
        # One builder per ontology key. The key is baked into `skill_params`, so a new key means a new agent
        # — and this row is what makes that visible instead of a note in someone's shell history.
        # (This agent was born as "doc_demo"; renamed when the confirmed dataset name became new_coldchain.)
        "skills": ["build-ontology-from-db"],
        "skill_params": {"build-ontology-from-db": {"datasource": "new_coldchain",
                                                   "ontology_key": "new_coldchain"}},
        "datasource": "new_coldchain",
    },
    "Dashboard Agent": {
        "skills": ["build-ontology-dashboard"],
        "skill_params": {"build-ontology-dashboard": {"ontology_key": "logistics"}},
    },
    "Ontology Editor": {
        # + build-ontology-dashboard: the board is a declaration over the metrics this agent authors,
        # so authoring the metric and authoring the panel must not be two different skills' business.
        "skills": ["edit-ontology-metrics", "answer-ontology-question", "build-ontology-dashboard"],
        "skill_params": {"edit-ontology-metrics": {"ontology_key": "logistics"},
                         "answer-ontology-question": {"ontology_key": "logistics",
                                                      "workbench": "http://127.0.0.1:8098"},
                         "build-ontology-dashboard": {"ontology_key": "logistics"}},
    },
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report what would change, change nothing")
    args = ap.parse_args()

    db = SessionLocal()
    problems = 0
    try:
        for name, want in EXPECTED.items():
            row = db.execute(text("select id, config, is_public from deep_agent_templates "
                                  "where name = :n order by id desc limit 1"), {"n": name}).fetchone()
            if row is None:
                print(f"MISSING  {name!r} — create it (builder: the UI or a seed; editor: "
                      f"seed_ontology_editor_agent.py)")
                problems += 1
                continue
            agent_id, cfg, is_public = row
            cfg = cfg if isinstance(cfg, dict) else json.loads(cfg or "{}")
            changes: list[str] = []
            if not is_public:
                changes.append("is_public: false -> true (the list endpoint hides non-public rows)")
            for key in ("skills", "skill_params", "datasource"):
                if key in want and cfg.get(key) != want[key]:
                    changes.append(f"{key}: {json.dumps(cfg.get(key), ensure_ascii=False)} "
                                   f"-> {json.dumps(want[key], ensure_ascii=False)}")
                    cfg[key] = want[key]
            # A tool the agent cannot work without. `read_any_file` is the only way a PDF/DOCX/PPTX brief
            # becomes text, and an agent that cannot read its input invents one instead.
            missing_tools = [t for t in (want.get("native_tools_must_include") or [])
                             if t not in (cfg.get("native_tools") or [])]
            if missing_tools:
                changes.append(f"native_tools: add {missing_tools}")
                cfg["native_tools"] = list(cfg.get("native_tools") or []) + missing_tools
            if not changes:
                print(f"ok       #{agent_id} {name} — visible, skills and parameters in place")
                continue
            print(f"UPDATE   #{agent_id} {name}")
            for change in changes:
                print(f"           {change}")
            if not args.dry_run:
                db.execute(text("update deep_agent_templates set is_public = true, "
                                "config = CAST(:c AS json), updated_at = now() where id = :i"),
                           {"c": json.dumps(cfg), "i": agent_id})
        if not args.dry_run:
            db.commit()
        return 1 if problems else 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

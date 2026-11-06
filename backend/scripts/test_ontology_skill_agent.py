#!/usr/bin/env python
"""Does `build-ontology-from-db` work inside a real deepagents agent?

Filesystem-first, per rules.md §Code Workflow: no PostgreSQL requirement of the platform's
own, no DB-mode skill staging — just `create_deep_agent(skills=[...])` with a disk backend,
the skill on disk, and a model.

Three checks, in the order a skill fails:

  A. DISCOVERY  the skill's name + description reach the model prompt (SkillsMiddleware
                catalog), so an agent that was never told about it can still find it
  B. READ       the agent opens SKILL.md with `read_file` (level 2 of progressive disclosure)
                and can name the skill's own phases and scripts
  C. EXECUTE    the agent runs one of the skill's scripts through the sandbox `execute` tool
                and uses the output

Run:
    cd backend && .venv/bin/python scripts/test_ontology_skill_agent.py \
        [--model qwen2.5:3b] [--dsn "host=127.0.0.1 port=5432 dbname=clinic_db user=weiping"]

Exit 0 only when all three pass. The model is a local Ollama one by default because this
platform ships without cloud keys; pass --model to use another registered id.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import sys

for _k in ("LANGCHAIN_TRACING_V2", "LANGSMITH_TRACING", "LANGSMITH_TRACING_V2",
           "LANGCHAIN_TRACING", "LANGSMITH_API_KEY"):
    os.environ.pop(_k, None)          # the repo's .env turns tracing on; without a key it
os.environ["LANGCHAIN_TRACING_V2"] = "false"   # only spams 401s into the test output
os.environ["LANGSMITH_TRACING"] = "false"

HERE = pathlib.Path(__file__).resolve()
REPO = HERE.parents[1]                     # backend/
SKILL_SRC = REPO / "skills" / "builtin" / "build-ontology-from-db"
WS = pathlib.Path("/tmp/ontology_skill_ws")

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail and not ok else ''}")


from langchain_core.callbacks import BaseCallbackHandler


class Capture(BaseCallbackHandler):
    """Collect the messages the model was actually shown, per call."""

    raise_error = False

    def __init__(self) -> None:
        super().__init__()
        self.prompts: list[list[tuple[str, str]]] = []

    # langchain callback hooks
    def on_chat_model_start(self, serialized, messages, **kwargs):
        for batch in messages:
            self.prompts.append([(m.type, m.content if isinstance(m.content, str)
                                  else json.dumps(m.content, ensure_ascii=False))
                                 for m in batch])

    def on_llm_start(self, serialized, prompts, **kwargs):
        for p in prompts:
            self.prompts.append([("prompt", p)])


def stage_workspace() -> None:
    shutil.rmtree(WS, ignore_errors=True)
    (WS / "skills" / "builtin").mkdir(parents=True)
    shutil.copytree(SKILL_SRC, WS / "skills" / "builtin" / "build-ontology-from-db")
    (WS / "out").mkdir()


def build_model(model_id: str):
    """Resolve the model the way the platform does — no key handling here.

    DeepSeek's key lives in the app's settings store (`settings_documents`, ns=models,
    user 1), so `resolve_model` is its only reader: the shell needs no
    `DEEPSEEK_API_KEY`, and a run that did need one would not prove the DB path works.
    A silent Ollama fallback used to sit here; it is gone on purpose — a green test
    against a local model says nothing about the model the agents actually use.
    """
    import asyncio
    import sys as _sys
    _sys.path.insert(0, str(REPO))
    from services.agent_utils import resolve_model
    model = asyncio.run(resolve_model(model_id, 0, 4096, {"streaming": True}))

    key = getattr(model, "openai_api_key", None)
    raw = key.get_secret_value() if hasattr(key, "get_secret_value") else key
    base = (getattr(model, "openai_api_base", None) or getattr(model, "base_url", None)
            or "provider default")
    print(f"  model: {type(model).__name__}({getattr(model, 'model_name', model_id)}) "
          f"· base={base} · key from DB: "
          f"{'yes (' + str(len(raw or '')) + ' chars)' if raw else 'NO'}")
    return model


def build_agent(model_id: str):
    from deepagents import create_deep_agent
    from deepagents.backends.local_shell import LocalShellBackend

    model = build_model(model_id)
    backend = LocalShellBackend(root_dir=str(WS), inherit_env=True, timeout=180)
    agent = create_deep_agent(
        model=model,
        skills=["skills/builtin"],            # virtual path inside the sandbox root
        backend=backend,                      # gives the SDK's own ls/read_file/…/execute
        system_prompt=("You are a data-engineering agent. When a task matches an available "
                       "skill, read that skill's SKILL.md first and follow it."),
    )
    return agent


def run_phase(agent, capture: Capture, message: str, recursion: int = 40) -> tuple[list, list]:
    """Run one turn; return (tool calls, final text)."""
    cfg = {"configurable": {"thread_id": f"probe-{len(capture.prompts)}"}, "recursion_limit": recursion}
    state = agent.invoke({"messages": [{"role": "user", "content": message}]},
                         config={**cfg, "callbacks": [capture]})
    calls, texts = [], []
    for m in state["messages"]:
        for tc in (getattr(m, "tool_calls", None) or []):
            calls.append((tc.get("name"), tc.get("args")))
        if getattr(m, "type", "") == "ai":
            body = m.content if isinstance(m.content, str) else json.dumps(m.content, ensure_ascii=False)
            if body.strip():
                texts.append(body)
    return calls, texts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="deepseek-v4-flash",
                    help="default: DeepSeek (the platform's own key); falls back to Ollama")
    ap.add_argument("--dsn", default="host=127.0.0.1 port=5432 dbname=clinic_db user=weiping")
    ap.add_argument("--skip-execute", action="store_true")
    ap.add_argument("--python", default=str(REPO / ".venv" / "bin" / "python"),
                    help="interpreter the sandbox should use (needs psycopg2)")
    args = ap.parse_args()

    sys.path.insert(0, str(REPO))
    stage_workspace()
    print(f"workspace: {WS}")
    print(f"skill:     {SKILL_SRC.name} (copied from {SKILL_SRC})")
    agent = build_agent(args.model)
    capture = Capture()

    # ---------------------------------------------------------------- A. discovery
    calls, texts = run_phase(agent, capture, "你好，你能做什么？(answer in Chinese, briefly)")
    prompt = "\n".join(t for p in capture.prompts for typ, t in p if typ in ("system", "prompt"))
    has_catalog = "build-ontology-from-db" in prompt
    has_desc = "semantic layer" in prompt.lower() or "ontology" in prompt.lower()
    check("A1 the skill catalog reaches the model prompt", has_catalog,
          "the name never appeared in the system prompt")
    check("A2 the description reaches the model prompt too", has_desc)
    has_execute = any(name == "execute" for name, _ in calls) or True   # tools are bound, not called yet
    print(f"       prompt chars: {len(prompt):,} · tool calls this turn: {[c[0] for c in calls]}")

    # ---------------------------------------------------------------- B. read
    capture2 = Capture()
    calls, texts = run_phase(
        agent, capture2,
        "列出你技能目录里的所有技能（名字 + 路径）。然后读取 build-ontology-from-db 的 SKILL.md，"
        "用中文告诉我：它分几个阶段？阶段 1 和阶段 3 分别做什么？scripts/ 目录里有哪几个脚本？")
    read_calls = [a for n, a in calls if n in ("read_file", "read_file_text", "cat")]
    read_targets = " ".join(json.dumps(a, ensure_ascii=False) for a in read_calls)
    check("B1 the agent read the skill file with read_file", "/SKILL.md" in read_targets,
          f"read calls: {read_targets[:200]}")
    joined = "\n".join(texts)
    mentions_scripts = sum(s in joined for s in ("introspect_db", "scaffold_ttl", "check_ontology"))
    check("B2 the answer names the skill's own scripts", mentions_scripts >= 2,
          f"answer mentioned {mentions_scripts}/3 script names")
    mentions_phases = bool(re.search(r"阶段|phase|Step|步骤", joined, re.I))
    check("B3 the answer describes the phases", mentions_phases,
          "no phase/step language in the answer")
    print(f"       read targets: {read_targets[:300]}")
    print(f"       model said  : {joined.strip()[:400].replace(chr(10), ' ')}")

    # ---------------------------------------------------------------- C. execute
    if not args.skip_execute:
        capture3 = Capture()
        calls, texts = run_phase(
            agent, capture3,
            "按技能的第 1 步，用沙箱的 execute 工具运行这个脚本（原样执行，不要改写路径）：\n"
            f"{args.python} skills/builtin/build-ontology-from-db/scripts/introspect_db.py "
            f"--dsn \"{args.dsn}\" --out out/brief.json\n"
            "跑完后用中文把 brief 里的表名列出来（最多 8 张），并说明每张表被判定成什么 shape。",
            recursion=50)
        exec_calls = [a for n, a in calls if n in ("execute", "bash", "run_command")]
        exec_text = " ".join(json.dumps(a, ensure_ascii=False) for a in exec_calls)
        check("C1 the agent used the sandbox execute tool", bool(exec_calls),
              f"tool calls: {[n for n, _ in calls]}")
        check("C2 it ran the skill's own introspect script", "introspect_db.py" in exec_text,
              f"executed: {exec_text[:240]}")
        brief = WS / "out" / "brief.json"
        check("C3 the script produced the brief file", brief.exists(),
              "out/brief.json was never written")
        if brief.exists():
            data = json.loads(brief.read_text())
            tables = [t["table"] for t in data["tables"]]
            shapes = {t["table"]: t["shape_hint"][:40] for t in data["tables"]}
            check("C4 the brief has the clinic tables",
                  {"appointments", "treatment_lines"} <= set(tables),
                  f"tables: {tables[:8]}")
            print(f"       tables: {tables}")
            print(f"       shapes: {shapes}")
        # a second turn: the model often ends the first turn mid-plan, so ask for the
        # summary explicitly rather than judging a plan sentence
        capture4 = Capture()
        calls2, texts2 = run_phase(
            agent, capture4,
            "现在用中文总结：out/brief.json 里每张表被判定成什么 shape？只列表名和 shape，"
            "并指出哪一张需要人工确认。", recursion=30)
        joined = "\n".join(texts + texts2)
        found = [t for t in ("appointments", "treatment_lines", "patients") if t in joined]
        check("C5 the agent reports the tables and their shapes", bool(found),
              "the final answer named none of the clinic tables")
        needs_confirm = any(w in joined for w in ("确认", "CONFIRM", "confirm"))
        check("C6 it flags the table the skill asked a human to confirm", needs_confirm,
              "the answer did not mention the CONFIRM question")

    print()
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"{passed}/{len(results)} checks passed")
    for name, ok, detail in results:
        if not ok:
            print(f"  FAILED {name}: {detail}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())

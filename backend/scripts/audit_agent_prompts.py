#!/usr/bin/env python
"""Audit every stored deep-agent prompt for the defects that make an agent quietly wrong.

Why this exists: agent 379's `system_prompt` read fine and was wrong in one way only a reader would
catch — its dsn example was two dsn examples glued at an edit (`…password": "${MEETING_V1_DB_PASSWORD}"}",
"port": "${ONTOLOGY_DB_PORT:-5432}", … "user": "${ONTOLOGY_DB_USER:-weiping}", "password": ""}`).
It named two ports, two users, ended with a literal empty password, and was not valid JSON. Nothing
errors: the agent simply writes a `meeting_v1_settings.json` that cannot connect, and the first
symptom is a dashboard that returns "数据库连不上".

Two severities, because they are not the same kind of fact:

  FAIL  the agent will act wrongly — a malformed dsn example, a dsn whose defaults disagree with
        the profile already installed, a literal password in a declaration example.
  NOTE  worth knowing, not a defect — a stored body with no machine tail (the chat path strips and
        re-bakes `## Identity` + AGENTS.md on every turn; the tail in the row only feeds the
        agent-detail view), or a key the prompt names in prose rather than in backticks.

    cd backend && .venv/bin/python scripts/audit_agent_prompts.py            # every agent
    cd backend && .venv/bin/python scripts/audit_agent_prompts.py --id 379   # one agent
    cd backend && .venv/bin/python scripts/audit_agent_prompts.py --strict   # FAIL → exit 1
    cd backend && .venv/bin/python scripts/audit_agent_prompts.py --json

Exit codes: 0 no FAILs, 1 FAILs found (with --strict), 2 bad arguments.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

PROFILES = BACKEND_ROOT / "features" / "ontology" / "profiles"
LITERAL_PASSWORD = re.compile(r'"password"\s*:\s*"(?!\$\{)[^"]*"')


def find_dsn_spans(prompt: str) -> list[tuple[str, str]]:
    """[(block, remainder_of_that_line)] — the remainder is how a glued dsn shows itself.

    A dsn glued at an edit closes its object at the FIRST `}` and leaves `", "port": …` behind, so
    brace counting alone calls the first half a valid object. The evidence is the text after it on
    the same line, which no honest dsn example has.
    """
    spans: list[tuple[str, str]] = []
    for block, end in _dsn_blocks_with_end(prompt):
        tail = prompt[end:]
        stop = min([i for i in (tail.find("\n"), tail.find("`")) if i != -1], default=len(tail))
        spans.append((block, tail[:stop]))
    return spans


def find_dsn_blocks(prompt: str) -> list[str]:
    """Every `"dsn": {…}` literal, with `${VAR:-default}` treated as opaque.

    A regex ending at the first `}` is wrong here, and wrong in a way that looks right: every dsn
    this platform writes contains `${ONTOLOGY_DB_HOST:-127.0.0.1}`, so the first `}` belongs to the
    variable, not to the object. Brace counting with `${…}` skipped is the only parse that survives.
    """
    return [block for block, _end in _dsn_blocks_with_end(prompt)]


def _dsn_blocks_with_end(prompt: str) -> list[tuple[str, int]]:
    blocks: list[tuple[str, int]] = []
    for match in re.finditer(r'"dsn"\s*:\s*', prompt):
        i = match.end()
        if i >= len(prompt) or prompt[i] != "{":
            continue
        start, depth, j = i, 0, i
        while j < len(prompt):
            char = prompt[j]
            if char == "$" and prompt.startswith("${", j):
                close = prompt.find("}", j)
                j = (close + 1) if close != -1 else j + 2
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        blocks.append((prompt[start:j + 1], j + 1))
    return blocks


def _dsn_default(value: str) -> str:
    """`${ONTOLOGY_DB_PORT:-5432}` → `5432`; a plain value stays as it is."""
    return value.split(":-")[-1].rstrip("}") if ":-" in value else value


def _profile_settings(key: str) -> dict | None:
    if not key:
        return None
    for name in (f"{key}_settings.json", "settings.json"):
        path = PROFILES / key / name
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:                                # noqa: BLE001
                return None
    return None


def _doc_problems(docs: dict) -> list[str]:
    """The instruction DOCUMENTS must not carry a machine tail.

    Measured across this instance: 39 of 67 agents have `agent_docs["AGENTS.md"]` saved with a
    baked prompt inside it — `## Identity`, the workspace-boundary block, and then a nested
    `## AGENTS.md (embedded)` copy of itself. Every turn therefore injects ~4 KB of instructions
    about which agent it is and which tree it may touch, twice, from a document whose job was to
    add three lines of theme guidance. A stale copy would name the WRONG workspace, and nothing in
    the platform refuses that: the doc is just text.
    """
    out = []
    for name, text in (docs or {}).items():
        body = text if isinstance(text, str) else str(text or "")
        if "## Identity" in body or "## Hard rule — workspace boundary" in body:
            out.append(f"agent_docs[{name}] 里烤进了机器尾巴（## Identity / workspace boundary）："
                       "文档描述的是「这个 agent 的额外规矩」，身份与边界由 prompt 尾巴负责；"
                       "重复一遍会每轮多注入 4 KB，且可能指向过期的 workspace —— 从 ## Identity 起截掉")
    return out


def audit(config: dict, docs: dict | None = None) -> tuple[list[str], list[str]]:
    """(fails, notes) for one agent's stored config (and its instruction documents)."""
    fails: list[str] = _doc_problems(docs or {})
    notes: list[str] = []
    prompt = config.get("system_prompt") or ""
    if not prompt:
        return ["config 里没有 system_prompt"], notes

    params = (config.get("skill_params") or {}).get("build-ontology-from-db") or {}
    key = (params.get("ontology_key") or "").strip()
    datasource = (config.get("datasource") or "").strip()

    if "## Identity" not in prompt:
        notes.append("存的 body 没有机器尾巴（chat 每轮会重烤 ## Identity + AGENTS.md；"
                     "这只影响 agent 详情页看到的 prompt，不影响运行）")
    elif prompt.count("## Identity") > 1:
        fails.append(f"prompt 里机器尾巴出现了 {prompt.count('## Identity')} 次（只该有一次）"
                     "：重烤一次就好——scripts/set_agent_prompt.py 会先剥再烤")

    spans = find_dsn_spans(prompt)
    blocks = [block for block, _tail in spans]
    if len(blocks) > 1:
        fails.append(f"prompt 里有 {len(blocks)} 个 dsn 例子，只该有一个：{blocks}")
    for block, tail in spans:
        if re.search(r'"(port|host|user|dbname|password)"\s*:', tail):
            fails.append("dsn 例子是两条粘在一起（对象在第一半就闭合了，后面还跟着 "
                         + tail.strip()[:80] + " ），照抄会得到坏掉的 JSON：" + block)
            continue
        if block.count('"port"') > 1 or block.count('"host"') > 1:
            fails.append("dsn 例子是两条粘在一起（host/port 重复），照抄会得到坏掉的 JSON：" + block)
        try:
            parsed = json.loads('{"dsn": ' + block + "}")["dsn"]
        except Exception as exc:                             # noqa: BLE001
            fails.append(f"dsn 例子不是合法 JSON（{exc}）：{block}")
            continue
        if LITERAL_PASSWORD.search(block) and not re.search(r'"password"\s*:\s*"\s*"', block):
            # An empty literal is this deployment's real value (local dev has no password);
            # a NON-empty literal is the defect — the declaration must carry ${VAR}, not a secret.
            fails.append("dsn 例子里有字面量口令（门禁 X2 拒；只能是 ${VAR}）：" + block)
        settings = _profile_settings(key)
        if settings:
            for field in ("dbname", "port", "user"):
                # Both sides may be `${VAR:-default}` — compare the defaults, not the spelling,
                # or the check reports every correct agent as broken (it did, on 4 of them).
                said = _dsn_default(str(parsed.get(field) or ""))
                installed = _dsn_default(str((settings.get("dsn") or {}).get(field) or ""))
                if said and installed and said != installed:
                    fails.append(f"dsn 的 {field}：prompt 说 {said}，已装 profile 是 {installed} "
                                 "（agent 会照 prompt 写一份连不上的 dsn）")

    if key and f"`{key}`" not in prompt:
        notes.append(f"skill_params 的 ontology_key={key} 没在 prompt 里以 {key} 出现（可能是散文写法）")
    if datasource and f"`{datasource}`" not in prompt:
        notes.append(f"datasource={datasource} 没在 prompt 里以 {datasource} 出现")
    return fails, notes


def strip_doc_tail(text: str) -> str:
    """The document without any baked machine tail — the text its author wrote."""
    body = text if isinstance(text, str) else str(text or "")
    for marker in ("## Identity", "## Hard rule — workspace boundary"):
        idx = body.find(marker)
        if idx != -1:
            body = body[:idx]
    return body.rstrip() + "\n"


def fix_agent(agent, db) -> list[str]:
    """Strip tails from agent_docs and re-bake the prompt once. Returns what changed."""
    changed: list[str] = []
    from core.agents.identity import build_identity_system_prompt

    docs = dict(agent.agent_docs or {})
    cleaned = {name: strip_doc_tail(text) for name, text in docs.items()}
    for name in docs:
        if cleaned[name] != docs[name]:
            changed.append(f"agent_docs[{name}]: {len(docs[name])} → {len(cleaned[name])} 字符（截掉尾巴）")

    config = dict(agent.config or {})
    prompt = config.get("system_prompt") or ""
    if prompt:
        from core.agents.identity import _strip_identity_block
        body = _strip_identity_block(prompt)
        if body != prompt:
            body = strip_doc_tail(body) if "## Identity" in body else body
        workspace = _resolve_workspace(db, agent)
        rebuilt = build_identity_system_prompt(body, agent.id, workspace, cleaned)
        if rebuilt != prompt:
            config["system_prompt"] = rebuilt
            agent.config = config
            changed.append(f"system_prompt: {len(prompt)} → {len(rebuilt)} 字符（重烤一次）")

    if cleaned != docs:
        agent.agent_docs = cleaned
    if changed:
        db.commit()
    return changed


def _resolve_workspace(db, agent) -> str:
    from services.workspace_manager import get_workspace_manager, WorkspaceManager

    mgr = get_workspace_manager()
    project_id = getattr(agent, "project_id", None)
    return str(mgr.resolve_agent_workspace(
        agent, project_id,
        vault_key=WorkspaceManager.project_vault_key(db, project_id) or None,
        agent_key=WorkspaceManager.agent_vault_key(db, agent),
    ))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--id", type=int, action="append", dest="ids",
                        help="audit only this agent id (repeatable)")
    parser.add_argument("--strict", action="store_true", help="exit 1 when any FAIL is found")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--fix", action="store_true",
                        help="repair what is mechanical: strip tails from agent_docs, re-bake the "
                             "prompt once. Never touches a body's prose or a dsn example.")
    parser.add_argument("--notes", action="store_true", help="also print the notes")
    args = parser.parse_args()

    from db.database import SessionLocal
    from models.deep_agent import DeepAgentTemplate

    db = SessionLocal()
    try:
        query = db.query(DeepAgentTemplate).order_by(DeepAgentTemplate.id)
        if args.ids:
            query = query.filter(DeepAgentTemplate.id.in_(args.ids))
        report, failing, noting, report_fixes = [], 0, 0, []
        for agent in query.all():
            config = dict(agent.config or {})
            if not (config.get("system_prompt") or ""):
                continue
            fails, notes = audit(config, agent.agent_docs or {})
            if args.fix and fails:
                changed = fix_agent(agent, db)
                if changed:
                    config = dict(agent.config or {})
                    fails, notes = audit(config, agent.agent_docs or {})
                    report_fixes.append({"id": agent.id, "name": agent.name, "changed": changed})
            failing += 1 if fails else 0
            noting += 1 if notes else 0
            report.append({"id": agent.id, "name": agent.name,
                           "prompt_chars": len(config.get("system_prompt") or ""),
                           "fails": fails, "notes": notes})
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            for item in report:
                if not item["fails"] and not (args.notes and item["notes"]):
                    continue
                mark = "FAIL" if item["fails"] else "note"
                print(f"{mark} {item['id']:>4} {item['name']}  ({item['prompt_chars']} 字符)")
                for line in item["fails"]:
                    print(f"       - {line}")
                for line in (item["notes"] if args.notes else []):
                    print(f"       · {line}")
            print(f"\n{len(report)} 个 agent：{failing} 个 FAIL，{noting} 个只有 note"
                  + ("；用 --notes 看 note" if noting and not args.notes else ""))
        if args.fix:
            for item in report_fixes:
                print(f"FIXED {item['id']:>4} {item['name']}")
                for line in item["changed"]:
                    print(f"       + {line}")
            print(f"\n{len(report_fixes)} 个 agent 被修（只做机械动作：剥尾巴 + 重烤）")
        return 1 if (failing and args.strict) else 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

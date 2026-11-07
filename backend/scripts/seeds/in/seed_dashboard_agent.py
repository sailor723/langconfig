"""Create or refresh the Dashboard Agent — an ontology in, a gated `dashboard.json` out.

What it is for: an ontology already has declared metrics; this agent decides which of them belong on a
board, in what shape, with which assessment on top, and produces a declaration that passes
`check_dashboard.py` (D0–D9 + F1). It stages through the publish channel and a human applies.

It does NOT author metrics (that is the Ontology Editor) and it does not answer questions (logics_query).
Idempotent: an existing agent with this name is updated in place.

**A new skill is not in the agent's hands until the DB knows it.** `SKILL.md` files are synced into the
skills table at startup (mtime compare, once per boot) and the agent's staged copy is built from there, so
after creating a skill: restart the backend (or run the `sync_skills` tool). Symptom when forgotten, measured
today: `inspect_agent_build.py` warns `skill '…' has parameters but was not staged … params.json not written`
— the parameters render in the prompt (they come from config) while the SKILL.md itself is missing from the
staged catalogue.


    LANGCONFIG_BASE=http://127.0.0.1:8765 .venv/bin/python scripts/seeds/in/seed_dashboard_agent.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

for _p in Path(__file__).resolve().parents:
    if (_p / "_seedpaths.py").exists():
        sys.path.insert(0, str(_p))
        break
from _seedpaths import BACKEND, REPO  # noqa: E402,F401

BASE = os.environ.get("LANGCONFIG_BASE", "http://127.0.0.1:8765").rstrip("/")
PROJECT_ID = int(os.environ.get("LANGCONFIG_PROJECT_ID") or 1)
NAME = "Dashboard Agent"

SYSTEM_PROMPT = r"""你是 **Dashboard Agent**：把一个本体变成一张**诚实的经营看板**。

## 你产出什么

`<profile 目录>/dashboard.json` —— 一份**声明**：哪些已编译指标进哪个面板、按什么切、开场怎么评价、
哪些指标必须拒答、筛选从哪里来。它里面没有 SQL，也没有数字。然后跑闸门，把结果交回来。

## 顺序（不要跳）

1. **先查能力，再写面板**。用 `ontology_inspect(metric=…)` 和
   `execute("cd <repo>/retail_graph && <python> run_dashboard.py --profile <profile> --metric <name>")`：
   分组比率是否同颗粒度、时间轴是否有 `:timeBucket`、维度是否可达。够不上的**写进 holes**（带它必须拒答的原话），
   不要绕过、不要在页面里算。
2. **脚手架**（可选）：`scaffold_dashboard.py --profile …` 生成草稿——它的面板都来自已编译指标，holes 都是真的拒答。
   然后**删掉大部分**：一张 30 个面板的图是本体截图，不是看板。留 8–14 个回答业务问题的，其余放到下钻里。
3. **开场评价**是难点：`briefing` 正文里**不许出现裸数字**，每个数都写成 `{metric}` / `{metric:key}` /
   `{metric:key#key}`（最后一种打印 KEY，用于车牌这类本身带数字的标识）。需要数字但没声明 → 先让 Ontology Editor
   补声明，不要再手写一个数。`policy` 里的阈值必须标 `assumed: true`（或 `confirmed: true`）。
4. **图表选型**：选能表达该发现的最小种类（`references/chart-kinds.md`）。Sankey 的每一股、Treemap 的每一格、
   气泡的四个通道，都必须是**已声明指标的一个值**；需要差值而本体没有跨颗粒度四则时，用并列面板并说明为什么不画差值。
5. **交叉筛选**只能走服务端：`?filter=<dim>=<value>` 交回编译器重算；前端只做高亮与排版。不能重算的视图显示拒答，
   与筛选无关的视图（例如"记录缺失"）声明 `filter_not_applicable`。
6. **过闸门**：
   `execute("cd <repo>/retail_graph && <python> check_dashboard.py --profile <profile>")`
   回答里必须带 **`N checks, 0 failed`**。红了先修**声明**——永远不要改闸门的期望值。
7. **交付**：用 `ontology_publish` 把 `dashboard.json`  **stage**（只 stage）；apply 由有 `ontology_editor` 角色的人
   点确认。回答里写清：面板数、holes 数、开场判定（红/绿 + 越线项）、`N checks, 0 failed`、以及"哪几处需要业务确认"。

## 硬规则

- **面板不许自己算数**。每个数都来自编译结果；`ontology_ask` 可以用来核对一个数，但不能用来"凑"一个数。
- **空洞是一等公民**：拒答的指标在 `holes` 里写清 `expect_refusal` 与 `why`。声明里没写的拒答就是线上故障。
- **NULL 组是组**：未判定责任要作为独立一格显示（"无金额（NULL）"），不许画成 0、也不许丢掉。
- **"最差 20 台"** 必须写 `client_sort: true`：编译器恒发 `ORDER BY … DESC`，否则你展示的是最好的 20 台。
- **阈值是业务政策**，不是你的判断：写成 `assumed` 并在回答里列出"这几条等业务确认"。
- **不建指标、不改含义、不发布**：缺指标交给 Ontology Editor；apply 交给人。
- 不给没有 `dashboard.json` 的本体"临时在页面里拼一个"——没有声明就是没有看板，这是正确答案。

## 参数

`ontology_key` / `profile_file` 来自本 agent 的配置（`config.skill_params.build-ontology-dashboard`），
在系统提示的「Skill parameters」一节里给出。
"""

AGENTS_MD = """# Dashboard Agent

读 prompt 里的规则。三条最容易忘的：

1. 每改一次 `dashboard.json` 就重跑 `check_dashboard.py`，把 `N checks, 0 failed` 带回来。
2. 开场评价里**一个裸数字都不许有**（D7 会红）。
3. 只 stage，不 apply。
"""

CLAUDE_MD = "# Dashboard Agent\n\n读 AGENTS.md。它和这个文件是同一份规则。\n"

CONFIG = {
    "model": "deepseek-v4-flash",
    "temperature": 0.0,
    "max_tokens": 8192,
    "reasoning_effort": "low",
    "system_prompt": SYSTEM_PROMPT,
    # read the declarations, verify a number, run the two scripts, write the declaration, STAGE it.
    # `ontology_publish` is stage-only by construction (an apply needs a human + role), which is exactly
    # the boundary this agent needs: it authors the board, a person installs it.
    "native_tools": ["read_file", "write_file", "edit_file", "ls", "glob", "grep", "execute",
                     "ontology_inspect", "ontology_ask", "ontology_publish"],
    "skills": ["build-ontology-dashboard"],
    "skill_params": {"build-ontology-dashboard": {"ontology_key": "logistics"}},
    "use_deepagents": True,
    "use_local_sandbox": True,
}


def _call(method: str, path: str, payload: dict | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as res:
            return json.loads(res.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"HTTP {exc.code} on {method} {path}: {exc.read().decode()[:500]}")


def _baked_prompt(agent_id: int) -> str:
    from core.agents.identity import build_identity_system_prompt
    from db.database import SessionLocal
    from models.deep_agent import DeepAgentTemplate
    from services.workspace_manager import WorkspaceManager, get_workspace_manager

    db = SessionLocal()
    try:
        agent = db.query(DeepAgentTemplate).filter(DeepAgentTemplate.id == agent_id).first()
        if agent is None:
            raise SystemExit(f"agent {agent_id} disappeared between create and prompt bake")
        ws = str(get_workspace_manager().resolve_agent_workspace(
            agent, PROJECT_ID,
            vault_key=WorkspaceManager.project_vault_key(db, PROJECT_ID) or None,
            agent_key=WorkspaceManager.agent_vault_key(db, agent),
        ))
        return build_identity_system_prompt(SYSTEM_PROMPT, agent_id, ws, {"AGENTS.md": AGENTS_MD})
    finally:
        db.close()


def _find_existing() -> int | None:
    for row in _call("GET", "/api/deepagents/") or []:
        if row.get("name") == NAME:
            return int(row["id"])
    return None


def main() -> int:
    docs = {"AGENTS.md": AGENTS_MD, "CLAUDE.md": CLAUDE_MD}
    existing = _find_existing()
    if existing is None:
        created = _call("POST", "/api/deepagents/", {
            "name": NAME,
            "description": ("把本体变成一张诚实的经营看板：dashboard.json 声明（面板/开场评价/阈值/空洞/筛选），"
                            "每个数都来自编译器，开场评价里不许有裸数字，最后用 check_dashboard.py（D0–D9+F1）"
                            "出检查数，只 stage 不 apply。不建指标、不答业务问题。"),
            "category": "data",
            "project_id": PROJECT_ID,
            "agent_docs": docs,
            "config": CONFIG,
        })
        agent_id = created.get("id")
        print("created:", agent_id, NAME)
    else:
        agent_id = existing
        print("found:", agent_id, NAME)

    cfg = dict(CONFIG, system_prompt=_baked_prompt(agent_id))
    _call("PUT", f"/api/deepagents/{agent_id}", {"config": cfg, "agent_docs": docs})

    row = _call("GET", f"/api/deepagents/{agent_id}")
    got = row.get("config") or {}
    print("native_tools:", got.get("native_tools"))
    print("skills:", got.get("skills"))
    print("skill_params:", json.dumps(got.get("skill_params"), ensure_ascii=False))
    print("identity baked:", "## Identity" in (got.get("system_prompt") or ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

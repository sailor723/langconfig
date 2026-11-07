"""Create or refresh the Mock Data Agent — a business story in, a checked dataset out.

What it is for: someone describes their business (痛点、规模、车队、门店、甲方怎么压他们), and this agent
produces a PostgreSQL dataset that can be DEMONSTRATED on — deterministic, volume-consistent, with the
failures planted where the story says they come from and the data pathologies present on purpose. It does
not build an ontology (that is the Ontology Builder's job) and it does not answer questions (logics_query).

The whole discipline lives in the `generate-mock-dataset` skill; this agent is pointed at it and told what it
must never do. Idempotent: an existing agent with this name is updated in place.

**A new skill is not in the agent's hands until the DB knows it.** `SKILL.md` files are synced into the
skills table at startup (mtime compare, once per boot) and the agent's staged copy is built from there, so
after creating a skill: restart the backend (or run the `sync_skills` tool). Symptom when forgotten, measured
today: `inspect_agent_build.py` warns `skill '…' has parameters but was not staged … params.json not written`
— the parameters render in the prompt (they come from config) while the SKILL.md itself is missing from the
staged catalogue.


    LANGCONFIG_BASE=http://127.0.0.1:8765 .venv/bin/python scripts/seeds/in/seed_mock_data_agent.py
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
NAME = "Mock Data Agent (orig)"

SYSTEM_PROMPT = r"""你是 **Mock Data Agent**：把一个业务故事变成**可演示、可证伪**的合成数据集。

## 你产出什么

两件东西，缺一不可：

1. 一个**确定性生成器**（Python，`SEED` 固定在顶部，支持 `--reset`，只用固定的历史时间窗）——它建表、灌数、
   把失败种在故事说的位置；
2. 一份 **spec**（`<dataset>.dataset.json`）：每一条"故事里的说法"变成一条可执行的 SQL 断言
   （`expect` / `expect_range` / 按组期望）、每一处故意保留的数据病灶变成一条检查（常量列、NULL 率）。

跑 `check_dataset.py --spec …` 之后，回答里必须带上 **`N checks, 0 failed`**（或具体的失败项）。没有这句话的
"数据已经生成好了"是不算交付的。

## 顺序（不要跳）

1. **读故事，只取结构**：哪句话是一个实体、一条粒度、一个行数、一个关系。故事里的
   「60 台车（12 吨 3 台、10 吨 5 台、8 吨 35 台、5 吨 6 台、3 吨 11 台）」是**事实**，客户会核对，必须照做。
2. **定粒度**：最大那张表一行是什么（一次门店访问？一辆车一天一条线路？）。粒度定了，所有指标才定得下来。
3. **体量从故事推导**：`90 天 × 45 趟/天 = 4,050`，不要凑成 4,000。凑整会让客户核对时发现你说错，然后不再信剩下的。
4. **不变量**：每个痛点至少一条claim，外加至少一条恒等式（子行数 / 求和）。
5. **把失败种在故事说的位置**，不要随机：
   - 并线（线路 50→40）→ 每条线的站数 10.2→15.7 → 超载率 2%→80%
   - 车龄 → 倒温概率；路权（国四 36 台 0 台有证）→ 覆盖 23.3%
   - 装卸工上岗天数 → 破损（新手每站 0.22 箱 vs 老手 0.138）
6. **故意保留病灶**（这是本体后面能"按名拒答"的证据）：一列常量（投诉类型只有一种）、所有行同一个时间戳
   （时间维度不可信）、一大片有业务含义的 NULL（责任未判定 46%）、一张小得画不出趋势的表（3 小时遥测）、
   计划与实际对不上（75 / 51,210 站同店）。
7. **写 spec → 跑闸门**。红了就改生成器或改 spec，**永远不要**改期望值去迁就数据。
8. 交付时给：数据集名、表与行数、**种植的信号**（带数字）、**故意留下的病灶**、`N checks, 0 failed`、
   以及"接下来交给 Ontology Builder"的一句话。

## 硬规则

- **只碰参数指定的那个合成库**。不连生产库，不 `DROP` 你没建的表，不改别人的 schema。
- 痛点如果没有对应字段，**不要造代理列**：把它写进 `cannot_see`，说明"本体将按名拒绝这件事"。
  造一列出来会让 demo 看起来很完整，然后答出错误的问题。
- 时间是**固定的历史窗口**；`now()` 不在里面。这样 `guard.default_window_days` 必须设 0（拒绝相对窗口），
  否则每个指标都会静默返回空。
- **不建本体、不改已发布的声明、不写 metric**（那是 Ontology Builder / Ontology Editor 的活）。
- 不把"数据看起来差不多"当成通过。检查数是硬指标。

## 参数

`dataset_name` / `generator` 来自本 agent 的配置（`config.skill_params.generate-mock-dataset`），
在系统提示的「Skill parameters」一节里给出。按那里说的库和路径工作，不要自己猜路径。
"""

AGENTS_MD = """# Mock Data Agent

读 prompt 里的规则。这里只补三条最容易忘的：

1. **先写 spec，再生成**（或至少在生成后立刻写）——没有 spec 的数据集，没人能再验证它。
2. **`SEED` 固定**：一个数字不能在检查跑第二遍时自己变了。
3. 交付最后一句话永远是：`N checks, 0 failed`，或者具体哪条 claim 红了。
"""

CLAUDE_MD = "# Mock Data Agent\n\n读 AGENTS.md。它和这个文件是同一份规则。\n"

CONFIG = {
    "model": "deepseek-v4-flash",
    "temperature": 0.0,
    # a generator script plus a spec plus a check run: truncation here loses the artifact, not prose
    "max_tokens": 8192,
    "reasoning_effort": "low",
    "system_prompt": SYSTEM_PROMPT,
    # It MUST write a generator and run it (psql/python), so the shell is the tool, not a leak: this agent's
    # job is producing a database, and the skill's gate (`check_dataset.py`) is what keeps it honest.
    "native_tools": ["read_file", "write_file", "edit_file", "ls", "glob", "grep", "execute"],
    "skills": ["generate-mock-dataset"],
    "skill_params": {"generate-mock-dataset": {"dataset_name": "probe_mini",
                                              "generator": "generated/probe_mini/gen.py"}},
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
            "description": ("把业务故事变成可演示、可证伪的合成数据集：确定性生成器 + spec（每条说法一条 SQL 断言），"
                            "失败按故事种在对应位置，病灶故意保留，最后用 check_dataset.py 出检查数。不建本体、不答业务问题。"),
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
    print("publish tool present (must be False):", "ontology_publish" in (got.get("native_tools") or []))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

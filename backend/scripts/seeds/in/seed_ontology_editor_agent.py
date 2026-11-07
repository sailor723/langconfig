"""Seed (or refresh) the "Ontology Editor" DeepAgent — agent 350 as created in this install.

The agent row lives in PostgreSQL, so a fresh install has no trace of it unless this file
exists. It goes through the SAME API the UI uses (`POST /api/deepagents/`) rather than
inserting a row: creation is what bakes the identity block, resolves the workspace root and
materialises AGENTS.md, and a row written by hand skips all three.

What the agent is for: an ontology that already exists. "This number is wrong", "add a metric",
"the words are wrong", "the tutorial is thin" — find the declaration that owns the number, edit
that one file, prove the number against a second SQL route, hand it back through
`services.ontology_publish` (stage only; a human with `ontology_editor` applies).

Idempotent: an existing agent with this name is updated in place (config + docs), never duplicated.

    cd backend && .venv/bin/python scripts/seeds/in/seed_ontology_editor_agent.py
    # against another install
    LANGCONFIG_BASE=http://127.0.0.1:8765 .venv/bin/python scripts/seeds/in/seed_ontology_editor_agent.py
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
NAME = "Ontology Editor"
PROJECT_ID = int(os.environ.get("LANGCONFIG_PROJECT_ID") or 1)

SYSTEM_PROMPT = """你是 ontology editor：一个已经上线的 ontology 由你维护，不再由你从数据库里造。

有人会说"这个数字不对 / 加一个指标 / 换个口径 / 这个词不对 / 教程讲错了"。你的工作是找到拥有这个数字的那条声明、只改那一个文件、证明新数字、然后把它交给发布通道；不是写 SQL。

Answer in Chinese unless asked otherwise.

## 你的循环（顺序不能换）

1. `ontology_open(ontology_key=...)` 把已安装的 ontology 复制到工作区 `work/<key>/`。仓库不是你的，副本才是。
2. 先读：profile（`*_settings.json`）和你要改的那个文件。namespace、`ontology_dir`、`overlay`、`guard` 上限、`features` 决定什么能改。
3. 判断这次改动归哪个文件（见你的技能 `edit-ontology-metrics` 的表）：meaning → `ontology/02-meaning.ttl`；计算（aggregate/grain/universe/where/groupBy/numerator/denominator/scale）→ `metrics_ext.ttl`；命名/描述 → `ontology/01-structure.ttl`；词表/样本/上限 → profile；教学 → `tutorial.json`。
4. 只改那一个文件，最小改动。
5. 验证数字，不是验证文件：用技能里的 `scripts/check_metric.py` 编译并运行，再用你自己写的**另一条** SQL 路线做 `--independent` 对比。跑通不等于正确。
6. `ontology_publish(ontology_key=..., source_dir="work/<key>")` 交付。它在暂存副本上重跑整套编译+门禁；出现 **new refusal** 或门禁失败就拒收。读它的报告。
7. 汇报：staged id、数字、门禁结论、以及按名列出 **NOT RUN** 的项。"已暂存"不等于"已上线"——apply 是有 `ontology_editor` 角色的人的点击。

## 必须拒绝的请求（要说明理由，不要绕）

- "把这个数字改成 X" 而没有规则：数字是定义的输出。问清楚哪些行进范围、在什么 grain、用什么阈值。
- 让你**发明阈值或 grain**（什么是"高风险司机"、什么算"准时"）：问。构建时被拒的那些指标之所以被拒，正是因为业务没定；这个拒绝就是诚实答案。
- 让你**手写 SQL** 或用别的方式绕开编译器：编译器是 SQL 的唯一来源。
- 用**放宽 guard / features** 的方式让一个数字"能算出来"：该窄化问题，或如实报告拒绝。
- **直接改仓库里的已安装 ontology**：那会跳过所有门禁、也不留审计记录。发布通道是唯一入口。

## 边界

- 你的工作区是私有的。别的 `users/<id>/` 不属于你，不读、不写、不拷。
- 已安装的 ontology 在仓库里，你只能通过 `ontology_open` 拿副本、`ontology_publish` 交回去；不要用 shell 去 cp/cp -r 仓库。
- 数据库凭据来自 profile 的 `dsn`；不要打印、不要写进任何文件。
- 讲清楚"哪些数字是被真实验证过的、哪些是 NOT RUN"。宁可少说，不要假绿。
"""

AGENTS_MD = """# Ontology Editor

维护一个已经上线的 ontology：改口径、改计算、改命名、改教程，然后通过发布通道交付（stage only；apply 是人点的）。

## 你能用的两个本体工具

- `ontology_open(ontology_key="logistics")` — 把 `ontologies/<key>/` 复制到 `work/<key>/`；仓库只读，副本可改。
- `ontology_publish(ontology_key="logistics", source_dir="work/logistics")` — 在暂存副本上重跑编译+门禁，出现 new refusal 或门禁失败就拒收。**它不会安装。** apply 需要在 Settings → Ontology → Pending publishes 由人确认。

不要用 shell 直接改仓库里的 ontology：那跳过全部门禁，也不留审计记录。

## 工作区

- 副本：`work/<key>/`（`ontology/`、`metrics_ext.ttl`、`*_settings.json`、`tutorial.json`、`generated/`）
- 交付物：`generated/`（验证记录、对比表）
- 临时文件：`other/`
- 上传：`upload/`

## 技能

- `edit-ontology-metrics` — 编辑工序、文件归属表、必须拒绝的请求、验证脚本 `scripts/check_metric.py`。
- `build-ontology-from-db` — 只为了其中的 `references/rules.md`（15 条配置规则）、`pitfalls.md`、`gates.md`。规则只有一份，别另抄。

## 验证（真跑，不要声称）

```bash
PY=/Users/weiping/dev/Learn/cube/tutorial/.venv/bin/python
$PY scripts/check_metric.py --profile work/logistics/logistics_settings.json
$PY scripts/check_metric.py --profile work/logistics/logistics_settings.json --metric tripCount --sql
$PY scripts/check_metric.py --profile work/logistics/logistics_settings.json --metric totalRevenue \\
    --independent "select sum(revenue) from trips"
```

编译器与门禁在 `/Users/weiping/dev/Learn/ontology/retail_graph/`（`sqlgen.py`、`guard.py`）；技能脚本自己会找 `ONTOLOGY_REPO`，默认就是那个路径。

## 规矩

- 一次只改一个文件，只改必须改的那几行。
- 数字必须用第二条、独立写出来的 SQL 路线证明；做不到就说 NOT RUN。
- 被拒绝的指标保持被拒绝，除非业务给了定义——不要为了让门禁变绿而加声明。
- 汇报里写：staged id、编译统计、carried vs new refusals、门禁 PASS/FAIL/NOT RUN、"apply 由人确认"。
"""

CLAUDE_MD = "# Ontology Editor\n\n读 AGENTS.md。它和这个文件是同一份规则。\n"

CONFIG = {
    "model": "deepseek-v4-flash",
    "temperature": 0.0,
    # 4096 truncated this agent's first real answer mid-sentence (the report ended at
    # "1794010432-6e"): a verified edit produces a body, two verification blocks and a gate
    # report. The prompt asks it to be terse; the budget must still fit the honest version.
    "max_tokens": 8192,
    "reasoning_effort": "low",
    "system_prompt": SYSTEM_PROMPT,
    "native_tools": ["read_file", "write_file", "edit_file", "ls", "glob", "grep", "execute",
                     "ontology_open", "ontology_publish"],
    "skills": ["edit-ontology-metrics", "build-ontology-from-db"],
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
    """Base prompt + identity + workspace boundary, exactly as the create path writes it.

    The API's PUT replaces `system_prompt` verbatim, so a refresh without this step drops the
    identity block the create path baked in (measured: the stored prompt went from carrying
    "## Identity" and its workspace root to 1,538 characters of role text only). Chat re-bakes
    per turn, so the agent still knew who it was — but the stored row stopped matching what a
    create would have stored, which is how two copies of an agent drift apart.
    """
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
            "description": ("Edits an existing ontology — a metric's meaning, its computation, a label, "
                            "the samples or the tutorial — and hands the change back through the "
                            "publish channel (stage only; a human applies)."),
            "category": "data",
            "project_id": PROJECT_ID,
            "agent_docs": docs,
            "config": CONFIG,
        })
        print("created:", created.get("id"), created.get("name"))
        agent_id = created.get("id")
    else:
        print("found:", existing, NAME)
        agent_id = existing

    # Always refresh through PUT with the identity baked in, whether the row was just created
    # or already existed — one code path, so a create and a refresh cannot disagree.
    cfg = dict(CONFIG, system_prompt=_baked_prompt(agent_id))
    _call("PUT", f"/api/deepagents/{agent_id}", {"config": cfg, "agent_docs": docs})

    row = _call("GET", f"/api/deepagents/{agent_id}")
    cfg = row.get("config") or {}
    prompt = cfg.get("system_prompt") or ""
    print("native_tools:", cfg.get("native_tools"))
    print("skills:", cfg.get("skills"))
    print("model:", cfg.get("model"), "| max_tokens:", cfg.get("max_tokens"))
    print("identity baked:", "## Identity" in prompt, "| prompt chars:", len(prompt))
    return 0 if "## Identity" in prompt else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Talent API —— 让 JD/CV 的产物能被一个界面读到、改到、并当场校验。

为什么需要这层,而不是"用脚本改":
`work/talent/` 下面那批文件是整条招聘流水线的中间产物,而**它们今天只能靠脚本读写**。
要在界面里做"左边文档、右边对话"的编辑器,就必须有一层能读能写的接口。

写安全是这里最要紧的部分,因为手改会破坏的东西很具体:

    jd_links/<JD>.yaml 的 verbatim   门禁的逐字回查会红(原话对不上原文)
    txt_line                         行号失效,引用回查不到
    _source/<JD>.txt                 **整条链的锚点**,改它等于把所有引用作废
    origin: client → hr              客户原话被冒充

所以做法跟 `api/semantics/routes.py` 学(那里是同样的处境:SEMANTICS.md 会改掉
每一条 SQL 的答案):

* **路径由服务端拼**,调用方只给 (jd, 相对子路径);任何 `..`、绝对路径、符号链接都拒绝
* **只允许白名单目录内的文件可写**;`_source/` 与 `collection/` 一律只读
* **原子写**(tmp + os.replace),并保留一份 `.bak`
* **每次写入落一条审计**(谁、什么时候、哪个文件、改了多少字节)
* **保存后立刻跑校验**,把结果一起返回 —— 一个只写不验的编辑器,就是一台造假的机器

校验用真脚本,不在这里重算:
    scripts/talent/verify_jd_report.py   回检(行数/条数/逐字/行号/门禁汇总行)
    scripts/talent/check_component_catalog.py  全库门禁

路由:
    GET  /api/talent/docs?jd=X      列出该 JD 的全部产物(带可写标记)
    GET  /api/talent/doc?jd=X&path= 读一个文件(带 mtime,用于并发检测)
    PUT  /api/talent/doc            写一个文件(白名单 + 审计 + 返回校验结果)
    POST /api/talent/validate?jd=X  只校验,不写
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import quote
from typing import Any, Dict, Optional

import yaml

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/talent", tags=["talent"])

BACKEND = pathlib.Path(__file__).resolve().parents[2]
ROOT = BACKEND.parent
TALENT = ROOT / "work" / "talent"
AUDIT = TALENT / "_audit" / "edits.jsonl"

MAX_BYTES = 2 * 1024 * 1024

#: 可写的相对子路径前缀 → 为什么。不在表里的一律只读。
#: 这张表是**判据**,不是提示:写接口只认它。
WRITABLE = {
    "jd_links/": "引用文件:改完必须过逐字回查(门禁会抓 verbatim/行号)",
    "jd_docs/": "定稿/回填表:我方建议与排版可改",
    "requirement_library.yaml": "要求库:JD 无关的要求定义",
    "component_catalog.yaml": "能力词表:维度/属性/类别/组件",
    "cv_interview/": "访谈记录:一面落盘的结构化答案",
    "cv_docs/": "CV 定稿",
    # 人填的答案:客户没写的格子填什么。定稿是从这里**重新生成**的,不手改定稿。
    "jd_inputs/": "回填答案:客户没写的字段由谁填了什么(定稿据此重新生成)",
}

#: 明确只读的(即使用 WRITABLE 的父目录覆盖也要挡住)。
READONLY = {
    "jd_links/_source/": "客户原文锚点:改它等于把所有引用作废,只能重新抽取",
    "collection/": "采集清单是生成物,下次跑会被覆盖",
    "hr_facts.json": "由脚本从 CV 推导",
    "cv_facts.json": "由抽取脚本产出",
    "ontology_facts.json": "由推理机产出",
    "_audit/": "审计日志只追加,不许改",
}


# ── 路径解析:服务端拼,调用方给不了路径 ─────────────────────────

def _rel_allowed(rel: str) -> tuple[bool, str]:
    """这个相对路径可写吗?返回 (可写, 理由)。"""
    rel = rel.strip().lstrip("/")
    for bad, why in READONLY.items():
        if rel == bad or rel.startswith(bad):
            return False, why
    for pre, why in WRITABLE.items():
        if rel == pre or rel.startswith(pre):
            return True, why
    return False, "不在可写白名单里"


def _resolve(rel: str, *, must_exist: bool = True) -> pathlib.Path:
    """把相对路径安全地解析到 work/talent 下。

    任何越界都拒绝:绝对路径、`..`、以及解析后（跟随符号链接）不在 TALENT 内的。
    """
    rel = (rel or "").strip().lstrip("/")
    if not rel or rel.startswith("..") or pathlib.PurePosixPath(rel).is_absolute():
        raise HTTPException(400, f"invalid relative path {rel!r}")
    candidate = (TALENT / rel).resolve()
    try:
        candidate.relative_to(TALENT.resolve())
    except ValueError:
        raise HTTPException(400, f"path escapes work/talent: {rel!r}")
    if must_exist and not candidate.is_file():
        raise HTTPException(404, f"not found: work/talent/{rel}")
    return candidate


def _global_files() -> list[dict]:
    """**不属于任何一份 JD** 的全局文档（标准目录 / 总览）。

    浏览器是"单 JD 作用域"：选中哪份 JD，看到的就只是那份 JD 的产物。
    所以全局文档不混进 JD 产物链，单独一份清单、单独一组显示 ——
    否则"这份 JD 的产物里怎么有一份讲 22 个分类的目录"这种问题会一直出现。
    """
    out: list[dict] = []
    for rel, layer, note in (
        ("OVERVIEW.md", "总览 · 完整流水线", "五步全景：每步业务做什么、门禁卡什么"),
        ("CATALOG.md", "标准目录 · Phase 0", "分类 / 组件 / 要求 / 标准 JD 40 / CV 26 模板"),
        ("tutorial/TUTORIAL_v2.md", "教程 v2 · 从记录到判定",
         "跨 JD 的读本：十四步，每步一个真数字 + 一个能变红的反证"),
    ):
        p = TALENT / rel
        if not p.is_file():
            continue
        out.append({"path": rel, "layer": layer, "exists": True, "bytes": p.stat().st_size,
                    "mtime": p.stat().st_mtime, "writable": False, "readonly_reason": "只读",
                    "note": note, "scope": "global"})
    return out


#: 层序 = 业务顺序（第 1 步 → 第 5 步）。**按业务事实排，不按字符串**。
LAYER_ORDER = (
    "1 客户原文",
    "2 引用文件",
    "2 决策账本",
    "2 回填答案",
    "2 定稿 · 标准 40 格",
    "3 初筛 · 明细(机读)",
    "3 初筛 · 面试名单",
    "3 初筛 · 面试名单(机读)",
    "3 一面（必须）· 采集清单(机读)",
    "3 一面（必须）· 采集清单(人读)",
    "3 一面（必须）· 待核清单",
    "3 一面（必须）· 待核清单(机读)",
    "3 CV 补齐 · 清单",
    "4 加面（可选）· 记录",
    "5 目标名单 · 人读",
    "5 目标名单 · 机读",
    "5 选人 · 名单",
    "5 业务面 · 问题清单",
    "5 选人 · 机读",
    "5 判定总览",
    "5 冲突待裁",
)


def _jd_files(jd: str) -> list[dict]:
    """**某一份 JD** 的全部产物,按"哪一层"分组。全局文档不在这里（见 _global_files）。"""
    items: list[dict] = []

    def add(rel: str, layer: str, note: str = "") -> None:
        p = TALENT / rel
        exists = p.is_file()
        w, why = _rel_allowed(rel)
        items.append({
            "path": rel,
            "layer": layer,
            "scope": "jd",
            "exists": exists,
            "bytes": p.stat().st_size if exists else 0,
            "mtime": p.stat().st_mtime if exists else None,
            "writable": w,
            "readonly_reason": "" if w else why,
            "note": note,
        })

    # 虚拟产物：不是磁盘文件，path 前缀 `@` 让前端走面板而不是读文件。
    # 放在最前面，因为"这份 JD 还缺什么"是打开就最该看到的。
    if jd in _jds():
        items.append({
            "scope": "jd",
            "path": "@gap",
            "layer": "1 客户原文",
            "exists": True,
            "bytes": 0,
            "mtime": None,
            "writable": False,
            "readonly_reason": "面板：由 jd_draft 或 template_fill 现算，不落盘",
            "note": "原文 + 40 格缺口并排：能判几格 / 谁还缺什么（跟着上面选的 JD 走）",
        })
    add(f"jd_links/_source/{jd}.txt", "1 客户原文", "只读锚点")
    add(f"jd_links/{jd}.yaml", "2 引用文件", "改完要过逐字回查")
    # ── 第 2 步：HR 与业务把 JD 定下来（定稿 + 回填 + 决策账本都在这一步）──
    # 定稿只有一份：标准 40 格（所有 JD 同一版式）。旧 49 格版式已删除，不再并列。
    add(f"jd_docs/{jd}.定稿(标准40格).md", "2 定稿 · 标准 40 格",
        "所有 JD 同一版式；逐行标 客户原文 / 文本规则 / AI 模拟")
    add(f"jd_inputs/{jd}.yaml", "2 回填答案", "人填的格子 + 依据;改完重跑 render_jd_final")
    add(f"collection/{jd}.yaml", "3 一面（必须）· 采集清单(机读)", "HR 一面要问的项")
    add(f"collection/{jd}.采集清单.md", "3 一面（必须）· 采集清单(人读)", "按人列出的问法")
    # ── 第 3~6 步的产物。之前这里只列到"采集清单",于是初筛、面试名单、判定说明
    #    在面板上根本看不见 —— 跑完了也找不到东西,只能去翻目录。
    add(f"jd_reviews/{jd}.yaml", "2 决策账本", "谁定了什么、哪天定的（定稿依据）")
    add(f"shortlist/{jd}.yaml", "3 初筛 · 明细(机读)", "保留/排除/待核,排除必须带硬证据")
    add(f"shortlist/{jd}.面试名单.md", "3 初筛 · 面试名单", "按目标人数切,每人附待问项")
    add(f"shortlist/{jd}.面试名单.yaml", "3 初筛 · 面试名单(机读)", "含排序规则与业务优先条件")
    add(f"open_questions/{jd}.md", "3 一面（必须）· 待核清单", "按 HR/业务/客户分组,带可照读问法")
    add(f"open_questions/{jd}.yaml", "3 一面（必须）· 待核清单(机读)", "第 3 步一面的机器可读版")
    add(f"shortlist/{jd}.目标名单.md", "5 目标名单 · 人读", "面完之后留下的 N 人 + 每人证据明细")
    add(f"shortlist/{jd}.目标名单.yaml", "5 目标名单 · 机读", "九层证据阶梯排序 + 切线 + 放宽记账")
    # 第 5 步一次 run 出三样:目标名单(名单) → 选人(≤4) → 判定说明。
    # 文件名没变,标签按五步走 —— 不然侧栏看起来像还有第 6 步。
    add(f"picks/{jd} 选人.md", "5 选人 · 名单", "最终名单(≤5)+ 每人逐条理由")
    add(f"picks/{jd}.业务面问题.md", "5 业务面 · 问题清单",
        "给业务面这 5 个人用：能力举例 / 未知项落地 / 岗位必答")
    add(f"picks/{jd}.yaml", "5 选人 · 机读", "四态计数与数据来源")
    add(f"verdicts/{jd}/_index.md", "5 判定总览", "每人一句话结论 + 集体卡在哪")
    add(f"conflicts/{jd}.yaml", "5 冲突待裁", "本体与 LLM 判得不一样的格子,等人裁")

    # CV 定稿**不再一份一条**塞进侧栏 —— 30 份 CV 会把侧栏铺满,而且 CV 是第 4 步的
    # 产物,却排在第 5 步名单后面,顺序本身就是错的。现在只留一条清单:
    # 打开是短表(名次/年龄/学历/年限/证据/判定),表里点「看 CV」在弹层里读全文。
    add(f"cv_docs/{jd}.CV清单.md", "3 CV 补齐 · 清单", "一面补齐后的 CV 短表 + 每人一个「看 CV」入口")
    # 第 4 步 = **可选**的额外面试（业务面/加面）。跑过才有文件；没跑就不是"缺"。
    add(f"cv_interview/{jd}.加面.yaml", "4 加面（可选）· 记录", "不是必须：跳过时那几格记「未知」")

    # 层序：显式排列，**不按 add 的先后、也不按拼音**。
    # 之前是按 add 先后，于是「2 决策账本」跑到「4 采集清单」后面；改成拼音又变成
    # 决策账本/回填答案/定稿/引用文件 乱序 —— 流水线的先后是业务事实，不能由字符串比较决定。
    rank = {name: i for i, name in enumerate(LAYER_ORDER)}

    def _key(x: dict) -> tuple:
        layer = x["layer"]
        head = layer.split(" ", 1)[0]
        try:
            lead = float(head)
        except ValueError:
            lead = 99.0
        return (rank.get(layer, 10_000), lead, layer, x["path"])

    items.sort(key=_key)
    return items


def _jds() -> list[str]:
    """有哪些 JD —— 复用服务层定义（jd_links ∪ uploads），避免两处各写一份。"""
    from services.talent_gap import known_jds

    return known_jds()

def _run(cmd: list[str], timeout: int = 300) -> dict:
    env = dict(os.environ)
    env.pop("PGPORT", None)          # 项目 shell 会导出 5432,把脚本的默认端口劫持掉
    try:
        proc = subprocess.run(cmd, cwd=str(BACKEND), capture_output=True, text=True,
                              timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "lines": [f"超过 {timeout}s"], "exit": None}
    out = (proc.stdout or "") + (proc.stderr or "")
    return {
        "status": "pass" if proc.returncode == 0 else "fail",
        "exit": proc.returncode,
        "lines": [ln for ln in out.strip().splitlines() if ln.strip()][-14:],
    }


def _validate(jd: str) -> dict:
    """回检 + 全库门禁。两条都必须有汇总行,没有汇总行按未完成处理。"""
    verify = _run([sys.executable, "-m", "scripts.talent.verify_jd_report", "--jd", jd])
    gate = _run([sys.executable, "-m", "scripts.talent.check_component_catalog"])
    verify_ok = any(("[PASS]" in ln) or ("全部对得上" in ln) for ln in verify["lines"])
    gate_line = next((ln for ln in reversed(gate["lines"]) if "checks ·" in ln), "")
    gate_ok = bool(gate_line) and " 0 failed" in gate_line
    return {
        "jd": jd,
        "verify": {**verify, "ok": verify_ok},
        # 没有汇总行 = 门禁没跑完,不算过 —— 这条在这一轮里踩过一次
        "gate": {**gate, "summary": gate_line, "ok": gate_ok},
        "ok": bool(verify_ok and gate_ok),
    }


# ── 跑流程:只允许白名单里的固定命令,不接受任意 shell ──────────
#
# 为什么值得开这个口子:第 5 步是一串脚本(名单 → 选人 → 判定说明 → 门禁),
# 少跑一步就会让 verdicts 的指纹过期、门禁变红。让人在终端里记四条命令、
# 还要按顺序跑,是这套东西最容易被绕过的地方。
#
# 两条硬规矩:
#   ① **只能是白名单**:body 里的 step 映射到写死的 argv,拼字符串一律不做;
#   ② **同一步串行**:两个请求同时写同一份 yaml,Git 也救不回来。

# 锁必须是**跨进程**的:uvicorn 起的是多进程(main.py 里 workers>1),
# 进程内的 threading.Lock 各锁各的 —— 实测两个请求同时跑完了同一步。
_RUN_LOCK_FILE = TALENT / ".run-step.lock"


class _FileLock:
    """整台机器上同名步骤串行。用 fcntl.flock:拿不到就立刻失败,不排队。"""

    def __init__(self, path: pathlib.Path) -> None:
        self.path = path
        self.fh = None

    def acquire(self, blocking: bool = False) -> bool:
        import fcntl
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = self.path.open("a+")
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except OSError:
            fh.close()
            return False
        self.fh = fh
        return True

    def release(self) -> None:
        if not self.fh:
            return
        try:
            import fcntl
            fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
        finally:
            self.fh.close()
            self.fh = None


_RUN_LOCK = _FileLock(_RUN_LOCK_FILE)

STEPS: dict[str, list[str]] = {
    # 第 3 步 = HR 一面（**必须**）：初筛 → 面试名单 → 待核清单 → 一面补齐 → HR 评语 →
    # 判定说明 → 门禁。后两件不能省：一面数据一变，判定说明的指纹立刻过期，
    # 门禁必然红 —— 那是自己造的红，不该留给用户去猜。
    "3": [
        "scripts.talent.screen_cv",
        "scripts.talent.pick_interview_list",
        "scripts.talent.open_questions",
        "scripts.talent.simulate_hr_round",
        "scripts.talent.mock_hr_comment",
        "scripts.talent.render_all_cv",
        "scripts.talent.explain_all",
        "scripts.talent.check_component_catalog",
    ],
    # 第 4 步 = 加面（**可选**）。没跑不是缺；跑了就补 HR 评语与 CV 定稿。
    "4": [
        "scripts.talent.mock_hr_comment",
        "scripts.talent.render_all_cv",
        "scripts.talent.open_questions",
        # 一次电话改的是**共享**的一面数据（同一个人可能同时在两份名单里），
        # 所以要刷新所有 JD 的说明，不能只刷这一份。
        "scripts.talent.explain_all",
        "scripts.talent.check_component_catalog",
    ],
    # 第 5 步 = 挑出给业务面的 5 人：目标名单(≤10) → 最终(≤5) → 判定说明 →
    # CV 清单 → **业务面问题清单** → 门禁。
    "5": [
        "scripts.talent.shortlist_after_interview",
        "scripts.talent.pick_final",
        "scripts.talent.explain_rejection",
        "scripts.talent.index_cv",
        "scripts.talent.business_questions",
        "scripts.talent.check_component_catalog",
    ],
}

#: 每一步都按"顺序错了就白跑"排，一个失败就停（半套产物比没有更危险）。
#: 口径（用户 2026-11-24）：第 3 步 = HR 一面**必须**（补齐 CV + HR 评语）；
#: 第 4 步 = 加面（**可选**）；第 5 步 = 挑出给业务面的 5 人 + 出业务面问题清单。
_RUN_ARGS: dict[str, dict[str, list[str]]] = {
    # 第 3 步：初筛 → 面试名单 → 待核清单 → 一面（补齐 CV）→ HR 评语 → CV 清单
    "3": {
        "scripts.talent.screen_cv": ["--jd", "{jd}"],
        "scripts.talent.pick_interview_list": ["--jd", "{jd}"],
        "scripts.talent.open_questions": ["--jd", "{jd}"],
        "scripts.talent.simulate_hr_round": ["--jd", "{jd}", "--force", "--refresh"],
        "scripts.talent.mock_hr_comment": ["--jd", "{jd}"],
        "scripts.talent.render_all_cv": ["--jd", "{jd}"],
    },
    # 第 4 步：加面（可选）。没跑不是缺 —— 跳过的格子记「未知」。
    "4": {
        "scripts.talent.mock_hr_comment": ["--jd", "{jd}"],
        "scripts.talent.render_all_cv": ["--jd", "{jd}"],
    },
    # 第 5 步：目标名单(≤10) → 最终 ≤5 → 判定说明 → CV 清单 → **业务面问题清单**
    "5": {
        "scripts.talent.shortlist_after_interview": ["--jd", "{jd}"],
        "scripts.talent.pick_final": ["--jd", "{jd}"],
        "scripts.talent.explain_rejection": ["--jd", "{jd}", "--shortlist"],
        "scripts.talent.index_cv": ["--jd", "{jd}"],
        "scripts.talent.business_questions": ["--jd", "{jd}"],
    },
}


class RunStep(BaseModel):
    jd: str
    step: str = "5"


@router.post("/run")
def run_step(body: RunStep) -> Dict[str, Any]:
    """跑一步流程。返回每条脚本的状态行 —— **不当成"成功"** 除非最后一行是绿的。"""
    cmds = STEPS.get(body.step)
    if not cmds:
        raise HTTPException(400, f"不认识的步骤:{body.step}(可选:{', '.join(STEPS)})")
    if body.jd not in _jds():
        raise HTTPException(404, f"没有这份 JD:{body.jd}")
    if body.step in ("3", "5") and not (TALENT / "jd_draft" / f"{body.jd}.draft.json").is_file():
        raise HTTPException(409, f"先跑第 2 步定稿:缺 jd_draft/{body.jd}.draft.json"
                                 "（mock_fill_jd → draft_jd → render_jd_standard）")
    if not _RUN_LOCK.acquire(blocking=False):
        raise HTTPException(409, "上一步还在跑,等它跑完再点")
    t0 = time.time()
    report = []
    try:
        for mod in cmds:
            argv = [sys.executable, "-m", mod] + [a.replace("{jd}", body.jd)
                                                  for a in _RUN_ARGS.get(body.step, {}).get(mod, [])]
            r = _run(argv, timeout=900)
            report.append({"module": mod.split(".")[-1], **r})
            _audit({"at": time.time(), "who": _who(), "kind": "run-step",
                    "jd": body.jd, "step": body.step, "module": mod,
                    "status": r["status"]})
            if r["status"] != "pass":
                report.append({"module": "（后续步骤已跳过）", "status": "skip", "exit": None,
                               "lines": [f"{mod} 没通过,后面的不跑了 —— 半套产物比没有更危险"]})
                break
    finally:
        _RUN_LOCK.release()
    gate_line = ""
    for step in report:
        for ln in step.get("lines") or []:
            if "checks ·" in ln:
                gate_line = ln.strip()
    return {
        "jd": body.jd, "step": body.step,
        "seconds": round(time.time() - t0, 1),
        "ok": bool(gate_line) and " 0 failed" in gate_line,
        "gate": gate_line,
        "steps": report,
    }


# ── 审计:每次写入都要留下痕迹 ────────────────────────────────

def _audit(entry: dict) -> None:
    AUDIT.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _who() -> Optional[int]:
    try:
        from services.user_roots import subject_user_id

        return subject_user_id()
    except Exception:  # noqa: BLE001 —— 拿不到用户不该让读接口失败
        return None


# ── 路由 ────────────────────────────────────────────────────

class DocSave(BaseModel):
    jd: str
    path: str
    text: str
    #: 编辑器打开时的 mtime。给了就必须和磁盘一致,否则说明别人改过。
    expected_mtime: Optional[float] = None


@router.get("/docs")
def list_docs() -> Dict[str, Any]:
    """所有 JD 及其产物清单。

    `default_jd` 由 `jd_inputs/<JD>.yaml` 的 `default: true` 决定（换批次不用改代码）；
    前端拿它当"没选过时的默认"，不再自己猜第一份 —— 猜第一份等于把缺口最大的那份
    摆在人眼前。
    """
    jds = _jds()
    from services.talent_gap import default_jd as _default_jd

    return {
        "jds": [
            {"jd": jd, "files": _jd_files(jd),
             "existing": sum(1 for f in _jd_files(jd) if f["exists"])}
            for jd in jds
        ],
        "default_jd": _default_jd(),
        # 单 JD 作用域：浏览器只显示选中那份 JD 的产物；全局文档单独一组
        "globals": _global_files(),
        "writable_prefixes": WRITABLE,
        "readonly_prefixes": READONLY,
        "user": _who(),
    }


@router.get("/gap")
def get_gap(jd: str = Query(..., description="必填：缺口是相对某一份 JD 才成立的")) -> Dict[str, Any]:
    """某份 JD 的缺口（40 格状态）。

    `jd` **必填**：不传就报 422，而不是返回空表 —— 空表会被人读成"没有缺口"。
    有 `jd_draft/<JD>.draft.json` 就返回 7 状态（定稿还差什么），
    否则退回 `template_fill` 的 5 状态（客户稿覆盖到哪），并在 `source` 里标清楚。
    """
    from services.talent_gap import gap_for

    if not jd.strip():
        raise HTTPException(422, "jd 不能为空：缺口是相对某一份 JD 才成立的")
    try:
        return gap_for(jd.strip())
    except KeyError:
        raise HTTPException(404, f"没有这份 JD：{jd}")


@router.post("/jd/upload")
def upload_jd(file: UploadFile = File(...)) -> Dict[str, Any]:
    """上传一份 JD → 抽文本 → 写抽取件 → 算缺口 → 生成给业务/HR 看的缺口 md。

    这是 Phase 1 的入口：**只有 JD**，不涉及任何简历。
    返回里带 `md`（可编辑的缺口说明）与 `gap`（四状态小计），前端据此打开编辑器。
    """
    from services.talent_jd_ingest import JdIngestError, ingest

    data = file.file.read()
    if not data:
        raise HTTPException(422, "文件是空的")
    try:
        out = ingest(file.filename or "upload", data)
    except JdIngestError as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:  # noqa: BLE001 —— 转换/解析都可能炸，但必须说清是哪种
        raise HTTPException(500, f"抽取失败（{type(exc).__name__}）：{exc}")
    _audit({"at": time.time(), "who": _who(), "kind": "jd-upload",
            "jd": out["jd"], "file": file.filename, "md": out["md"]})
    return out


@router.get("/cvs")
def list_cvs(search: str = Query(""), limit: int = Query(400, ge=1, le=2000)) -> Dict[str, Any]:
    """可选简历清单（展示名为伪造，见下）。

    简历与 JD 是**一对多**：一个人可能投过几个岗。所以这里不做"按 JD 过滤"的强绑定，
    只给 jd 字段供前端分组/筛选 —— 但缺口**永远是一份简历对模板**，不是一堆简历的统计。
    """
    from services.talent_gap import cv_list

    rows = cv_list(limit=limit, search=search)
    return {"cvs": rows, "count": len(rows),
            "disclosure": "展示名为本仓库伪造（basis=fabricated）；原件姓名已脱敏"}


@router.get("/cv-gap")
def get_cv_gap(cv: str = Query(..., description="必填：缺口是相对某一份简历才成立的"),
               jd: str = Query("", description="可选：判断条件字段是否适用于这份 JD")):
    """一份简历对着 CV 模板（26 字段）的缺口。"""
    from services.talent_gap import cv_gap_for

    if not cv.strip():
        raise HTTPException(422, "cv 不能为空：缺口是相对某一份简历才成立的")
    try:
        return cv_gap_for(cv.strip(), jd.strip())
    except KeyError:
        raise HTTPException(404, f"没有这份简历：{cv}")


@router.get("/raw")
def get_raw(jd: str = Query(""), path: str = Query(...)):
    """仓库产物的**原始字节**,内联返回(给 docx/pdf/图片的查看器用)。

    为什么需要:页面在 http 下打不开 `file://`;而把 docx 当文本读回来只能得到乱码。
    `Content-Disposition: inline` 才能让 Office 查看器在页内打开而不是触发下载。
    """
    p = _resolve(path)
    suffix = p.suffix.lower()
    media = RAW_MEDIA.get(suffix, "application/octet-stream")
    return FileResponse(p, media_type=media, filename=p.name,
                        content_disposition_type="inline")


@router.get("/catalog")
def get_catalog() -> Dict[str, Any]:
    """标准目录(分类/组件/要求/JD 与 CV 模板)。

    读的是 `build_catalog.py` 的产物 —— 门禁里有「catalog 与三份 YAML 一致」这一条,
    所以这里**不重算**:重算会让页面和门禁各有一份真相。
    """
    path = TALENT / "catalog.json"
    if not path.is_file():
        raise HTTPException(404, "还没有 catalog.json —— 先跑 "
                                 "`python -m scripts.talent.build_catalog`")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise HTTPException(500, f"catalog.json 解析失败: {exc}") from exc
    return {"ok": True, **doc}


@router.get("/doc")
def get_doc(jd: str = Query(...), path: str = Query(...)) -> Dict[str, Any]:
    """读一个产物。`path` 是相对 `work/talent/` 的路径。

    文本类(md/yaml/json/txt/代码)直接给 text;有格式的(pdf/docx/pptx/图片/html)给一个
    `url` 让前端的查看器去取原始字节 —— **不把 docx 硬读成文本**:那只会得到乱码,
    而"这份 docx 打不开"看起来像文件坏了,其实是我们读错了方式。
    """
    p = _resolve(path)
    w, why = _rel_allowed(path)
    st = p.stat()
    suffix = p.suffix.lower()
    base = {
        "path": path, "jd": jd, "name": p.name, "ext": suffix,
        "bytes": st.st_size, "mtime": st.st_mtime,
        "writable": w, "readonly_reason": "" if w else why,
    }
    if suffix not in TEXT_LIKE:
        return {**base, "kind": "binary", "viewer": _viewer_for(suffix),
                "media_type": RAW_MEDIA.get(suffix, "application/octet-stream"),
                "url": f"/api/talent/raw?jd={quote(jd)}&path={quote(path)}"}
    return {**base, "kind": "text",
            "text": p.read_text(encoding="utf-8", errors="replace")}


@router.put("/doc")
def save_doc(payload: DocSave) -> Dict[str, Any]:
    """保存一个产物:白名单 → 原子写 + .bak → 审计 → 立刻校验。"""
    rel = (payload.path or "").strip().lstrip("/")
    ok, why = _rel_allowed(rel)
    if not ok:
        # 这里必须硬拒,不能"警告后照写":锚点文件被手改后,整条链的引用全部失效,
        # 而门禁要等到下一次运行时才会红。
        raise HTTPException(403, f"work/talent/{rel} 不可写:{why}")

    p = _resolve(rel)
    if payload.expected_mtime is not None:
        current = p.stat().st_mtime
        if abs(current - payload.expected_mtime) > 1e-6:
            raise HTTPException(
                409,
                f"{rel} 在编辑器打开之后被改过(mtime {current} ≠ {payload.expected_mtime})。"
                f"重新打开再改,否则会覆盖别人的修改。",
            )

    text = payload.text or ""
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise HTTPException(400, f"文件超过 {MAX_BYTES} 字节")

    old = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""
    if old == text:
        return {"saved": False, "reason": "内容没变化", "path": rel,
                "validate": _validate(payload.jd)}

    backup = p.with_suffix(p.suffix + ".bak")
    if p.is_file():
        try:
            backup.write_text(old, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 —— 备份失败不该阻断保存
            logger.warning("talent: backup failed for %s (%s)", p, exc)

    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".talent-", suffix=p.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, p)
    except Exception as exc:  # noqa: BLE001
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise HTTPException(500, f"写入失败:{exc}")

    entry = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "user": _who(), "jd": payload.jd, "path": rel,
        "bytes_before": len(old.encode("utf-8")),
        "bytes_after": len(text.encode("utf-8")),
        "lines_before": old.count("\n"), "lines_after": text.count("\n"),
    }
    _audit(entry)
    logger.info("talent: %s saved by user %s (%d→%d bytes)", rel, entry["user"],
                entry["bytes_before"], entry["bytes_after"])

    return {"saved": True, "path": rel, "audit": entry,
            "mtime": p.stat().st_mtime,
            "validate": _validate(payload.jd)}


# ── agent 产物(只读)──────────────────────────────────────────
# 为什么需要:左轨列的是**仓库里的** work/talent/**,而 agent 的两类文件都在**它自己的工作区**:
#   upload/     你交给它的东西(原始 .doc 等)
#   generated/  它写出来的东西(报告、副本)
# 这是两棵树 —— 于是"它写了什么、我给了它什么"在界面上都看不见。所以把工作区**只读地**
# 暴露出来:看得见,但改不了。写这条路仍然只走上面的白名单 ——
# 一个 agent 不该能直接覆盖正式产物,要变成正式产物得由人抬进 jd_docs/。
#
# 为什么分三条接口而不是一条:
#   不显示格式的文件(md/yaml/txt)**要文本**,好渲染;
#   有格式的(pdf/docx/pptx/图片)要**原始字节**交给浏览器自己的查看器,转文本会丢掉它存在的意义;
#   老式 .doc 是第三种:浏览器打不开,服务端用同一条 legacy_doc 转换链抽成文本(版式不保留,接口如实说明)。
AGENT_EXPOSED_DIRS = ("upload", "generated")
TEXT_LIKE = {
    ".md", ".markdown", ".yaml", ".yml", ".json", ".txt", ".csv", ".tsv", ".log",
    ".xml", ".ini", ".toml", ".conf", ".env", ".css", ".sql", ".sh", ".bash", ".zsh",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".mjs", ".rb", ".go", ".rs", ".java", ".kt",
    ".swift", ".c", ".cpp", ".h", ".hpp", ".mdx",
}
LEGACY_OFFICE = {".doc", ".ppt", ".xls"}
RAW_MEDIA = {
    ".pdf": "application/pdf",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
    ".webp": "image/webp", ".bmp": "image/bmp", ".svg": "image/svg+xml",
    ".html": "text/html; charset=utf-8", ".htm": "text/html; charset=utf-8",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def _viewer_for(suffix: str) -> str:
    """该用哪个查看器渲染。判定放服务端:前端不需要围着扩展名再写一遍,也就不会两边分叉。"""
    if suffix == ".pdf":
        return "pdf"
    if suffix in (".docx", ".pptx"):
        return "office"
    if suffix in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"):
        return "image"
    if suffix in (".html", ".htm"):
        return "html"
    return "other"


def _agent_workspace(agent_id: int, project_id: Optional[int]) -> tuple[pathlib.Path, str]:
    """复用 workspace_manager 的官方解析,**不自己拼路径**。

    自己拼的后果实测过:一个残留的 backend/work/ 目录就让 agent 头 5 次调用都在错的地方找,
    还得出「这份 JD 不存在」的结论。路径只有一个权威来源,这里只调它。
    """
    from db.database import SessionLocal
    from models.deep_agent import DeepAgentTemplate
    from services.workspace_manager import get_workspace_manager

    mgr = get_workspace_manager()
    db = SessionLocal()
    try:
        agent = db.query(DeepAgentTemplate).filter(DeepAgentTemplate.id == agent_id).first()
        if agent is None:
            raise HTTPException(404, f"agent {agent_id} 不存在")
        vault = mgr.project_vault_key(db, project_id) if project_id else None
        root = mgr.resolve_agent_workspace(
            agent, project_id, vault_key=vault or None, agent_key=mgr.agent_vault_key(db, agent)
        )
        return root, str(getattr(agent, "name", "") or f"agent {agent_id}")
    finally:
        db.close()


def _agent_path(agent_id: int, project_id: Optional[int], path: str) -> tuple[pathlib.Path, pathlib.Path]:
    """把工作区相对路径解析成绝对路径,并守住两条边界:只在 upload/generated 里,且真在工作区内。"""
    root, _ = _agent_workspace(agent_id, project_id)
    rel = pathlib.PurePosixPath(path)
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise HTTPException(400, "路径不合法")
    if rel.parts[0] not in AGENT_EXPOSED_DIRS:
        raise HTTPException(400, f"只暴露 {' / '.join(AGENT_EXPOSED_DIRS)}/ 下的文件")
    target = (root / rel.as_posix()).resolve()
    try:
        target.relative_to(root.resolve())      # `..` 绕不出去
    except ValueError:
        raise HTTPException(400, "路径落在工作区之外")
    return target, root


@router.get("/agent-files")
def list_agent_files(agent_id: int = Query(...), project_id: Optional[int] = Query(None),
                     limit: int = Query(400, ge=1, le=4000)) -> Dict[str, Any]:
    """列出 agent 工作区里 upload/ 与 generated/ 的文件(只读)。"""
    root, name = _agent_workspace(agent_id, project_id)
    files: list[dict] = []
    for d in AGENT_EXPOSED_DIRS:
        base = root / d
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if len(files) >= limit:
                break
            if not path.is_file() or path.name in (".gitkeep", ".DS_Store"):
                continue
            try:
                st = path.stat()
            except OSError:
                continue
            files.append({
                "name": path.name,
                "path": str(path.relative_to(root)),
                "dir": d,
                "ext": path.suffix.lower(),
                "bytes": st.st_size,
                "mtime": st.st_mtime,
            })
    return {"agent": {"id": agent_id, "name": name}, "workspace": str(root),
            "dirs": list(AGENT_EXPOSED_DIRS), "files": files}


@router.get("/agent-file")
def get_agent_file(agent_id: int = Query(...), path: str = Query(...),
                   project_id: Optional[int] = Query(None)) -> Dict[str, Any]:
    """读一份 agent 文件:能变成文本的就给文本,否则给一个能取原始字节的 URL。

    返回 kind 是三选一,前端据此选渲染器 —— 判定只在**这里**做一次:
      text       纯文本(md/yaml/json/代码),直接渲染
      converted  老式 .doc/.ppt/.xls,服务端抽成文本(版式不保留)
      binary     有格式的文件(pdf/docx/pptx/图片/html),交给浏览器查看器
    """
    target, root = _agent_path(agent_id, project_id, path)
    if not target.is_file():
        raise HTTPException(404, f"找不到 {path}")
    st = target.stat()
    if st.st_size > MAX_BYTES:
        raise HTTPException(413, f"文件超过 {MAX_BYTES // 1024 // 1024}MB,不在这里读")

    suffix = target.suffix.lower()
    rel = pathlib.PurePosixPath(path).as_posix()
    base = {"path": rel, "name": target.name, "ext": suffix,
            "bytes": st.st_size, "mtime": st.st_mtime}

    if suffix in TEXT_LIKE:
        return {**base, "kind": "text",
                "text": target.read_text(encoding="utf-8", errors="replace")}

    if suffix in LEGACY_OFFICE:
        from services.legacy_doc import legacy_to_docx

        # 先试"转成 OOXML 交给查看器"(保留表格/加粗/段落),转不出来才退回纯文本。
        # 这个顺序是有意的:纯文本会让人以为客户的文件就是一堆没排版的字。
        if legacy_to_docx(target) is not None:
            return {**base, "kind": "binary", "viewer": "office",
                    "media_type": RAW_MEDIA[".docx"], "converted_from": suffix,
                    "url": f"/api/talent/agent-raw?agent_id={agent_id}"
                           + (f"&project_id={project_id}" if project_id else "")
                           + f"&path={quote(rel)}&as=docx"}

        # 没有可用的转换器 —— 至少把字给出来,并如实说明版式不保留。
        from services.legacy_doc import legacy_to_text, unsupported_hint

        try:
            text, converter = legacy_to_text(target)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(415, f"这台机器上抽不出 {suffix} 的文字:{exc}。"
                                     f"{unsupported_hint(suffix)}")
        return {**base, "kind": "converted", "text": text, "converter": converter}

    return {**base, "kind": "binary", "viewer": _viewer_for(suffix),
            "url": f"/api/talent/agent-raw?agent_id={agent_id}"
                   + (f"&project_id={project_id}" if project_id else "")
                   + f"&path={quote(rel)}",
            "media_type": RAW_MEDIA.get(suffix, "application/octet-stream")}


@router.get("/agent-raw")
def get_agent_raw(agent_id: int = Query(...), path: str = Query(...),
                  project_id: Optional[int] = Query(None),
                  as_: Optional[str] = Query(None, alias="as")):
    """原始字节,内联返回。

    为什么要这条:页面在 http 下打不开 `file://`,没有它,生成的 pdf/docx 只能去磁盘上手工找。
    `Content-Disposition: inline` 才能让查看器直接在页内打开,而不是触发下载。
    """
    target, _ = _agent_path(agent_id, project_id, path)
    if not target.is_file():
        raise HTTPException(404, f"找不到 {path}")

    # `as=docx`:老式 .doc 现转成 OOXML 再发,交给前端的 OfficeViewer。
    # 转不出来就 415 —— 让界面显示"没有转换器",而不是发一个浏览器打不开的二进制。
    if as_ in ("docx", "pptx", "xlsx"):
        from services.legacy_doc import legacy_to_docx

        converted = legacy_to_docx(target)
        if converted is None:
            raise HTTPException(415, f"这台机器上没有能把 {target.suffix} 转成 .{as_} 的转换器")
        return FileResponse(converted, media_type=RAW_MEDIA.get(f".{as_}", "application/octet-stream"),
                            filename=f"{target.stem}.{as_}", content_disposition_type="inline")

    media = RAW_MEDIA.get(target.suffix.lower(), "application/octet-stream")
    return FileResponse(target, media_type=media, filename=target.name,
                        content_disposition_type="inline")


@router.post("/validate")
def validate(jd: str = Query(...)) -> Dict[str, Any]:
    """只校验,不写。"""
    if not (TALENT / "jd_links" / f"{jd}.yaml").is_file():
        raise HTTPException(404, f"这份 JD 还没有引用文件:jd_links/{jd}.yaml")
    return _validate(jd)

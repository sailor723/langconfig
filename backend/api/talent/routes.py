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
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
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


def _jd_files(jd: str) -> list[dict]:
    """某份 JD 的全部产物,按"哪一层"分组。"""
    items: list[dict] = []

    def add(rel: str, layer: str, note: str = "") -> None:
        p = TALENT / rel
        exists = p.is_file()
        w, why = _rel_allowed(rel)
        items.append({
            "path": rel,
            "layer": layer,
            "exists": exists,
            "bytes": p.stat().st_size if exists else 0,
            "mtime": p.stat().st_mtime if exists else None,
            "writable": w,
            "readonly_reason": "" if w else why,
            "note": note,
        })

    add(f"jd_links/_source/{jd}.txt", "1 客户原文", "只读锚点")
    add(f"jd_links/{jd}.yaml", "2 引用文件", "改完要过逐字回查")
    add(f"jd_docs/{jd}.定稿.md", "3 定稿", "我方建议/排版可改")
    add(f"jd_docs/{jd}.待补清单.md", "3 回填表", "空白字段的 A/B/C 分级")
    add(f"jd_docs/{jd}.fields.json", "3 字段机读", "")
    add(f"collection/{jd}.yaml", "4 采集清单(机读)", "生成物")
    add(f"collection/{jd}.采集清单.md", "4 采集清单(人读)", "生成物")
    return items


def _jds() -> list[str]:
    if not (TALENT / "jd_links").is_dir():
        return []
    return sorted(p.stem for p in (TALENT / "jd_links").glob("*.yaml"))


# ── 校验:跑真脚本,不在这里重算 ──────────────────────────────

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
    """所有 JD 及其产物清单。"""
    jds = _jds()
    return {
        "jds": [
            {"jd": jd, "files": _jd_files(jd),
             "existing": sum(1 for f in _jd_files(jd) if f["exists"])}
            for jd in jds
        ],
        "writable_prefixes": WRITABLE,
        "readonly_prefixes": READONLY,
        "user": _who(),
    }


@router.get("/doc")
def get_doc(jd: str = Query(...), path: str = Query(...)) -> Dict[str, Any]:
    """读一个产物。`path` 是相对 `work/talent/` 的路径。"""
    p = _resolve(path)
    if not path.startswith(f"jd_links/_source/{jd}") and jd not in path and not path.endswith(".yaml") and not path.endswith(".md"):
        pass  # 不做硬约束:path 已经限定在 work/talent 内
    text = p.read_text(encoding="utf-8", errors="replace")
    w, why = _rel_allowed(path)
    return {
        "path": path, "jd": jd, "text": text,
        "bytes": len(text.encode("utf-8")),
        "mtime": p.stat().st_mtime,
        "writable": w, "readonly_reason": "" if w else why,
    }


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


@router.post("/validate")
def validate(jd: str = Query(...)) -> Dict[str, Any]:
    """只校验,不写。"""
    if not (TALENT / "jd_links" / f"{jd}.yaml").is_file():
        raise HTTPException(404, f"这份 JD 还没有引用文件:jd_links/{jd}.yaml")
    return _validate(jd)

#!/usr/bin/env python3
"""一面数据采信规则:一份数据文件,两个脚本读同一份。

为什么要有这个模块:采信规则曾经只活在 `pick_final --include-simulated` 一个开关里,
判定脚本(`evaluate`)那边完全看不到 —— 于是同一份模拟答案,选人脚本用了、判定脚本
没用,两边的数对不上,而且**各自都看起来正常**。这类"两边都对得上自己"的错最难查,
唯一解法是让规则只存在一处。

现在:规则写在 `work/talent/interview_policy.yaml`,谁改的、什么时候、为什么都在里面;
`evaluate` 和 `pick_final` 都调这里,不存在第二套判断。
"""
from __future__ import annotations

import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[3]
POLICY = ROOT / "work" / "talent" / "interview_policy.yaml"

REAL_ONLY = "real_only"
MOCK_ALLOWED = "mock_allowed"
MODES = (REAL_ONLY, MOCK_ALLOWED)

SIM_BASIS = ("simulated", "simulated_interview")


def load() -> dict:
    if not POLICY.is_file():
        # 没有规则文件 = 没有授权 = 只认真人。默认必须落在最保守的一侧。
        return {"schema": "talent.interview_policy/v1", "default_mode": REAL_ONLY, "jobs": {}}
    return yaml.safe_load(POLICY.read_text(encoding="utf-8")) or {}


def record(jd: str) -> dict:
    """这个 JD 上的规则记录(没有就是空 dict)。"""
    return dict((load().get("jobs") or {}).get(jd) or {})


def mode_for(jd: str, *, override: str | None = None) -> tuple[str, str]:
    """返回 (mode, 来源)。来源写明这个结论是怎么来的,便于在产物里交代。

    override 是命令行强制:`real` 收紧 / `mock` 放开 —— 强制也要留痕。
    """
    if override in ("real", "real_only"):
        return REAL_ONLY, "命令行 --real-only 强制收紧"
    if override in ("mock", "mock_allowed"):
        return MOCK_ALLOWED, "命令行 --include-simulated 强制放开"
    rec = record(jd)
    mode = str(rec.get("mode") or load().get("default_mode") or REAL_ONLY)
    if mode not in MODES:
        # 写错模式名不许"猜一个":直接拒绝,否则拼错就当成了放开
        raise SystemExit(f"interview_policy.yaml: {jd} 的 mode={mode!r} 不合法,只收 {MODES}")
    if rec.get("mode"):
        signer = rec.get("decided_by") or "未署名"
        when = str(rec.get("decided_at") or "未标日期")
        return mode, f"interview_policy.yaml · {jd} · {signer} {when}"
    return mode, f"interview_policy.yaml · default_mode={mode}"


def allows_mock(jd: str, *, override: str | None = None) -> bool:
    return mode_for(jd, override=override)[0] == MOCK_ALLOWED


def is_real_basis(answer: dict) -> bool:
    """没有 basis 的历史答案按真人答的处理(这是老数据的默认约定)。"""
    return str(answer.get("basis") or "interview") not in SIM_BASIS

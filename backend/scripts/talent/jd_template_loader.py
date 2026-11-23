"""读 `work/talent/jd_templates/` —— 一份骨架 + 两版裁剪。

为什么单独成模块:三个消费者(`render_jd_final` / `jd_input_form` / `render_jd_docx`)
都要「按岗位类别选模板」。各写一份合并逻辑,迟早有一处忘了 `inherits`,
于是同一份 JD 在两个脚本里用不同字段集 —— 那正是上一轮 `render`(42 条)与
`input_form`(29 条)分叉的成因。

**用哪一版由 `S1.11 岗位类别` 决定,不由岗位名决定。** 实测反例:品质经理原文写
「直接下属:无」,按名字套经理岗模板会去问管理幅度和预算(空问),同时把作业频次降级掉。

`role_type` 记在 `jd_links/<JD>.yaml` 里,取自原文 S1.08 直接下属:
有具体人员 → manager;写「无」→ staff;**未写 → undetermined,不许猜**,该 JD 标 NOT RUN。
"""
from __future__ import annotations

import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[3]
DIR = ROOT / "work" / "talent" / "jd_templates"
ROLES = ("manager", "staff")


def load(role: str) -> dict:
    """合并 `_common.yaml` + `<role>.yaml`,返回一条可直接消费的模板。

    `by_code` 是 code → 字段元信息(带 section),`not_applicable` 是该版明确不填的码
    (它们**仍然出现**在文档里,只是标「不适用」并写明为什么 —— 悄悄删掉会让读者
    以为漏了,而"不适用"本身就是一条结论)。
    """
    if role not in ROLES:
        raise ValueError(f"未知岗位类别 {role!r},只能是 {ROLES}")
    common = yaml.safe_load((DIR / "_common.yaml").read_text(encoding="utf-8"))
    spec = yaml.safe_load((DIR / f"{role}.yaml").read_text(encoding="utf-8"))
    sections = list(common.get("sections") or []) + list(spec.get("sections") or [])
    by_code: dict[str, dict] = {}
    for sec in sections:
        for f in sec.get("fields") or []:
            by_code[str(f["code"])] = {**f, "section": sec.get("code"), "section_title": sec.get("title")}
    na = [str(c) for c in (spec.get("not_applicable") or [])]
    missing = [c for c in na if c not in by_code]
    if missing:
        # 声明为"不适用"却根本不在模板里 —— 那两种状态会互相掩盖,必须当场说清
        raise ValueError(f"{role}.yaml: not_applicable 里的 {missing} 不在该版字段里")
    return {"role": role, "title": spec.get("template") or role,
            "sections": sections, "by_code": by_code, "not_applicable": na}


def role_of(link: dict) -> tuple[str | None, str]:
    """从一条 `jd_links/<JD>.yaml` 里取岗位类别。返回 `(role, 依据)`。

    `role` 为 None 表示**判不出来** —— 调用方必须据此拒绝渲染,而不是挑一个默认值。
    挑默认值的后果是整份 JD 用错模板,而错在哪要到"问了不该问的问题"时才被发现。
    """
    raw = str(link.get("role_type") or "").strip().lower()
    basis = str(link.get("role_basis") or "").strip()
    if raw in ROLES:
        return raw, basis or "(未写依据)"
    if raw in ("", "undetermined", "unknown", "pending"):
        return None, basis or "role_type 未定"
    return None, f"role_type 取值非法:{raw!r}"


def union_codes() -> set[str]:
    """两版的字段并集 —— 用来校验"每个模板码都在宇宙里,且宇宙里没有孤码"。"""
    out: set[str] = set()
    for role in ROLES:
        out |= set(load(role)["by_code"])
    return out


def render_codes(role: str) -> list[str]:
    """该版要渲染的码(含标成"不适用"的),按 sections 顺序。"""
    tpl = load(role)
    return [c for c, _ in ((c, m) for c, m in tpl["by_code"].items())]

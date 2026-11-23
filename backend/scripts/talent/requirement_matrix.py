"""把一份 JD 的要求摊成「维度 → 组件」一行一条 —— md 与 docx 共用同一份行数据。

为什么要共用:同一份 JD 在 `.md` 和 `.docx` 里如果各算一遍,迟早一处更新、另一处忘
(实测过:`render` 42 条 vs `input_form` 29 条就是这么分叉的)。这里只算一次,
两个渲染器只是把同样的行印成 markdown 表格或 Word 表格。

一行 = 一条要求。**组件**是判人时真正要比对的东西(`skill_8D报告`);没有组件的行
是区间/枚举类要求,直接比属性(A.2/B.1/C.1…)。
"""
from __future__ import annotations

import json
import re

DIM = {"A": "人口属性", "B": "教育", "C": "经历", "D": "技能",
       "E": "素质能力", "F": "资质证书", "G": "合规约束", "H": "语言", "I": "身体条件"}

EDU = {2: "中专/高中", 3: "大专", 4: "本科", 5: "硕士", 6: "博士"}


def cv_total(catalog: dict) -> int:
    """去重后的 CV 份数 —— 从 `scope` 里现取,不写死。

    写死一个数字的风险:语料一变,所有持有率的分母就悄悄错了,而百分比看起来仍然合理。
    """
    m = re.search(r"(\d+)\s*份简历", str(catalog.get("scope") or ""))
    return int(m.group(1)) if m else 0


def build_rows(link: dict, reqs: dict, atts: dict, comp_label: dict,
               catalog: dict, *, origin: str = "client") -> list[dict]:
    """一条客户引用 → 一行。`origin='hr'` 时取 HR 侧要求(它另有作者/理由两列)。"""
    comp_cv = {c["id"]: c.get("cv_count", 0) for c in catalog["components"]}
    out: list[dict] = []
    for c in link.get("citations") or []:
        if (c.get("origin") or "client") != origin:
            continue
        r = reqs.get(c["requirement"]) or {}
        v = c.get("value") or {}
        att = atts.get(r.get("attribute") or "") or {}
        comps = r.get("_resolved") or r.get("components") or []
        assessable = bool(r.get("assessable"))

        if comps:
            need = f"{len(comps)} 项组件:" + "·".join(comp_label.get(x, x) for x in comps)
            short = "·".join(comp_label.get(x, x) for x in comps)
            how = "holds(全部具备)" if r.get("op") == "holds" else f"{r.get('op', '')}(组件)"
            holds = " ".join(f"{comp_label.get(x, x)} {comp_cv.get(x, '?')}" for x in comps) or "—"
        else:
            aid = att.get("id") or "—"
            need = f"{aid} {att.get('label') or r.get('name') or ''}".strip()
            if aid == "A.2":
                short = f"年龄 {v.get('min')}–{v.get('max')}"
            elif aid == "A.1":
                short = "性别 " + "/".join(v.get("in") or [])
            elif aid == "B.1":
                short = f"{EDU.get(v.get('num'), v.get('num'))}及以上"
            elif aid == "B.2":
                short = "专业:" + "/".join(v.get("in") or [])
            elif aid == "C.1":
                short = f"{v.get('num')} 年以上"
            else:
                short = str(c.get("verbatim") or "").rstrip("，,。")
            if r.get("op"):
                how = f"{r['op']} {json.dumps(v, ensure_ascii=False) if v else '(无取值)'}"
            elif r.get("no_component") or not assessable:
                how = "无判定方式(只能面试)"
            else:
                how = "(无 op)"
            holds = "—"

        out.append({
            "dim": r.get("dimension") or "?",
            "dim_label": DIM.get(r.get("dimension") or "", ""),
            "need": need,
            "short": short,
            "verbatim": c.get("verbatim", ""),
            "line": c.get("txt_line", ""),
            "how": how,
            "assessable": assessable,
            "holds": holds,
            "requirement": c.get("requirement", ""),
            "author": c.get("author", ""),
            "rationale": c.get("rationale", ""),
        })
    return out


def dim_summaries(rows: list[dict]) -> dict[str, str]:
    """A–I 每个维度压成一句(给 dim_* 汇总字段用);没有要求的维度返回空串。"""
    out: dict[str, str] = {}
    for d in DIM:
        texts = [r["short"] for r in rows if r["dim"] == d]
        if texts:
            out[d] = " / ".join(texts)
    return out

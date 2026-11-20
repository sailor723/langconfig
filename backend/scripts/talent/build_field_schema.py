#!/usr/bin/env python3
"""把 JD 与 CV 的字段合并成**一份字段全集** —— 字段集只此一份,模板各自裁剪。

一次性迁移工具。输入是 `_retired/` 下两份实测模板,输出是 field_schema.yaml。
日常不要再跑它 —— 新字段直接加进 field_schema.yaml。

为什么必须是生成而不是手写:
    手写两份 schema 再手写一张 crosswalk,是三次记账;任何一次漏改,两侧就悄悄对不上。
    生成的话,字段来源只有 _retired/ 下那两份实测数据,
    合并规则写在代码里,可重跑、可 diff。

合并规则(唯一一条):
    **同一个字段在两侧各出现一次,就合成一条。**
    判"同一个"用 FIELDS 里的手工对应表 —— 这是业务判断,不能自动猜
    (猜"职务名称"="意向职位"就会把岗位和候选人的期望混成一个字段)。

产出:work/talent/field_schema.yaml
    template: {jd: [...], cv: [...]}  —— 两份模板各自的字段清单
    compare:  both | jd_only | cv_only | not_comparable

用法:
    python -m scripts.talent.build_field_schema
"""
from __future__ import annotations

import collections
import pathlib
import sys

import yaml

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]

JD_SCHEMA = ROOT / "work" / "talent" / "_retired" / "jd_schema.yaml"
CV_SCHEMA = ROOT / "work" / "talent" / "_retired" / "cv_schema.yaml"
OUT = ROOT / "work" / "talent" / "field_schema.yaml"

#: 两侧同一个字段的对应表。**业务判断,不是自动猜出来的。**
#   左 = JD 的 (section, name);右 = CV 的 (section, name)
SAME = {
    ("S3", "F.EDU_LEVEL"): ("C3", "edu_level"),
    ("S3", "F.EDU_MAJOR"): ("C3", "major"),
    ("S3", "F.EDU_FULLTIME"): ("C3", "full_time"),
    ("S3", "F.EXP_YEARS"): ("C4", "period"),
    ("S3", "F.EXP_DOMAIN"): ("C4", "title"),
    ("S3", "F.EXP_INDUSTRY"): ("C4", "industry"),
    ("S3", "F.EXP_ACTIVITY"): ("C4", "description"),
    ("S3", "F.SKILL"): ("C5", "skills"),
    ("S3", "F.COMPETENCY"): ("C6", "self_evaluation"),
    ("S3", "F.AGE"): ("C1", "age"),
    ("S3", "F.GENDER"): ("C1", "gender"),
    ("S3", "F.LANGUAGE_LEVEL"): ("C5", "language_level"),
    ("S3", "F.CERTIFICATION"): ("C5", "certification"),
    ("S8", "F.CLEARANCE"): (None, None),
    ("S1", "F.JOB_TITLE"): ("C1", "target_role"),   # 侧向不同:岗位 vs 期望,不可比
    ("S6", "F.WORK_LOCATION"): ("C1", "current_city"),
    ("S7", "F.SALARY"): ("C2", "expected_salary"),
}
#: 合并后仍不可比的(两侧都有字段,但语义/刻度对不上)
NOT_COMPARABLE = {
    "F.JOB_TITLE": "岗位名称 vs 候选人期望职位 —— 两条不同的信息",
    "F.COMPETENCY": "简历「自我评价」是自我陈述,不构成判定依据",
    "F.EXP_DOMAIN": "JD 写「文职类/管理类」,简历只有职位名;分类标准本身不存在",
    "F.EDU_FULLTIME": "简历侧没有任何一份直接写「全日制」,只能推断且推断无出处",
    "F.EXP_INDUSTRY": "简历不写行业,只能从公司名推断",
    "F.WORK_LOCATION": "JD 全批未写工作地点,无法与简历现居地比对通勤",
    "F.SALARY": "JD 侧无薪资区间,单边数据不构成比较",
    "F.LANGUAGE_LEVEL": "简历只写 CET 等级,无统一刻度",
    "F.CLEARANCE": "简历侧完全没有对应字段",
}


def jd_fields() -> list[dict]:
    d = yaml.safe_load(JD_SCHEMA.read_text(encoding="utf-8"))
    out = []
    for sec in d["L1_sections"]:
        for f in sec.get("fields") or []:
            out.append({"section": sec["code"], "name": f["name"], "label": f["label"],
                        "presence": f["presence"], "required": f.get("required", False)})
    return out


def cv_fields() -> list[dict]:
    d = yaml.safe_load(CV_SCHEMA.read_text(encoding="utf-8"))
    out = []
    for sec in d["sections"]:
        for f in sec.get("fields") or []:
            out.append({"section": sec["code"], "name": f["name"], "label": f["label"],
                        "presence": f["presence"], "prop": f.get("prop")})
    return out


def main() -> int:
    jdf, cvf = jd_fields(), cv_fields()
    print(f"输入:JD {len(jdf)} 字段 · CV {len(cvf)} 字段")

    # 手工分类过的(见 field_schema.yaml 的 notes)优先保留
    curated: dict[str, dict] = {}
    if OUT.is_file():
        old = yaml.safe_load(OUT.read_text(encoding="utf-8")) or {}
        curated = {f["label"]: f for f in old.get("fields") or []}

    merged: list[dict] = []
    used_cv: set[tuple] = set()

    # 先处理成对的
    jd_by = {(f["section"], f["label"]): f for f in jdf}
    cv_by = {(f["section"], f["name"]): f for f in cvf}
    pairs = {v: k for k, v in SAME.items()}
    handled_jd: set[tuple] = set()

    # 把 S3 的 9 个维度当作字段(它们在 jd_schema 里没有 fields 列表)
    s3 = [f for f in jdf if f["section"] == "S3"]

    def emit(fid, label, jd=None, cv=None, dimension=None, scale=None, note=None):
        cmp_ = "both" if (jd and cv) else ("jd_only" if jd else "cv_only")
        if fid in NOT_COMPARABLE:
            cmp_ = "not_comparable"
        merged.append({
            "id": fid, "label": label, "dimension": dimension, "scale": scale,
            "jd": ({"section": jd["section"], "presence": jd["presence"],
                    "required": jd.get("required", False)} if jd else None),
            "cv": ({"section": cv["section"], "presence": cv["presence"],
                    "prop": cv.get("prop")} if cv else None),
            "compare": cmp_,
            **({"note": note} if note else {}),
            **({"not_comparable_because": NOT_COMPARABLE[fid]} if fid in NOT_COMPARABLE else {}),
        })

    # 1) curated 里已有的,原样保留(它们带了 dimension/scale/values/note)
    for f in curated.values():
        # 手工分类过的也要重新过一遍「不可比」判定 —— 否则它保留着旧结论,
        # 合并后的可比数会虚高(第一版就是这个错:不可比 0 个)。
        if f["id"] in NOT_COMPARABLE:
            f = dict(f, compare="not_comparable",
                     not_comparable_because=NOT_COMPARABLE[f["id"]])
        merged.append(f)
    curated_labels = {f["label"] for f in curated.values()}

    # 2) JD 侧剩余字段 → jd_only
    for f in jdf:
        if f["label"] in curated_labels:
            continue
        emit(f"F.JD_{f['name'].upper()}", f["label"], jd=f,
             note="岗位侧字段,简历无对应项" if f["section"] != "S3" else None)

    # 3) CV 侧剩余字段 → cv_only
    curated_cv_labels = set()
    for f in curated.values():
        if f.get("cv"):
            curated_cv_labels.add(f["label"])
    for f in cvf:
        if f["label"] in curated_labels or f["label"] in curated_cv_labels:
            continue
        if any(f["label"] == v[1] or f["name"] == v[1] for v in SAME.values() if v[1]):
            continue
        emit(f"F.CV_{f['name'].upper()}", f["label"], cv=f,
             note="候选人侧字段,JD 无对应项")

    # 规范化:section 为 null 且 presence=0 的一侧视为"没有这个字段" —— 存成 None,
    # 不要留一个 {section: null} 的空壳。第一版留了空壳,渲染器按 section 分组时直接崩。
    for m in merged:
        for side in ("jd", "cv"):
            b = m.get(side)
            if b and not b.get("section") and not b.get("presence"):
                m[side] = None

    cnt = collections.Counter(m["compare"] for m in merged)
    doc = {
        "version": 2,
        "scope": "东莞制造业 · 10 份职务说明书 × 270 份简历",
        "measured": "2026-11-20",
        "principle": "字段集只有一份;JD 与 CV 是两个模板,各自裁剪。",
        "sections": {
            # 两侧的分区标签。渲染器按它分组,不自己硬编码。
            "jd": {"S1": "岗位标识", "S2": "岗位目的", "S3": "任职资格", "S4": "岗位职责",
                   "S5": "作业明细", "S6": "工作条件", "S7": "元数据", "S8": "合规声明"},
            "cv": {"C1": "基本信息", "C2": "求职意向", "C3": "教育背景", "C4": "工作经历",
                   "C5": "技能与证书", "C6": "其他"},
        },
        "templates": {
            "jd": {"name": "职务说明书",
                   "rule": "渲染 jd 非 null 的字段;其余标「JD 未写」"},
            "cv": {"name": "候选人档案",
                   "rule": "渲染 cv 非 null 的字段;其余标〔待补〕"},
        },
        "totals": {"fields": len(merged), **dict(cnt)},
        "fields": sorted(merged, key=lambda m: (
            {"both": 0, "not_comparable": 1, "jd_only": 2, "cv_only": 3}[m["compare"]],
            m["id"])),
    }
    OUT.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False,
                                  default_flow_style=False, width=200), encoding="utf-8")
    print(f"写出 {OUT.relative_to(ROOT)}")
    print(f"  字段 {len(merged)} · 可比 {cnt['both']} · 不可比 {cnt['not_comparable']} · "
          f"仅JD {cnt['jd_only']} · 仅CV {cnt['cv_only']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

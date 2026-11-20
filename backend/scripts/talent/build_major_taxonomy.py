#!/usr/bin/env python3
"""把「专业」建成本体里的两级层级,让**推理机**来回答"这算不算工程类专业"。

为什么要有这一步:
    要求说的是「机电一体化/电子技术/自动化/工业工程/机械工程**等**工程类专业」。
    那个「等」字,靠字符串匹配是永远处理不了的:白名单精确匹配会误杀
    「材料成型及控制工程」,子串匹配又处理不了「工商管理」不含工程但含「工」。
    这不是文本问题,是**分类问题** —— 所以把它交给分类学,而不是正则。

做法(严格按 DSH 的规矩:算的部分确定性,判断的部分留出处):
    ① 有序规则把语料里的 97 种专业名分到「专业类」,每条记录**命中了哪条规则**
    ② 专业类挂到「门类」(工学/管理学/文学…)—— 这层是 subClassOf,推理机做传递
    ③ 生成 Turtle:类 + 个体 + 候选人 :hasMajor
    ④ 跑 HermiT,取 `?m a :工学` 这类蕴含
    ⑤ 落成 ontology_facts.json,每个结论带**推导链**(m → 专业类 → 门类)

这样 join 那边读到的不是"字符串像不像",而是"本体说它属于工学",
而且能说出是哪两跳推出来的。

用法:
    python -m scripts.talent.build_major_taxonomy            # 生成 ttl + 推理 + 落盘
    python -m scripts.talent.build_major_taxonomy --check     # 只报告分类结果
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
ROOT = HERE.parents[2]
sys.path.insert(0, str(BACKEND))

PROFILE = BACKEND / "features" / "ontology" / "profiles" / "talent_v1"
NS = "https://cube.local/ontology/talent_v1#"
FACTS = ROOT / "work" / "talent" / "cv_facts.json"
TAXO_OUT = PROFILE / "major_taxonomy.ttl"
ABOX_OUT = PROFILE / "abox_major.ttl"
ONT_FACTS = ROOT / "work" / "talent" / "ontology_facts.json"

TRUSTED = {"stated", "inferred", "computed"}

#: 有序规则:第一条命中的生效。每条纹样都要能在专业名里看见字面依据,
#: 顺序敏感的地方(「电子商务」必须先于「电子」、「大数据与会计」必须先于「大数据」)
#: 都写在这里,而不是靠正则的聪明。
#:   (规则正则, 专业类, 门类, 判据说明)
RULES: list[tuple[str, str, str, str]] = [
    # ── 管理学 · 工商管理族(必须在「电子」「工程」之前,否则电子商务会被判成电子信息)
    (r"电子商务",                  "工商管理类",   "管理学", "专业名含「电子商务」"),
    (r"工商管理|工商企业管理|企业工商管理|企业管理", "工商管理类", "管理学", "专业名含「工商管理/企业管理」"),
    (r"市场营销|商务管理",           "工商管理类",   "管理学", "专业名含「市场营销/商务管理」"),
    (r"旅游管理|酒店管理|导游",       "旅游管理类",   "管理学", "专业名含「旅游/酒店/导游」"),
    (r"人力资源管理",               "工商管理类",   "管理学", "专业名含「人力资源」"),
    (r"物流管理",                   "物流管理与工程类", "管理学", "专业名含「物流」"),
    (r"行政管理|公共事业",           "公共管理类",   "管理学", "专业名含「行政管理」"),
    (r"资源管理",                   "公共管理类",   "管理学", "专业名含「资源管理」"),
    # ── 管理学 · 财会族
    (r"会计|财务|资产评估",          "工商管理类",   "管理学", "专业名含「会计/财务/资产评估」(教育部目录:会计学属管理学)"),
    # ── 工学 · 机械族
    (r"智能制造",                   "机械类",       "工学",   "专业名含「智能制造」"),
    (r"机电",                       "机电设备类",   "工学",   "专业名含「机电」(机电设备类)"),
    (r"机械",                       "机械类",       "工学",   "专业名含「机械」"),
    (r"数控",                       "机械类",       "工学",   "专业名含「数控」"),
    # ── 工学 · 自动化族
    (r"自动化|电气",                "自动化类",     "工学",   "专业名含「自动化/电气」"),
    # ── 工学 · 电子信息族
    (r"通信",                       "电子信息类",   "工学",   "专业名含「通信」"),
    (r"电子",                       "电子信息类",   "工学",   "专业名含「电子」"),
    # ── 工学 · 计算机族
    (r"计算机|软件|物联网|虚拟现实", "计算机类",     "工学",   "专业名含「计算机/软件/物联网/虚拟现实」"),
    # ── 工学 · 其他族
    (r"材料",                       "材料类",       "工学",   "专业名含「材料」"),
    (r"建筑|Architecture",          "土木建筑类",   "工学",   "专业名含「建筑」"),
    (r"水利|水电",                  "土木建筑类",   "工学",   "专业名含「水利水电」"),
    (r"纺织|服装工程|服装设计与工程", "纺织类",      "工学",   "专业名含「纺织/服装工程」"),
    (r"安全工程",                   "安全科学与工程类", "工学", "专业名含「安全工程」"),
    (r"汽车|轨道交通|铁道",          "交通运输类",   "工学",   "专业名含「汽车/轨道交通/铁道」"),
    # ── 运营管理:必须排在交通运输之后,否则「城市轨道交通**运营管理**」会被它吃掉
    (r"运营管理",                   "工商管理类",   "管理学", "专业名含「运营管理」(且不含交通语境)"),
    # ── 经济学
    (r"经济学|国际经济与贸易|经贸",  "经济与贸易类", "经济学", "专业名含「经济学/经贸」"),
    # ── 文学
    (r"汉语言文学",                 "中国语言文学类", "文学", "专业名含「汉语言文学」"),
    (r"文秘",                       "中国语言文学类", "文学", "专业名含「文秘」(秘书学属文学门类)"),
    (r"英语|日语|法语|西班牙语|越南语|外语", "外国语言文学类", "文学", "专业名含语种名"),
    # ── 法学 / 医学 / 教育学 / 理学 / 艺术学
    (r"法律|法学",                  "法学类",       "法学",   "专业名含「法律」"),
    (r"康复治疗",                   "医学技术类",   "医学",   "专业名含「康复治疗」"),
    (r"教育",                       "教育学类",     "教育学", "专业名含「教育」"),
    (r"心理学",                     "心理学类",     "理学",   "专业名含「心理学」"),
    (r"设计|动漫",                  "设计学类",     "艺术学", "专业名含「设计/动漫」"),
]

#: 规则没命中时的兜底。**不许猜** —— 落到「其他」并标出来,等人补规则。
FALLBACK = ("未分类", "未分类", "没有规则命中 —— 需要人补一条规则")


def classify(major: str) -> tuple[str, str, str]:
    for pat, cat, field, why in RULES:
        if re.search(pat, major):
            return cat, field, why
    return FALLBACK


def slug(major: str) -> str:
    """把专业名压成 IRI 本地名。中文直接用,只替换非法字符 —— 不用哈希,人要能读。"""
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "_", major).strip("_")
    return f"major_{s}"


def local_majors() -> dict[str, int]:
    facts = json.loads(FACTS.read_text(encoding="utf-8"))
    c = collections.Counter()
    for d in facts.values():
        m = d.get("major") or {}
        if m.get("basis") in TRUSTED and m.get("value"):
            c[str(m["value"]).strip()] += 1
    return dict(c)


def emit_turtle(majors: dict[str, int]) -> tuple[str, str, dict[str, tuple]]:
    """生成两份 Turtle:专业层级 + 候选人→专业的断言。"""
    names = sorted(majors)
    assigned = {m: classify(m) for m in names}
    cats = sorted({a[0] for a in assigned.values()})
    fields = sorted({a[1] for a in assigned.values()})

    tax = [
        "# 专业层级 —— 由 scripts/talent/build_major_taxonomy.py 生成,不要手改。",
        "# 目的:让「等工程类专业」这种说法能被推理,而不是被正则近似。",
        "@prefix : <https://cube.local/ontology/talent_v1#> .",
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "",
        ":Major a owl:Class .",
        ":MajorField a owl:Class ; owl:disjointUnionOf ( " +
        " ".join(f":field_{f}" for f in fields) + " ) .",
        ":MajorCategory a owl:Class .",
        "",
    ]
    for f in fields:
        # 显式 a owl:Class —— 只写 `a :MajorField` 时 owlready2 不把它当类,
        # 推理能跑但 members 永远是空(踩过:201 人全是"不一致")
        tax.append(f':field_{f} a owl:Class, :MajorField ; rdfs:label "{f}" .')
    tax.append("")
    for cat in cats:
        fields_of = sorted({a[1] for a in assigned.values() if a[0] == cat})
        assert len(fields_of) == 1, f"{cat} 跨了多个门类:{fields_of}"
        tax.append(f':cat_{cat} a owl:Class, :MajorCategory ; rdfs:label "{cat}" ; '
                   f':majorField :field_{fields_of[0]} ')
        tax.append(f"    ; rdfs:subClassOf :field_{fields_of[0]} .")
    tax.append("")
    for m in names:
        cat, field, _why = assigned[m]
        tax.append(f':{slug(m)} a :Major ; a :cat_{cat} ; rdfs:label "{m}" .')
    tax.append("")
    tax.append(":hasMajor a owl:ObjectProperty ; rdfs:domain :Candidate ; rdfs:range :Major .")

    facts = json.loads(FACTS.read_text(encoding="utf-8"))
    abox = [
        "# 候选人 → 专业。由 scripts/talent/build_major_taxonomy.py 生成,不要手改。",
        f"@prefix : <{NS}> .",
        "",
    ]
    for cid, d in sorted(facts.items()):
        m = d.get("major") or {}
        if m.get("basis") in TRUSTED and m.get("value"):
            abox.append(f':{cid.replace("cand_", "cand_")} :hasMajor :{slug(str(m["value"]).strip())} .')
    return "\n".join(tax) + "\n", "\n".join(abox) + "\n", assigned


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只打印分类结果,不写文件")
    args = ap.parse_args()

    majors = local_majors()
    tax, abox, assigned = emit_turtle(majors)

    dist = collections.Counter((a[1], a[0]) for a in assigned.values())
    unclassified = [m for m, a in assigned.items() if a[1] == "未分类"]
    print(f"语料 {len(majors)} 种专业 / {sum(majors.values())} 人")
    for (field, cat), n in sorted(dist.items(), key=lambda x: (-x[1], x[0])):
        print(f"  {field:6s} · {cat:14s} {n:3d} 种")
    if unclassified:
        print(f"  ! 未分类 {len(unclassified)} 种:{unclassified}")
    if args.check:
        return 0

    TAXO_OUT.write_text(tax, encoding="utf-8")
    ABOX_OUT.write_text(abox, encoding="utf-8")
    print(f"写出 {TAXO_OUT.relative_to(ROOT)} / {ABOX_OUT.relative_to(ROOT)}")

    # ── 跑推理机:只问「门类」和「专业类」这两层,不问全部类(全量推理会慢到没意义)
    from features.ontology.reasoning.reasoner import load_graph, reason

    settings = json.loads((PROFILE / "talent_v1_settings.json").read_text(encoding="utf-8"))
    g = load_graph([PROFILE / settings.get("abox", "abox.ttl"), PROFILE / "reasoning.ttl",
                    TAXO_OUT, ABOX_OUT])
    watch = [NS + f"field_{f}" for f in sorted({a[1] for a in assigned.values()})]
    watch += [NS + f"cat_{c}" for c in sorted({a[0] for a in assigned.values()})]
    res = reason(g, watch_classes=watch)
    print(f"reasoner: {res.engine} · {res.elapsed_ms:.0f} ms · consistent={res.consistent}")

    # ── 落成 facts:每个候选人的专业 → 专业类 → 门类,带推导链
    cand_major = {}
    for ln in abox.splitlines():
        m = re.match(r":(\S+) :hasMajor :(\S+) \.", ln)
        if m:
            cand_major[m.group(1)] = m.group(2)
    member_of: dict[str, list[str]] = {}
    for cls in watch:
        for ind in res.members_of(cls):
            member_of.setdefault(ind.rsplit("#", 1)[-1], []).append(cls.rsplit("#", 1)[-1])

    # ── 先落「专业名 → 专业类 → 门类」这张表。
    # 候选人的专业可能来自简历,也可能来自访谈(廖的专业就是访谈补的),
    # 所以 join 需要的是**按专业名查表**,而不是只按候选人查。
    major_tbl = {}
    for m in majors:
        cat, field, why = assigned[m]
        ent = member_of.get(slug(m), [])
        major_tbl[m] = {"category": cat, "field": field, "rule": why,
                        "entailed_classes": sorted(ent),
                        "chain": [f"{slug(m)} a cat_{cat}", f"cat_{cat} ⊑ field_{field}"],
                        "field_entailed": f"field_{field}" in ent}

    out = {}
    for cid, mslug in cand_major.items():
        major = next((m for m in majors if slug(m) == mslug), None)
        cat, field, why = assigned.get(major, FALLBACK)
        entailed = member_of.get(mslug, [])
        out[cid] = {
            "major": major, "category": cat, "field": field,
            "rule": why,
            # 推导链:本体自己说的,不是这段代码说的
            "entailed_classes": sorted(entailed),
            "chain": [f"{mslug} a cat_{cat}", f"cat_{cat} ⊑ field_{field}"],
            "field_entailed": f"field_{field}" in entailed,
        }
    payload = {
        "source": "HermiT over talent_v1 abox + reasoning.ttl + major_taxonomy.ttl",
        "ref": "scripts/talent/build_major_taxonomy.py",
        "majors": major_tbl,
        "candidates": out,
    }
    ONT_FACTS.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    ok_c = sum(1 for v in out.values() if v["field_entailed"])
    ok_m = sum(1 for v in major_tbl.values() if v["field_entailed"])
    print(f"专业表 {len(major_tbl)} 条 · 门类被推理机确认 {ok_m} 条")
    print(f"候选人 {len(out)} 人 · 门类被推理机确认 {ok_c} 人")
    print(f"写出 {ONT_FACTS.relative_to(ROOT)}")
    if ok_m != len(major_tbl) or ok_c != len(out):
        print("  ! 有门类没被推出来 —— 分类与 ttl 不一致,先别用")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

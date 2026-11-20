#!/usr/bin/env python3
"""用例 1:一份 JD + 五个人,端到端跑一遍。小,但每一环都是真的。

这不是框架,是一次**垂直切片**。它把四份已经存在的东西装进一张图,然后回答一个真问题:

    component_catalog.yaml   ← 能力全集(106 个节点)
    jd_links/品质经理.yaml    ← 需求侧投影(10 条要求)
    abox.ttl                 ← 供给侧事实(5 个人)
    ↓
    Neo4j
    ↓
    "这 5 个人各自满足品质经理的哪几条要求,凭什么"

为什么只用 5 个人而不是 277:277 人不需要新的设计,只需要跑 277 次;而 5 个人能把
"满足 / 不满足 / **不知道**"三种状态都摆在一屏上 —— 第三种是最容易被做成"不满足"的那一种。

五个人是照分布挑的,不是随便挑的(实测:9 个组件里,全池最多的人也只有 5 个):

    廖(品质经理/NPI经理/研发经理)  5/9  · 学历4 · 年限15 · 年龄未读到
    孙(专案工程师)                 4/9  · 学历3 · 年限10 · 年龄未读到
    李(38岁/行政专员)              4/9  · 学历3 · 年限未读到 · 年龄38
    徐(专案工程师/1年以内)         3/9  · 学历2 · 年限1
    廖(专案工程师)                 0/9  · 学历2 · 年限10

**这个脚本不做的事(刻意的):**

  · 不给"合格/不合格"的判决。判定需要阈值(覆盖率 ≥ 多少算过),而那个决定还没做。
    这里只如实报出:**命中几个组件 / 每条属性阈值够不够 / 哪几项没有数据**。
  · 不写 PG。图是唯一落点。
  · 不做增量。每次清空重建 —— 一张能对账的图必须可以从源文件重放出来。

用法:
    python -m scripts.talent.graph_uc1                      # 建图并打印结算
    python -m scripts.talent.graph_uc1 --dry-run            # 只读源文件,不写图
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
ROOT = HERE.parents[2]
sys.path.insert(0, str(BACKEND))

import yaml  # noqa: E402
from rdflib import Literal, URIRef  # noqa: E402
from rdflib.namespace import RDF  # noqa: E402

CATALOG = ROOT / "work" / "talent" / "component_catalog.yaml"
LINK = ROOT / "work" / "talent" / "jd_links" / "品质经理.yaml"
PROFILE = BACKEND / "features" / "ontology" / "profiles" / "talent_v1" / "talent_v1_settings.json"

#: 五个人,按"命中组件数"从高到低挑,让三种判定状态都能出现
CANDIDATES = [
    "cand_廖___品质经理_NPI经理_研发经理",              # 5/9 真品质经理
    "cand_专案工程师_东莞_12_16K_孙___10年以上",        # 4/9
    "cand_李___38岁_行政专员_智通简历_编号",            # 4/9 唯一有年龄的人
    "cand_专案工程师_东莞_10_15K_徐___1年以内",         # 3/9 学历与年限都不够
    "cand_专案工程师_东莞_12_16K_廖___10年以上",        # 0/9 一个组件都没有
]

WIPE = "MATCH (n) DETACH DELETE n"

DDL = [
    "CREATE INDEX comp_id IF NOT EXISTS FOR (c:Component) ON (c.id)",
    "CREATE INDEX cand_id IF NOT EXISTS FOR (c:Candidate) ON (c.id)",
    "CREATE INDEX req_id  IF NOT EXISTS FOR (r:Requirement) ON (r.id)",
]


# ─────────────────────────────────────────────── 读源文件
def load_catalog() -> dict:
    return yaml.safe_load(CATALOG.read_text(encoding="utf-8"))


def load_link() -> dict:
    return yaml.safe_load(LINK.read_text(encoding="utf-8"))


def load_candidates(ids: list[str]) -> dict[str, dict]:
    """从 ABox 读 — 供给侧的唯一真源不是 PG,是 abox.ttl。"""
    import rdflib

    settings = json.loads(PROFILE.read_text(encoding="utf-8"))
    ns = (settings.get("ns") or "").rstrip("#") + "#"
    g = rdflib.Graph()
    g.parse(PROFILE.parent / settings.get("abox", "abox.ttl"), format="turtle")

    def one(node, prop):
        for value in g.objects(node, URIRef(ns + prop)):
            if isinstance(value, Literal):
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return str(value)
            return str(value).rsplit("#", 1)[-1]
        return None

    out = {}
    for cid in ids:
        node = URIRef(ns + cid)
        if (node, RDF.type, URIRef(ns + "Candidate")) not in g:
            print(f"  ! ABox 里没有 {cid}")
            continue
        out[cid] = {
            "id": cid,
            "years": one(node, "yearsExperience"),
            "educationRank": one(node, "educationRank"),
            "age": one(node, "age"),
            "sourceFile": one(node, "sourceFile"),
            "components": sorted(str(o).rsplit("#", 1)[-1]
                                 for o in g.objects(node, URIRef(ns + "hasSkill"))),
        }
    return out


# ─────────────────────────────────────────────── 建图
def build(driver, catalog: dict, link: dict, candidates: dict[str, dict]) -> dict:
    comps = catalog["components"]
    atts = catalog["attributes"]
    cats = catalog["categories"]
    dims = catalog["dimensions"]
    reqs = link["requirements"]

    def rows_of_components():
        return [{"id": c["id"], "label": c["label"], "kind": c.get("kind"),
                 "cvCount": c.get("cv_count"), "category": c["category"]} for c in comps]

    with driver.session(database=os.environ.get("NEO4J_DATABASE", "neo4j")) as s:
        s.run(WIPE).consume()
        for stmt in DDL:
            s.run(stmt).consume()

        # ① 能力全集 —— 完全来自 component_catalog.yaml
        s.run("UNWIND $rows AS r MERGE (d:Dimension {id:r.id}) SET d.name = r.id + ' ' + r.label, d.label = r.label",
              rows=[{"id": d["id"], "label": d["label"]} for d in dims]).consume()
        s.run("""UNWIND $rows AS r MERGE (a:Attribute {id:r.id})
                 SET a.name=r.id + ' ' + r.label, a.label=r.label,
                     a.cardinality=r.cardinality, a.scale=r.scale,
                     a.prop=r.prop, a.propExists=r.propExists
                 WITH a, r MATCH (d:Dimension {id:r.dim}) MERGE (a)-[:IN_DIMENSION]->(d)""",
              rows=[{"id": a["id"], "label": a["label"], "cardinality": a["cardinality"],
                     "scale": a.get("scale"), "prop": a.get("prop"),
                     "propExists": bool(a.get("prop_exists")), "dim": a["dimension"]}
                    for a in atts]).consume()
        s.run("""UNWIND $rows AS r MERGE (c:Category {id:r.id}) SET c.name = r.id, c.label = r.label
                 WITH c MATCH (d:Dimension {id:'D'}) MERGE (c)-[:IN_DIMENSION]->(d)""",
              rows=[{"id": c["id"], "label": c["label"]} for c in cats]).consume()
        s.run("""UNWIND $rows AS r MERGE (c:Component {id:r.id})
                 SET c.name=r.label, c.label=r.label, c.kind=r.kind, c.cvCount=r.cvCount
                 WITH c, r MATCH (cat:Category {id:r.category})
                 MERGE (c)-[:IN_CATEGORY]->(cat)""", rows=rows_of_components()).consume()

        # ② 需求侧投影 —— 完全来自 jd_links/品质经理.yaml
        s.run("""MERGE (j:JD {name:$name})
                 SET j.sourceFile=$src, j.sourceText=$txt,
                     j.sourceLines=$lines, j.atomicRequirements=$atomic""",
              name=link["jd"], src=link["source_file"], txt=link["source_text"],
              lines=link["count"]["source_lines"],
              atomic=link["count"]["atomic_requirements"]).consume()
        s.run("""UNWIND $rows AS r MERGE (q:Requirement {id:r.id})
                 SET q.name=r.id, q.verbatim=r.verbatim, q.kind=r.kind, q.assessable=r.assessable,
                     q.sourceText=r.sourceText, q.txtLine=r.txtLine, q.sectionIndex=r.sectionIndex,
                     q.jd=r.jd,
                     q.noComponent=r.noComponent, q.attributeRef=r.attributeRef
                 WITH q, r MATCH (j:JD {name:r.jd}) MERGE (j)-[:HAS_REQUIREMENT]->(q)""",
              rows=[{"id": r["id"], "verbatim": r["verbatim"], "kind": r.get("kind"),
                     "assessable": bool(r.get("assessable")),
                     "sourceText": r.get("source_text"), "txtLine": r.get("txt_line"),
                     "sectionIndex": r.get("section_index"),
                     "jd": link["jd"],
                     "noComponent": bool(r.get("no_component")),
                     "attributeRef": r.get("attribute_ref")} for r in reqs]).consume()
        s.run("""UNWIND $rows AS r MATCH (q:Requirement {id:r.req})
                 MATCH (c:Component {id:r.comp}) MERGE (q)-[:ON_COMPONENT]->(c)""",
              rows=[{"req": r["id"], "comp": c} for r in reqs for c in (r.get("components") or [])]).consume()
        s.run("""UNWIND $rows AS r MATCH (q:Requirement {id:r.req})
                 MATCH (a:Attribute {id:r.att}) MERGE (q)-[:ON_ATTRIBUTE]->(a)""",
              rows=[{"req": r["id"], "att": r["attribute"]} for r in reqs if r.get("attribute")]).consume()

        # 每条要求都落在**恰好一个** Dimension 上。这是分类事实,不是抄近路:
        #   带 attribute 的要求 → 由该属性的 dimension 决定
        #   直接写 dimension 的要求 → 用它自己声明的(E 维这种 prop=null 的空壳属性走这条)
        #   只挂组件的技能要求 → D
        # 它让「按维度看一个岗要什么」变成一跳,而不是在 Neo4j 里连点三下。
        att_dim = {a["id"]: a["dimension"] for a in atts}
        s.run("""UNWIND $rows AS r MATCH (q:Requirement {id:r.req})
                 MATCH (d:Dimension {id:r.dim}) MERGE (q)-[:IN_DIMENSION]->(d)""",
              rows=[{"req": r["id"],
                     "dim": (att_dim.get(r.get("attribute") or "")
                             or r.get("dimension")
                             or "D")} for r in reqs]).consume()
        s.run("""UNWIND $rows AS r MATCH (q:Requirement {id:r.req})
                 MATCH (a:Attribute {id:r.att}) MERGE (q)-[:LEVEL_CHECK_ON]->(a)""",
              rows=[{"req": r["id"], "att": (r.get("level_check") or {}).get("attribute")}
                    for r in reqs if (r.get("level_check") or {}).get("attribute")]).consume()

        # ③ 供给侧投影 —— 来自 abox.ttl
        s.run("""UNWIND $rows AS r MERGE (c:Candidate {id:r.id})
                 SET c.name=r.id, c.years=r.years, c.educationRank=r.edu, c.age=r.age, c.sourceFile=r.src""",
              rows=[{"id": c["id"], "years": c["years"], "edu": c["educationRank"],
                     "age": c["age"], "src": c["sourceFile"]} for c in candidates.values()]).consume()
        s.run("""UNWIND $rows AS r MATCH (c:Candidate {id:r.c})
                 MATCH (k:Component {id:r.k}) MERGE (c)-[:HAS_COMPONENT]->(k)""",
              rows=[{"c": c["id"], "k": k} for c in candidates.values() for k in c["components"]]).consume()

        # ── 层级规则:所有节点必须挂在 Dimension 下面;要求不能绕过 Dimension 直接连叶子。
        #    这五条不是"当前恰好成立",是**图的形状约束**,违反就不许出图。
        HIERARCHY = [
            ("每个 Attribute 必须在某个 Dimension 下",
             """MATCH (a:Attribute) WHERE NOT (a)-[:IN_DIMENSION]->(:Dimension) RETURN a.id AS x"""),
            ("每个 Component 必须能上溯到 Dimension",
             """MATCH (k:Component) WHERE NOT (k)-[:IN_CATEGORY]->(:Category)-[:IN_DIMENSION]->(:Dimension)
                RETURN k.id AS x"""),
            ("每个 Category 必须在某个 Dimension 下",
             """MATCH (c:Category) WHERE NOT (c)-[:IN_DIMENSION]->(:Dimension) RETURN c.id AS x"""),
            ("要求连 Attribute 时必须同时连 Dimension(不许绕过维度)",
             """MATCH (q:Requirement)-[:ON_ATTRIBUTE]->(:Attribute)
                WHERE NOT (q)-[:IN_DIMENSION]->(:Dimension) RETURN q.id AS x"""),
            ("要求连 Component 时必须同时连 Dimension",
             """MATCH (q:Requirement)-[:ON_COMPONENT]->(:Component)
                WHERE NOT (q)-[:IN_DIMENSION]->(:Dimension) RETURN q.id AS x"""),
            ("约束的属性必须属于该要求声明的维度",
             """MATCH (q:Requirement)-[:ON_ATTRIBUTE]->(a:Attribute)-[:IN_DIMENSION]->(ad:Dimension)
                MATCH (q)-[:IN_DIMENSION]->(qd:Dimension) WHERE ad <> qd RETURN q.id AS x"""),
            ("要求的组件必须属于该要求声明的维度",
             """MATCH (q:Requirement)-[:ON_COMPONENT]->(:Component)-[:IN_CATEGORY]->(:Category)
                      -[:IN_DIMENSION]->(kd:Dimension)
                MATCH (q)-[:IN_DIMENSION]->(qd:Dimension) WHERE kd <> qd RETURN q.id AS x"""),
        ]
        for label, cypher in HIERARCHY:
            bad = s.run(cypher).data()
            if bad:
                raise SystemExit(f"层级规则被违反,拒绝出图 —— {label}: {bad[:5]}")

        # 一致性断言:一条要求的 IN_DIMENSION 必须等于它真正约束的那个节点所属的维度。
        # 读图的人一定会走 JD → Requirement → Dimension → 属性 这条路;
        # 那条路会顺带连上同一维度里的**其他**属性(QM-02 会连上专业/全日制/院校层次),
        # 所以必须钉住:真正被约束的属性 = ON_ATTRIBUTE 那一条,不是 IN_DIMENSION 后能到的全部。
        drift = s.run("""
            MATCH (q:Requirement)-[:IN_DIMENSION]->(d:Dimension)
            OPTIONAL MATCH (q)-[:ON_ATTRIBUTE]->(a:Attribute)-[:IN_DIMENSION]->(ad:Dimension)
            WITH q, d, ad WHERE ad IS NOT NULL AND d <> ad
            RETURN q.id AS req, d.id AS declared, ad.id AS actual
        """).data()
        if drift:
            raise SystemExit(f"维度归属不一致,拒绝出图: {drift}")

        counts = s.run("""
            MATCH (n) UNWIND labels(n) AS l
            WITH l, count(*) AS n WHERE l IN ['Dimension','Attribute','Category','Component','JD','Requirement','Candidate']
            RETURN l AS label, n ORDER BY n DESC""").data()
        edges = s.run("MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS n ORDER BY n DESC").data()
    return {"nodes": {r["label"]: r["n"] for r in counts},
            "edges": {r["t"]: r["n"] for r in edges}}


# ─────────────────────────────────────────────── 回答那个真问题
ANSWER = """
MATCH (j:JD {name:$jd})-[:HAS_REQUIREMENT]->(q:Requirement)
OPTIONAL MATCH (q)-[:ON_COMPONENT]->(need:Component)
WITH q, collect(DISTINCT need.id) AS 需要组件
OPTIONAL MATCH (q)-[:ON_ATTRIBUTE]->(att:Attribute)
WITH q, 需要组件, att
MATCH (c:Candidate)
OPTIONAL MATCH (c)-[:HAS_COMPONENT]->(have:Component) WHERE have.id IN 需要组件
WITH c, q, 需要组件, att, collect(DISTINCT have.id) AS 命中组件
RETURN c.id AS 候选人, q.id AS 要求, q.sourceText AS 原句,
       size(需要组件) AS 组件数, size(命中组件) AS 命中数,
       [h IN 命中组件] AS 命中, att.id AS 属性, att.label AS 属性名, att.prop AS 供侧属性,
       [(q)-[:IN_DIMENSION]->(dd:Dimension) | dd.id][0] AS 维度,
       c.years AS 年限, c.educationRank AS 学历, c.age AS 年龄
ORDER BY c.id, q.id
"""


def attribute_verdict(link: dict, candidates: dict, attr_id: str, cand_id: str) -> tuple[str, str]:
    """属性类要求:够了 / 不够 / 没有数据。三态,不是两态。"""
    req = next(r for r in link["requirements"] if (r.get("attribute") == attr_id))
    cons = req.get("constraint") or {}
    cand = candidates[cand_id]
    prop = {"A.2": "age", "B.1": "educationRank", "C.1": "years"}.get(attr_id)
    if prop is None:
        return "—", "该属性未建或在语料里没有来源"
    value = cand.get(prop)
    if value is None:
        return "未知", f"{prop} 没读到 —— 不是不合格,是说不清"
    if "min" in cons and "max" in cons:
        ok = cons["min"] <= value <= cons["max"]
        return ("够" if ok else "不够"), f"{cons['min']}~{cons['max']} vs {value}"
    if cons.get("op") == ">=":
        ok = value >= cons["value"]
        return ("够" if ok else "不够"), f">={cons['value']} vs {value}"
    return "—", "这个约束类型没有判定规则"


def report(rows: list[dict], link: dict, catalog: dict, candidates: dict) -> None:
    comp_by_id = {c["id"]: c for c in catalog["components"]}
    reqs = {r["id"]: r for r in link["requirements"]}

    print(f"\n{'═' * 78}\n{link['jd']} · {len(reqs)} 条要求 × {len(candidates)} 个人\n{'═' * 78}")
    for cand_id in candidates:
        print(f"\n▌{cand_id}")
        c = candidates[cand_id]
        print(f"   学历={c['educationRank']} 年限={c['years']} 年龄={c['age']} "
              f"({pathlib.Path(c['sourceFile'] or '').name[:44]})")
        met_comp, met_attr, unknown = 0, 0, 0
        for r in sorted((x for x in rows if x["候选人"] == cand_id), key=lambda x: x["要求"]):
            req = reqs[r["要求"]]
            parts = []
            if r["组件数"]:
                hit = r["命中数"]
                met_comp += 1 if hit else 0
                parts.append(f"组件 {hit}/{r['组件数']}")
                if r["命中"]:
                    parts.append("命中 " + "·".join(comp_by_id[h]["label"] for h in r["命中"]))
            if r["属性"]:
                verdict, why = attribute_verdict(link, candidates, r["属性"], cand_id)
                parts.append(f"{r['属性名']} {verdict}({why})")
                met_attr += 1 if verdict == "够" else 0
                unknown += 1 if verdict == "未知" else 0
            elif req.get("dimension"):
                parts.append(f"→ {req['dimension']} 维(该维无组件,只连到维度)")
            lvl = (req.get("level_check") or {})
            if lvl:
                parts.append(f"{lvl['attribute']} 未测")
            if not r["组件数"] and not r["属性"]:
                parts.append("不可判 —— " + ("素质,只能靠面试" if r["属性名"] is None else "无对应组件"))
                unknown += 1
            print(f"   {r['要求']} [{r['维度']}] 「{r['原句']}」")
            print(f"        └ {(' | '.join(parts)) or '（无归宿）'}")
        print(f"   ── 组件命中 {met_comp} 条要求 · 属性阈值够 {met_attr} 条 · 说不清 {unknown} 处")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    catalog, link = load_catalog(), load_link()
    candidates = load_candidates(CANDIDATES)
    reqs = link["requirements"]
    comps_needed = sorted({c for r in reqs for c in (r.get("components") or [])})
    print(f"catalog: {len(catalog['components'])} 组件 / {len(catalog['attributes'])} 属性 / "
          f"{len(catalog['categories'])} 类别 / {len(catalog['dimensions'])} 维度")
    print(f"JD     : {link['jd']} · {len(reqs)} 条要求 · 引用 {len(comps_needed)} 个组件")
    print(f"候选人 : {len(candidates)} 个")

    if args.dry_run:
        print("dry run: 不写图")
        return 0

    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(
        os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.environ.get("NEO4J_USER", "neo4j"), os.environ.get("NEO4J_PASSWORD", "")))
    try:
        driver.verify_connectivity()
        built = build(driver, catalog, link, candidates)
        print("图: " + " · ".join(f"{k} {v}" for k, v in built["nodes"].items()))
        print("  边: " + " · ".join(f"{k} {v}" for k, v in built["edges"].items()))
        with driver.session(database=os.environ.get("NEO4J_DATABASE", "neo4j")) as s:
            rows = s.run(ANSWER, jd=link["jd"]).data()
    finally:
        driver.close()

    report(rows, link, catalog, candidates)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

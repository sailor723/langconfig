#!/usr/bin/env python3
"""用 yaml 的尺子,量一次 277 人 —— 只做 join,不用推理机,不碰 Neo4j。

这是"两种口径并排"的那一步。目的是回答一个具体问题:

    新尺子(10 条要求逐条落位)量出来的人,和旧尺子(PG 闸门 英语∧5S = 0 人)
    到底差在哪?

输入只有三样,全部已存在:
    work/talent/component_catalog.yaml     属性(prop / scale / prop_exists)
    work/talent/requirement_library.yaml   要求语义(算子 / 组件 / 哪些判不了)
    work/talent/jd_links/品质经理.yaml      这份 JD 的引用(阈值 + 原话)
    + abox.ttl                             277 人的事实

**判定规则,写在明面上(不藏):**

  组件类要求   coverage = 命中组件数 / 要求组件数;  coverage >= 0.5 记为"满足"
               —— 0.5 是沿用旧闸门的 GATE_COVERAGE,为了让两边可比。
               覆盖率本身也一起打印出来,所以这个阈值随时可以改。
  属性类要求   算子来自要求(op),阈值来自引用(value),刻度来自属性(scale)。
               供给侧读不到 → "未知"。**未知不是不合格。**
  不可判要求   库里 assessable=false 的(素质、专业属性未建)→ "不可判",不计入分母。

**分母必须一并披露:** 有人只被 3 条要求判过,有人被 8 条判过。
不披露分母就排不出名次 —— 排出来的名次是假的。

用法:
    python -m scripts.talent.evaluate                    # 品质经理 × 277 人
    python -m scripts.talent.evaluate --top 15
    python -m scripts.talent.evaluate --include-duplicates
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
ROOT = HERE.parents[2]
sys.path.insert(0, str(BACKEND))

import yaml  # noqa: E402

CATALOG = ROOT / "work" / "talent" / "component_catalog.yaml"
LIBRARY = ROOT / "work" / "talent" / "requirement_library.yaml"
LINKS = ROOT / "work" / "talent" / "jd_links"
PROFILE = BACKEND / "features" / "ontology" / "profiles" / "talent_v1" / "talent_v1_settings.json"

#: 组件类要求的覆盖率阈值。沿用旧闸门的值,两边才可比。
COVERAGE = 0.5

#: 属性 id → 供给侧字段名
PROP_FIELD = {"A.2": "age", "B.1": "educationRank", "C.1": "years"}


def load_all(jd: str) -> tuple[dict, dict, dict]:
    return (yaml.safe_load(CATALOG.read_text(encoding="utf-8")),
            yaml.safe_load(LIBRARY.read_text(encoding="utf-8")),
            yaml.safe_load((LINKS / f"{jd}.yaml").read_text(encoding="utf-8")))


def load_candidates() -> list[dict]:
    """从 abox.ttl 读 277 人。供给侧的唯一真源是它,不是 PG。"""
    import rdflib
    from rdflib import Literal, URIRef
    from rdflib.namespace import RDF

    settings = json.loads(PROFILE.read_text(encoding="utf-8"))
    ns = (settings.get("ns") or "").rstrip("#") + "#"
    g = rdflib.Graph()
    g.parse(PROFILE.parent / settings.get("abox", "abox.ttl"), format="turtle")
    SAME_AS = "http://www.w3.org/2002/07/owl#sameAs"

    def one(node, prop, *, absolute: bool = False):
        """absolute=True 时不加命名空间 —— 第一版把 owl:sameAs 也拼上了 ns,
        于是 7 份重复简历一条也没认出来,dup 检测静默失效。"""
        for value in g.objects(node, URIRef(prop if absolute else ns + prop)):
            if isinstance(value, Literal):
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return str(value)
            return str(value)
        return None

    out, dupes = [], set()
    for node in g.subjects(RDF.type, URIRef(ns + "Candidate")):
        cid = str(node).rsplit("#", 1)[-1]
        dup = one(node, SAME_AS, absolute=True)
        if dup:
            dupes.add(cid)
        out.append({
            "id": cid,
            "years": one(node, "yearsExperience"),
            "educationRank": one(node, "educationRank"),
            "age": one(node, "age"),
            "duplicate": bool(dup),
            "components": {str(o).rsplit("#", 1)[-1]
                           for o in g.objects(node, URIRef(ns + "hasSkill"))},
        })
    return out


def judge_component(held: set[str], needed: list[str]) -> tuple[str, str]:
    """返回 (状态, 说明)。覆盖率判据写在这里,只有一个地方。"""
    if not needed:
        return "不可判", "没有组件"
    hit = [c for c in needed if c in held]
    cov = len(hit) / len(needed)
    state = "满足" if cov >= COVERAGE else "不满足"
    return state, f"{len(hit)}/{len(needed)}" + (f" 命中 {'·'.join(hit)}" if hit else "")


def judge_attribute(att: dict, req: dict, cit: dict, cand: dict) -> tuple[str, str]:
    """三态:满足 / 不满足 / 未知。未知不折成不满足。"""
    field = PROP_FIELD.get(att["id"])
    if field is None:
        return "不可判", f"{att['id']} 的 supply 属性未建"
    value = cand.get(field)
    if value is None:
        return "未知", f"{field} 没读到"
    val = cit.get("value") or {}
    op = req.get("op")
    if op == "between" and "min" in val and "max" in val:
        ok = val["min"] <= value <= val["max"]
        return ("满足" if ok else "不满足"), f"{val['min']}~{val['max']} vs {value}"
    if op == ">=" and "num" in val:
        ok = value >= val["num"]
        return ("满足" if ok else "不满足"), f">={val['num']} vs {value}"
    if op == "in":
        return "不可判", "取值集合型,属性未建"
    return "不可判", f"算子 {op} 无判定规则"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jd", default="品质经理", help="jd_links/<名字>.yaml")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--include-duplicates", action="store_true")
    args = ap.parse_args()

    catalog, library, link = load_all(args.jd)
    atts = {a["id"]: a for a in catalog["attributes"]}
    comps = {c["id"]: c for c in catalog["components"]}
    reqs = {r["id"]: r for r in library["requirements"]}
    cands = load_candidates()

    pool = [c for c in cands if args.include_duplicates or not c["duplicate"]]
    print(f"JD: {link['jd']} · {len(link['citations'])} 条引用 → "
          f"{len({c['requirement'] for c in link['citations']})} 条要求")
    print(f"候选人: {len(pool)} 人(另有 {len(cands) - len(pool)} 份重复简历已排除)")
    print(f"组件覆盖率阈值: {COVERAGE}(沿用旧闸门,两边可比)")

    # ── 每条要求:分母 + 结果分布
    per_req: dict[str, dict] = {}
    rows = []
    for cand in pool:
        result = {}
        for cit in link["citations"]:
            req = reqs[cit["requirement"]]
            if not req.get("assessable"):
                state, why = "不可判", ("E 维无组件" if req.get("no_component")
                                        else "属性未建")
            elif req.get("components"):
                state, why = judge_component(cand["components"], req["components"])
            elif req.get("attribute"):
                state, why = judge_attribute(atts[req["attribute"]], req, cit, cand)
            else:
                state, why = "不可判", "既无组件也无属性"
            result[cit["requirement"]] = (state, why)
            per_req.setdefault(cit["requirement"], collections.Counter())[state] += 1
        judged = [s for s, _ in result.values() if s in ("满足", "不满足")]
        rows.append({
            "id": cand["id"], "result": result,
            "满足": sum(1 for s, _ in result.values() if s == "满足"),
            "不满足": sum(1 for s, _ in result.values() if s == "不满足"),
            "未知": sum(1 for s, _ in result.values() if s == "未知"),
            "不可判": sum(1 for s, _ in result.values() if s == "不可判"),
            "可判": len(judged),
            "年限": cand["years"], "学历": cand["educationRank"], "年龄": cand["age"],
        })

    print(f"\n{'═' * 84}\n每条要求的分母(有多少人被它真正判过)\n{'═' * 84}")
    print(f"{'要求':24s} {'含义':22s} 满足 / 不满足 / 未知 / 不可判")
    for cit in link["citations"]:
        rid = cit["requirement"]
        c = per_req[rid]
        print(f"{rid:24s} {reqs[rid].get('name','')[:20]:22s} "
              f"{c['满足']:4d} / {c['不满足']:4d} / {c['未知']:4d} / {c['不可判']:4d}"
              + ("  [优先]" if cit.get("tier") == "desirable" else ""))

    print(f"\n{'═' * 84}\n分布:满足 k 条要求的人数(分母 = 该人被几条要求判过)\n{'═' * 84}")
    dist = collections.Counter(r["满足"] for r in rows)
    for k in sorted(dist, reverse=True):
        full = sum(1 for r in rows if r["满足"] == k and r["可判"] == 10 - r["不可判"] and r["未知"] == 0)
        print(f"   满足 {k:2d} 条 → {dist[k]:4d} 人   (其中「零未知」的 {full} 人)")

    print(f"\n{'═' * 84}\nTop {args.top}(按 满足条数 ↓,再看 可判条数 ↓)\n{'═' * 84}")
    rows.sort(key=lambda r: (-r["满足"], -r["可判"], -r["未知"], r["id"]))
    for r in rows[:args.top]:
        gaps = [rid for rid, (s, _) in r["result"].items() if s == "不满足"]
        print(f"\n▌{r['id']}")
        print(f"   满足 {r['满足']} · 不满足 {r['不满足']} · 未知 {r['未知']} · "
              f"不可判 {r['不可判']}  |  学历={r['学历']} 年限={r['年限']} 年龄={r['年龄']}")
        if gaps:
            print(f"   差:{' · '.join(gaps)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

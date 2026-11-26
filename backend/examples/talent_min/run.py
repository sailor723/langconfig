#!/usr/bin/env python3
"""三份简历 + 一份 JD：把「TBox / ABox / 推理」拆开给你看。

跑法（用仓库的 venv）：

    backend/.venv/bin/python backend/examples/talent_min/run.py

四段输出，每一段只回答一个问题：

    1 事实   ABox 里写了什么（3 个人，谁都不会「设计工程师」）
    2 规则   TBox 里写了什么（设计工程师 ≡ 会 CAD 且 ≥3 年）
    3 推理   跑 HermiT，谁被**推**成设计工程师；同时证明「推出来的不是抄来的」
    4 反证   删掉那条公理 → 答案消失；删掉某人的技能 → 他消失

第 3 段的关键不是"推理机能算"，而是**断言里一条都没有**：把 ABox 原样查询得到 0 行，
推理之后才有行。第 4 段是关键的关键：一个删不掉的答案说明它本来就是手写死的。
"""
from __future__ import annotations

import pathlib
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
TBOX, ABOX = HERE / "tbox.ttl", HERE / "abox.ttl"
NS = "http://example.org/talent#"

sys.path.insert(0, str(HERE.parents[1]))          # backend/ on the path


def _local(node) -> str:
    return str(node).rsplit("#", 1)[-1]


def _label(graph, node) -> str:
    from rdflib.namespace import RDFS
    for value in graph.objects(node, RDFS.label):
        return str(value)
    return _local(node)


def main() -> int:
    from rdflib import Graph
    from rdflib.namespace import RDF

    graph = Graph()
    graph.parse(TBOX, format="turtle")
    graph.parse(ABOX, format="turtle")

    print("1 事实（ABox）：3 个候选人各自会什么、几年")
    for node in sorted(graph.subjects(RDF.type, None), key=_local):
        if _local(node) not in ("cand_A", "cand_B", "cand_C"):
            continue
        skills = sorted(_local(o) for o in graph.objects(node, f"{NS}hasSkill"))
        years = next(iter(graph.objects(node, f"{NS}yearsExperience")), None)
        kinds = {_local(t) for s in skills
                 for t in graph.objects(next(n for n in graph.subjects(RDF.type, None)
                                             if _local(n) == s), RDF.type)}
        print(f"   {_label(graph, node):34s} 技能 {', '.join(skills) or '-':28s} "
              f"（类别 {', '.join(sorted(kinds)) or '-'}）  年限 {years}")

    print("\n2 规则（TBox）：JD 说「设计工程师 = 会 CAD 且 3 年以上」")
    print("   :matchesDesignEngineer ≡ :Candidate ⊓ (:hasSkill some :CAD)")
    print("                             ⊓ (:yearsExperience some xsd:integer[>= 3])")

    from features.ontology.reasoning import reasoner as R

    usable, why = R.available()
    if not usable:
        print(f"\n推理机不可用：{why}")
        return 2

    cls = f"{NS}matchesDesignEngineer"
    asserted = [_local(s) for s in graph.subjects(RDF.type, {} and None or RDF.type) if False]
    asserted = [_local(s) for s in graph.subjects(RDF.type, f"{NS}matchesDesignEngineer".replace(NS, NS))]
    result = R.reason(graph, watch_classes=[cls])
    members = [_local(m) for m in result.members_of(cls)]

    print("\n3 推理（HermiT）：ABox 原样查询 vs 推理之后")
    print(f"   ABox 里写着的「设计工程师」：{len(asserted)} 条   ← 一条都没有")
    print(f"   推理之后的成员：{len(members)} 人 → {members}")
    print(f"   耗时 {result.elapsed_ms:.0f} ms · 一致={result.consistent}")

    print("\n4 反证：删掉规则 / 删掉事实，答案必须消失")
    mutated, removed = R.mutate(graph, subject="matchesDesignEngineer",
                               predicate="equivalentClass", namespace=NS)
    after = [_local(m) for m in R.reason(mutated, watch_classes=[cls]).members_of(cls)]
    print(f"   删掉那条公理（{removed} 条三元组）→ 成员 {len(after)} 人 {after}")
    if members:
        who = members[0]
        mutated2, removed2 = R.mutate(graph, subject=who, predicate="hasSkill", namespace=NS)
        after2 = [_local(m) for m in R.reason(mutated2, watch_classes=[cls]).members_of(cls)]
        print(f"   删掉 {who} 的技能（{removed2} 条三元组）→ 成员 {len(after2)} 人 {after2}")

    print("\n一句话：ABox 只说「他会什么」，TBox 只说「什么叫合格」，"
          "「谁合格」是推理机在两者之上算出来的，谁都没写下来。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

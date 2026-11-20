#!/usr/bin/env python3
"""品质经理 JD · 排除项的影响面实测（HermiT，只读，不改任何 profile 文件）。

背景：`:role_品质经理 :requiresSkill :skill_ISO_TS16949` 这条 ABox 断言来自
`12.品质经理职务说明书.doc` **第 24 行「岗位职责」段**，而不是任职资格段。
本脚本回答一个问题：如果把它撤掉，`matches_品质经理` 会少多少人。

跑法（三行都要）：
    cd backend && set -a && source ../.env; set +a
    env -u PGPORT .venv/bin/python ../work/talent/probe_qualitymanager_blast.py

为什么要 `env -u PGPORT`：shell 会导出 PGPORT=5432，劫持默认端口。本脚本不连库，
但保持全仓库统一的调用形，免得下一个人复制时踩坑。

输出三行：
    baseline                                     现状成员数
    drop skill_ISO_TS16949 assertions only       只删「谁持有 ISO/TS16949」的断言
    drop whole QualitySystem route               把 skillsFor_品质经理 的 union 收成只有 LanguageSkill
"""
from __future__ import annotations

import json
import pathlib
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND))

import rdflib  # noqa: E402
from rdflib import Graph, URIRef  # noqa: E402
from rdflib.namespace import OWL, RDF  # noqa: E402

from features.ontology.reasoning import reasoner as R  # noqa: E402

ROLE = "品质经理"
CLASS = f"matches_{ROLE}"
UNION_CLASS = f"skillsFor_{ROLE}"


def members(graph, target: str) -> set[str]:
    return set(R.reason(graph, watch_classes=[target]).members_of(target))


def clone(graph) -> Graph:
    out = Graph()
    for prefix, ns in graph.namespaces():
        out.bind(prefix, ns)
    for triple in graph:
        out.add(triple)
    return out


def main() -> int:
    prof = BACKEND / "features" / "ontology" / "profiles" / "talent_v1"
    cfg = json.loads((prof / "talent_v1_settings.json").read_text(encoding="utf-8"))
    ns = cfg["ns"]
    paths = (list((prof / cfg["ontology_dir"]).glob("*.ttl"))
             + [prof / cfg["abox"], prof / cfg["reasoning"]])
    g = R.load_graph(paths)
    target = ns + CLASS

    base = members(g, target)
    print(f"baseline                                     {len(base)}")

    # ① 只删「谁持有 ISO/TS16949」——即 abox 里所有 obj = skill_ISO_TS16949 的三元组
    mut = clone(g)
    drop = URIRef(ns + "skill_ISO_TS16949")
    for triple in list(mut):
        if triple[2] == drop:
            mut.remove(triple)
    print(f"drop skill_ISO_TS16949 assertions only       {len(members(mut, target))}")

    # ② 把 skillsFor_品质经理 的 union 收成只有 LanguageSkill（整条 QualitySystem 路线撤掉）
    mut2 = clone(g)
    union_from = URIRef(ns + UNION_CLASS)
    for triple in list(mut2.triples((union_from, OWL.equivalentClass, None))):
        mut2.remove(triple)
    node, cell = rdflib.BNode(), rdflib.BNode()
    mut2.add((union_from, OWL.equivalentClass, node))
    mut2.add((node, OWL.unionOf, cell))
    mut2.add((cell, RDF.first, URIRef(ns + "LanguageSkill")))
    mut2.add((cell, RDF.rest, RDF.nil))
    print(f"drop whole QualitySystem route               {len(members(mut2, target))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

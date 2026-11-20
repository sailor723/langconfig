#!/usr/bin/env python3
"""从本体的 :Requirement 类生成 `requirement` 表的行 —— 一处定义,两处消费。

为什么要有这个脚本:要求如果既写在 `reasoning.ttl` 又手写在 `requirement` 表,就是两份真源。
这套系统已经吃过一次苦头(公理判 204、闸门判 299、交集 38,一致率 13%),原因正是"同一件事写两遍"。

所以按 Palantir 式:TTL 是**唯一手写处**,表是**生成物**。本脚本读 TTL 的注解,输出 INSERT。

它不做的事(刻意的):不推导 threshold / 覆盖率 / 排序 —— OWL 表达不了,那些由 fit.py 在 PG 侧算。

用法:
    python -m scripts.talent.gen_from_ontology --profile <settings.json> --dry-run
    python -m scripts.talent.gen_from_ontology --profile <settings.json> --apply
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

import rdflib  # noqa: E402
from rdflib import RDF, OWL, URIRef  # noqa: E402


def requirements_from_ttl(ttl: pathlib.Path, ns: str) -> list[dict]:
    g = rdflib.Graph()
    g.parse(ttl, format="turtle")
    ann = lambda s, p: (str(next(iter(g.objects(s, URIRef(ns + p)))))  # noqa: E731
                        if (s, URIRef(ns + p), None) in g else None)
    out = []
    for node in g.subjects(RDF.type, URIRef(ns + "Requirement")):
        code = ann(node, "code")
        if not code:
            continue
        out.append({
            "code": code,
            "label": ann(node, "label") or str(next(iter(g.objects(node, URIRef(
                "http://www.w3.org/2000/01/rdf-schema#label"))), "")),
            "dimension": ann(node, "dimension"),
            "tier": ann(node, "tier"),
            "provenance": ann(node, "provenance"),
            "verbatim": ann(node, "verbatim"),
            "source_jd": ann(node, "sourceJd"),
            "threshold": float(ann(node, "threshold")) if ann(node, "threshold") else None,
            "owl_class": str(node).replace(ns, ":"),
        })
    return sorted(out, key=lambda r: r["code"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    profile = pathlib.Path(args.profile).resolve()
    settings = json.loads(profile.read_text(encoding="utf-8"))
    ns = (settings.get("ns") or "").rstrip("#") + "#"
    tbox = (profile.parent / (settings.get("reasoning") or "reasoning.ttl")).resolve()
    if not tbox.is_file():
        print(f"no TBox: {tbox}")
        return 2

    rows = requirements_from_ttl(tbox, ns)
    print(f"TBox: {tbox.name} · :Requirement 类 {len(rows)} 个\n")
    print(f"{'code':10s} {'dim':4s} {'tier':10s} {'prov':9s} 标签")
    print("-" * 74)
    for r in rows:
        print(f"{r['code']:10s} {str(r['dimension']):4s} {str(r['tier']):10s} "
              f"{str(r['provenance']):9s} {r['label'][:34]}")

    if not args.apply:
        print(f"\nDRY-RUN —— 会向 requirement 表写入 {len(rows)} 行(ON CONFLICT code 更新)")
        return 0

    import psycopg2
    from psycopg2.extras import execute_values
    conn = psycopg2.connect(
        host="127.0.0.1", port=5433, dbname=settings["dsn"]["dbname"],
        user="langconfig", password="langconfig_dev")
    with conn, conn.cursor() as cur:
        execute_values(cur, """
            insert into requirement (id, role, kind, label, verbatim, source_jd,
                                     mandatory, assessable, tier, threshold, provenance, code,
                                     dimension)
            values %s
            on conflict (id) do update set label=excluded.label, tier=excluded.tier,
                verbatim=excluded.verbatim, dimension=excluded.dimension
        """, [(f"gen_{r['code']}", "role_副总助理", "composite", r["label"], r["verbatim"],
               r["source_jd"], True, True, r["tier"], r["threshold"] or 0.5,
               r["provenance"], r["code"], r["dimension"]) for r in rows])
    print(f"\n已写入 {len(rows)} 行(code 唯一,重复运行会更新)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Scaffold a `dashboard.json` from what the ontology actually DECLARES.

The point of scaffolding from the compiled graph rather than from a template: every panel it emits is a
metric the compiler already answers, and every hole it emits is a metric that already refuses — WITH the
reason it refuses. What it cannot know, it leaves out and names loudly:

  * thresholds (`policy`) — a business decision, not a default
  * the sentences (`briefing`) — they must quote placeholders, and only a human knows what the finding is
  * event markers (`events`) — a date the business cares about

Usage:
    python scaffold_dashboard.py --profile ../ontologies/logistics/logistics_settings.json [--out path]
    python scaffold_dashboard.py --profile … --print          # stdout only

Exit 0 when a declaration was produced; 2 when the profile/ontology cannot be read. It runs the compiler
only (no database), so a refusal here is a DECLARATION problem, not a data problem.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys


def _early_profile() -> None:
    """`--profile` must be in $APP_SETTINGS before sqlgen is imported (it binds the profile once)."""
    argv = sys.argv[1:]
    for i, arg in enumerate(argv):
        if arg == "--profile" and i + 1 < len(argv):
            raw = argv[i + 1]
        elif arg.startswith("--profile="):
            raw = arg.split("=", 1)[1]
        else:
            continue
        p = pathlib.Path(raw).expanduser()
        os.environ["APP_SETTINGS"] = str(p if p.is_absolute() else (pathlib.Path.cwd() / p).resolve())
        return


_early_profile()

REPO = pathlib.Path(os.environ.get("ONTOLOGY_REPO") or "/Users/weiping/dev/Learn/ontology")
sys.path.insert(0, str(REPO / "retail_graph"))

import sqlgen                                            # noqa: E402

RDF_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"


def label_of(g, name: str) -> str | None:
    for s in g.subjects(sqlgen.RDF.type, sqlgen.OWL.DatatypeProperty):
        if str(s).split("#")[-1] != name:
            continue
        for _, _, label in g.triples((s, sqlgen.URIRef(RDF_LABEL), None)):
            return str(label)
    return None


def first_clause(text: str) -> str:
    """The part of a refusal that names the missing declaration (the first clause, trimmed)."""
    head = (text or "").splitlines()[0]
    for sep in (" — ", ": "):
        if sep in head:
            head = head.split(sep)[0]
    return head.strip()[:120]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile")
    ap.add_argument("--out", help="where to write (default: next to the profile)")
    ap.add_argument("--print", action="store_true", dest="to_stdout")
    ap.add_argument("--max-kpis", type=int, default=8)
    args = ap.parse_args()

    profile = pathlib.Path(os.environ.get("APP_SETTINGS", ""))
    if not profile.is_file():
        print(f"scaffold: no profile (--profile or APP_SETTINGS); got {profile}", file=sys.stderr)
        return 2
    g = sqlgen.load()
    declared = sqlgen.metrics(g)
    if not declared:
        print(f"scaffold: {profile} declares no metrics — nothing to build a board from", file=sys.stderr)
        return 2

    kpis, panels, holes = [], [], []
    for name in sorted(declared):
        meta = declared[name]
        try:
            compiled = sqlgen.compile_metric(g, name)
        except sqlgen.Refusal as exc:
            holes.append({
                "metric": name,
                "label": label_of(g, name),
                "expect_refusal": first_clause(str(exc)),
                "why": str(exc),
            })
            continue
        except Exception as exc:                                    # noqa: BLE001
            holes.append({"metric": name, "label": label_of(g, name),
                          "expect_refusal": type(exc).__name__, "why": str(exc)[:200]})
            continue
        keys = (1 if meta.time_bucket else 0) + len(meta.group_by)
        if keys == 0:
            kpis.append({"metric": name, "note": (compiled.notes or [None])[0] or ""})
            continue
        if meta.time_bucket:
            panels.append({"id": f"{name}_series", "kind": "series", "title": compiled.metric,
                           "metric": name, "render": "bar",
                           "expect": "删掉这一行前，先确认单行是数据事实（常量列）还是时间轴缺失"})
        elif keys == 1:
            panels.append({"id": f"{name}_ranked", "kind": "ranked", "title": compiled.metric,
                           "metric": name, "sort": "desc", "limit": 20,
                           "size_by": None,
                           "emit_filter": {"dimension": meta.group_by[0], "column": "key1"},
                           "expect": "补一个 size_by（同一维度的计数指标），否则「每多少」没有分母"})
        else:
            panels.append({"id": f"{name}_matrix", "kind": "matrix", "title": compiled.metric,
                           "metric": name, "rows": "key1", "cols": "key2",
                           "expect": "补一个 size_by（同两键的计数指标），否则格子体积缺失"})

    draft = {
        "_doc": ("scaffold 生成的草稿：面板都来自已声明并已编译的指标，holes 都是真的拒答。"
                 "policy / briefing / events 没有生成——那是业务判断，只能由人（或与业务对话的 agent）写。"),
        "version": 1,
        "ontology": profile.parent.name,
        "title": f"{profile.parent.name} · 看板（草稿）",
        "subtitle": f"口径来自 {profile.name} 指向的 overlay",
        "events": [],
        "policy": [],
        "briefing": {
            "_doc": "每条结论里的数字都必须写成 {metric} 或 {metric:key}；D7 不允许正文出现裸数字。",
            "headline": "",
            "claims": [],
            "cannot_see": [],
            "next": "",
        },
        "kpis": kpis[:args.max_kpis],
        "panels": [p for p in panels if p.get("size_by") is not None or "expect" in p],
        "holes": holes,
        "cross_filter": [],
    }
    # a panel with size_by: None cannot pass D1 — drop it from the draft but SAY so
    dropped = [p["id"] for p in panels if p.get("size_by") is None]
    if dropped:
        draft["_scaffold_notes"] = [
            f"这些分组指标暂时没有面板（缺 size_by/分母）：{', '.join(dropped)}",
            f"补一个同维度的计数指标，再把它们加回来；拒答的 {len(holes)} 个指标已经写进 holes。",
        ]

    text = json.dumps(draft, ensure_ascii=False, indent=2) + "\n"
    if args.to_stdout:
        print(text)
    else:
        out = pathlib.Path(args.out) if args.out else profile.parent / "dashboard.json"
        if out.exists():
            out = out.with_name(out.stem + ".scaffold.json")
        out.write_text(text)
        print(f"wrote {out}")
    print(f"\n{len(kpis)} scalar metrics · {len(panels)} grouped · {len(holes)} refusals",
          file=sys.stderr)
    for hole in holes:
        print(f"  HOLE  {hole['metric']}: {hole['expect_refusal']}", file=sys.stderr)
    print("\nstill to write (only a human/business conversation can): policy, briefing, events",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Build the per-step pictures for the `talent_steps` tutorial's right-hand panel.

THE PICTURE MUST SHOW WHAT THE STEP'S FILE CONTAINS — nothing more. A picture that shows the
finished ontology while the reader is at step 1 teaches the wrong thing, and a picture that shows
something the file does not contain teaches a lie. So the picture is derived FROM the step's TTL:
one box per class and per individual, one arrow per property, and the label says what the class
is (a plain class, a defined class, an individual).

The reason this is a generator and not hand-drawn JSON: the tutorial's whole claim is "the picture
on the right is exactly this step's file". Hand-drawn pictures drift from the files; generated ones
cannot. `tests/test_tutorial_steps.py` checks both directions.

Run:  python scripts/build_tutorial_graphs.py
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PROFILE = ROOT / "features" / "ontology" / "profiles" / "talent_steps"
STEPS = PROFILE / "ontology"
OUT = PROFILE / "tutorial" / "graph.json"

NS = "http://example.org/talent#"


def _local(uri: str) -> str:
    return str(uri).split("#")[-1]


def picture(path: pathlib.Path) -> dict:
    """One step's picture, read out of that step's TTL."""
    from rdflib import Graph, RDF, RDFS, OWL, URIRef

    g = Graph()
    g.parse(path, format="turtle")

    classes = []
    for s in g.subjects(RDF.type, OWL.Class):
        if not isinstance(s, URIRef) or not str(s).startswith(NS):
            continue
        name = _local(s)
        defined = bool(list(g.objects(s, OWL.equivalentClass)))
        classes.append((name, defined))

    individuals = []
    props = set()
    # DEDUPLICATE THE SUBJECTS. `g.subjects(RDF.type, None)` yields one row PER TYPE TRIPLE, so an
    # individual with two types (:Python is a :SkillTag AND a :Programming) came out twice — the
    # picture showed the same box twice and drew its two type-arrows twice.
    seen: set[str] = set()
    for s in g.subjects(RDF.type, None):
        if not isinstance(s, URIRef) or not str(s).startswith(NS):
            continue
        name = _local(s)
        if name in seen:
            continue
        seen.add(name)
        if name in {c for c, _ in classes}:
            continue
        # rdflib's `objects(s, RDF.type, X)` IGNORES the third argument — it returns every object of
        # (s, rdf:type), so asking "is this a property?" that way says YES to every individual
        # (measured: :Python and :cand_A were both classified as properties and vanished from the
        # picture). `g.value(s, RDF.type)` is the reliable single-value read.
        types = [_local(t) for t in g.objects(s, RDF.type) if isinstance(t, URIRef)]
        if set(types) & {"ObjectProperty", "DatatypeProperty", "AnnotationProperty"}:
            props.add(name)
            continue
        individuals.append((name, [t for t in types if t in {c for c, _ in classes}]))

    # ── layout: classes on the left, individuals on the right, arrows between ──
    nodes, edges = [], []
    col = 0
    y = 30

    for name, defined in sorted(classes):
        nodes.append({
            "id": name, "t": f":{name}",
            "l": ["defined class" if defined else "class"],
            "x": 30, "y": y, "w": 150, "h": 44,
            "k": "defined" if defined else "class",
        })
        y += 58
        col += 1

    y = 30
    for name, types in sorted(individuals):
        label = "individual" + (f" · {', '.join(types)}" if types else "")
        nodes.append({
            "id": name, "t": f":{name}",
            "l": [label],
            "x": 260, "y": y, "w": 170, "h": 44,
            "k": "object",
        })
        for t in types:
            edges.append({"a": name, "b": t, "l": "type", "k": "sub"})
        y += 58

    # a candidate's skill link is the story of steps 6-7: draw the FACT that uses it
    for subj in g.subjects(URIRef(NS + "hasSkill"), None):
        if _local(subj) not in {n for n, _ in individuals}:
            continue
        obj = _local(next(g.objects(subj, URIRef(NS + "hasSkill"))))
        if obj in {n["id"] for n in nodes}:
            edges.append({"a": _local(subj), "b": obj, "l": "hasSkill", "k": "join"})

    # EVERY PROPERTY GETS A NODE. A property is a thing in the ontology, and the reader must be
    # able to see it — whether it is a number (a slot on its domain) or a link (a bridge between two
    # boxes). Drawing one as a node and the other only as an edge label made the picture
    # inconsistent: `yearsExperience` appeared twice (node AND edge label) while `hasSkill`
    # appeared once (edge label only), so a reader could not tell that both were properties.
    for prop in sorted(props):
        p = URIRef(NS + prop)
        dom = next(iter(g.objects(p, RDFS.domain)), None)
        rng = next(iter(g.objects(p, RDFS.range)), None)
        if dom is None or rng is None:
            continue
        dom_name, rng_name = _local(dom), _local(rng)
        node_ids = {n["id"] for n in nodes}
        if dom_name not in node_ids:
            continue
        # the range of a DATA property is a datatype, not a box: it is a slot on the domain
        if str(rng).startswith("http://www.w3.org/2001/XMLSchema#"):
            if prop not in node_ids:
                nodes.append({
                    "id": prop, "t": f":{prop}",
                    "l": [f"a slot · holds a {rng_name.split('#')[-1]}"],
                    "x": 260, "y": 30 + 58 * (len(nodes) % 6), "w": 170, "h": 44,
                    "k": "prop",
                })
            edges.append({"a": dom_name, "b": prop, "l": "holds", "k": "prop"})
            continue
        # the range of an OBJECT property is another box: it is the bridge between two boxes
        if prop not in node_ids:
            nodes.append({
                "id": prop, "t": f":{prop}",
                "l": ["a link between two boxes"],
                "x": 260, "y": 30 + 58 * (len(nodes) % 6), "w": 170, "h": 44,
                "k": "prop",
            })
        if rng_name in node_ids:
            edges.append({"a": dom_name, "b": prop, "l": "from", "k": "join"})
            edges.append({"a": prop, "b": rng_name, "l": "to", "k": "join"})

    return {"nodes": nodes, "edges": edges}


def main() -> int:
    steps = {}
    for n in range(1, 8):
        name = f"step{n:02d}.ttl"
        steps[str(n)] = picture(STEPS / name)
    doc = {
        "_doc": ("每一步的本体图，由 scripts/build_tutorial_graphs.py 从该步的 TTL 生成 —— "
                 "图里的东西就是文件里的东西。节点：id / t 标题 / l 标签行 / x,y,w,h 位置 / k 种类；"
                 "边：a / b 两端 / l 标签 / k 种类。"),
        "steps": steps,
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    for n in range(1, 8):
        p = steps[str(n)]
        print(f"  step {n}: {len(p['nodes'])} nodes, {len(p['edges'])} edges")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

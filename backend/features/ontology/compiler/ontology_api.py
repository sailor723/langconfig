#!/usr/bin/env python3
"""ontology_api.py — the loaded ontology as JSON, for a browser that is not the workbench.

The workbench itself is a set of pages: good for asking a question, awkward for *reading*
what is declared. This turns the same compiled graph into one document — objects, their
tables and keys, the definitions (axioms), the links, and every metric with its compiled
SQL or its refusal — so an editor, a CI job or another app can browse the ontology without
scraping HTML or re-implementing the compiler.

    python ontology_api.py --profile ontologies/clinic/clinic_settings.json

Prints one JSON object. Exit 0 when the profile loads; 1 when it does not (with the error
in the document, because "why won't it load" is the first thing a browser should tell you).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import sqlgen  # noqa: E402
from rdflib import OWL, RDF, RDFS  # noqa: E402

P = sqlgen.P


def resolve(profile: dict, key: str) -> pathlib.Path | None:
    raw = profile.get(key) or ""
    if not raw:
        return None
    p = pathlib.Path(raw)
    return (p if p.is_absolute() else (profile["_base"] / p)).resolve()


def _label(g, name: str) -> str | None:
    node = P(name)
    obj = next(iter(g.objects(node, RDFS.label)), None)
    return str(obj) if obj is not None else None


def _desc(g, name: str) -> str | None:
    node = P(name)
    obj = next(iter(g.objects(node, sqlgen.P("businessDescription"))), None)
    return str(obj) if obj is not None else None


def _columns(g, cls: str) -> list[dict]:
    """Every data property whose domain is exactly this class."""
    out = []
    for prop in g.subjects(RDF.type, OWL.DatatypeProperty):
        domains = [str(o).split("#")[-1] for o in g.objects(prop, RDFS.domain)]
        if cls not in domains:
            continue
        local = str(prop).split("#")[-1]
        col = next(iter(g.objects(prop, sqlgen.P("physicalColumn"))), None)
        out.append({"name": local, "column": str(col) if col else None,
                    "label": _label(g, local), "annotated": col is not None})
    return sorted(out, key=lambda c: (c["column"] is None, c["name"]))


def build(profile_path: pathlib.Path) -> dict:
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile["_base"] = profile_path.parent
    sqlgen.reconfigure(ns=profile.get("ns"),
                       ontology_dir=str(resolve(profile, "ontology_dir") or (HERE / "ontology")),
                       overlay=str(resolve(profile, "overlay") or ""),
                       drop_overlay=not profile.get("overlay"))
    g = sqlgen.load()

    classes = sorted({str(s).split("#")[-1] for s in g.subjects(RDF.type, OWL.Class)
                      if str(s).startswith(sqlgen.NS)})
    objects, definitions = [], []
    for cls in classes:
        axioms = list(g.objects(P(cls), OWL.equivalentClass))
        predicate = next(iter(g.objects(P(cls), sqlgen.P("physicalPredicate"))), None)
        table = next(iter(g.objects(P(cls), sqlgen.P("physicalTable"))), None)
        pk = [str(x) for x in g.objects(P(cls), sqlgen.P("primaryKey"))]
        entry = {"name": cls, "label": _label(g, cls), "description": _desc(g, cls),
                 "table": str(table) if table else None, "primaryKey": pk,
                 "columns": _columns(g, cls) if table else []}
        if axioms or predicate is not None:
            kinds = []
            for axiom in axioms:
                for pred, kind in ((OWL.intersectionOf, "intersection"),
                                   (OWL.unionOf, "union")):
                    if list(g.objects(axiom, pred)):
                        kinds.append(kind)
            if predicate is not None:
                kinds.append("physicalPredicate")
            members = sorted({str(o).split("#")[-1]
                              for axiom in axioms
                              for lst in g.objects(axiom, OWL.unionOf)
                              for o in g.items(lst)})
            entry.update({"kind": kinds[0] if kinds else "axiom", "kinds": kinds,
                          "members": members,
                          "predicate": str(predicate) if predicate is not None else None,
                          "base": sqlgen.concept_base_class(g, cls)})
            definitions.append(entry)
        else:
            objects.append(entry)

    links = []
    for prop in g.subjects(RDF.type, OWL.ObjectProperty):
        local = str(prop).split("#")[-1]
        col = next(iter(g.objects(prop, sqlgen.P("physicalColumn"))), None)
        ref = next(iter(g.objects(prop, sqlgen.P("references"))), None)
        links.append({"name": local, "label": _label(g, local),
                      "from": [str(o).split("#")[-1] for o in g.objects(prop, RDFS.domain)],
                      "to": str(ref).split("#")[-1] if ref else None,
                      "column": str(col) if col else None})
    links.sort(key=lambda l: l["name"])

    metrics = []
    for name, m in sorted(sqlgen.metrics(g).items()):
        entry = {"name": name, "label": _label(g, name), "description": _desc(g, name),
                 "aggregate": m.aggregate, "grain": m.grain, "universe": m.universe,
                 "where": m.where, "groupBy": m.group_by, "formula": m.formula,
                 "numerator": m.numerator, "denominator": m.denominator, "scale": m.scale,
                 "unit": m.unit, "missing": m.missing}
        try:
            compiled = sqlgen.compile_metric(g, name)
            entry["sql"] = compiled.sql
            entry["notes"] = compiled.notes
        except Exception as exc:                                # noqa: BLE001
            entry["refused"] = str(exc)
        metrics.append(entry)

    return {
        "ok": True,
        "profile": profile_path.name,
        "path": str(profile_path),
        "ns": profile.get("ns"),
        "title": profile.get("title"),
        "dsn": {k: v for k, v in (profile.get("dsn") or {}).items() if k != "password"},
        "guard": profile.get("guard") or {},
        "features": profile.get("features") or {},
        "objects": objects,
        "definitions": definitions,
        "links": links,
        "metrics": metrics,
        "counts": {
            "objects": len(objects),
            "definitions": len(definitions),
            "links": len(links),
            "metrics": len(metrics),
            "compiled": sum(1 for m in metrics if "sql" in m),
            "refused": sum(1 for m in metrics if "refused" in m),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    args = ap.parse_args()
    path = pathlib.Path(args.profile).expanduser().resolve()
    try:
        print(json.dumps(build(path), ensure_ascii=False))
        return 0
    except Exception as exc:                                     # noqa: BLE001
        print(json.dumps({"ok": False, "profile": path.name,
                          "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""tutorial_api.py — the tutorial for one profile: steps, a metric run, a definition.

An ontology with no tutorial is one nobody learns to read, so every profile gets one:

  * `steps`       the authored `tutorial.json` beside the profile when the build shipped it;
                  otherwise steps **derived from the declarations themselves** — the objects,
                  the definitions, the metrics that compile, the ones that refuse, the guard.
  * `run`         compile a declared metric and actually run it (under the guardrails), so a
                  tutorial step can show the number instead of a screenshot of it.
  * `definition`  a definition's compiled predicate, its table, and how many rows it selects.

Runs under the interpreter that has rdflib + psycopg2 (the workbench server stays stdlib):

    python tutorial_api.py --profile <profile.json> --mode steps
    python tutorial_api.py --profile <profile.json> --mode run --metric collectionRate
    python tutorial_api.py --profile <profile.json> --mode definition --class NoShowAppointment

Prints one JSON object. Exit 0 on success, 1 when the request cannot be answered (the error
is in the document — the tutorial should show *why*, not fail silently).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import psycopg2  # noqa: E402
import dsn as _dsn  # the one place a declared DSN becomes a connection
import sqlgen  # noqa: E402
import guard  # noqa: E402
from rdflib import OWL, RDF  # noqa: E402

P = sqlgen.P


def resolve(profile: dict, key: str) -> pathlib.Path | None:
    raw = profile.get(key) or ""
    if not raw:
        return None
    p = pathlib.Path(raw)
    return (p if p.is_absolute() else (profile["_base"] / p)).resolve()


def load_profile(path: pathlib.Path) -> dict:
    profile = json.loads(path.read_text(encoding="utf-8"))
    profile["_base"] = path.parent
    sqlgen.reconfigure(ns=profile.get("ns"),
                       ontology_dir=str(resolve(profile, "ontology_dir") or (HERE / "ontology")),
                       overlay=str(resolve(profile, "overlay") or ""),
                       drop_overlay=not profile.get("overlay"))
    return profile


def classes(g) -> list[str]:
    return sorted({str(s).split("#")[-1] for s in g.subjects(RDF.type, OWL.Class)
                   if str(s).startswith(sqlgen.NS)})


def refused(g, name: str) -> str | None:
    try:
        sqlgen.compile_metric(g, name)
        return None
    except Exception as exc:                                    # noqa: BLE001
        return str(exc).splitlines()[0]


# ───────────────────────────────────────────────────────────── steps
def _guard_of(profile_path: pathlib.Path) -> dict:
    try:
        return json.loads(profile_path.read_text(encoding="utf-8")).get("guard") or {}
    except Exception:                                           # noqa: BLE001
        return {}


def _features_of(profile_path: pathlib.Path) -> dict:
    try:
        return json.loads(profile_path.read_text(encoding="utf-8")).get("features") or {}
    except Exception:                                           # noqa: BLE001
        return {}


def authored(profile_path: pathlib.Path) -> dict | None:
    doc = profile_path.parent / "tutorial.json"
    if not doc.exists():
        return None
    try:
        data = json.loads(doc.read_text(encoding="utf-8"))
    except Exception as exc:                                    # noqa: BLE001
        return {"ok": False, "source": "profile", "steps": [],
                "error": f"tutorial.json is unreadable: {exc}"}
    steps = data.get("steps") or []
    if not steps:
        return None
    return {"ok": True, "source": "profile", "title": data.get("title"),
            "intro": data.get("intro") or "", "steps": steps,
            "profile": profile_path.name, "guard": _guard_of(profile_path),
            "features": _features_of(profile_path)}


def derive(profile: dict, g) -> list[dict]:
    metrics = sqlgen.metrics(g)
    objects = [c for c in classes(g) if g.value(P(c), P("physicalTable"))]
    definitions = [c for c in classes(g)
                   if g.value(P(c), P("physicalTable")) is None
                   and (list(g.objects(P(c), OWL.equivalentClass))
                        or g.value(P(c), P("physicalPredicate")))]
    compiled = sorted(n for n in metrics if not refused(g, n))
    broken = sorted(n for n in metrics if refused(g, n))
    steps: list[dict] = [{
        "kind": "objects",
        "title": "Objects: what one row is",
        "body": (f"This ontology declares {len(objects)} objects and {len(metrics)} metrics. "
                 f"An object names its physical table and primary key, so every question has a "
                 f"grain to answer at. Pick one — its columns and keys are what the compiler "
                 f"reads."),
        "items": objects,
    }]
    if definitions:
        steps.append({
            "kind": "definitions",
            "title": "Definitions: what a word means",
            "body": ("Membership is an axiom compiled into a predicate, so the same word means the "
                     "same rows in every report. Open one to see its predicate and how many rows "
                     "it actually selects."),
            "items": definitions,
        })
    if compiled:
        steps.append({
            "kind": "metrics",
            "title": "Metrics: declarations, not SQL",
            "body": ("A metric declares its aggregate, grain and scope; the SQL is generated from "
                     "that. Run one — the number comes from the database, under the guardrails, "
                     "and the plan rows are what the guard budgeted."),
            "items": compiled[:6],
        })
    if broken:
        steps.append({
            "kind": "refusals",
            "title": "Refusals: what it cannot answer",
            "body": ("A refusal is a deliverable. These metrics are declared but cannot compile, "
                     "and the compiler says why — that sentence names the declaration still "
                     "missing."),
            "items": broken,
        })
    if profile.get("guard"):
        steps.append({
            "kind": "guard",
            "title": "Guardrails: what a question may cost",
            "body": ("Every read passes these limits before it reaches the database: a page cap, a "
                     "time bound (or a refusal when the data is historical), a plan budget and a "
                     "statement timeout."),
            "items": [],
            "guard": profile["guard"],
        })
    return steps


# ───────────────────────────────────────────────────────────── cards
def metric_cards(profile: dict, g) -> list[dict]:
    """Every metric as one card: declaration, compiled SQL, the number, the guard report.

    This is the shape the workbench's own metric grid uses (and the tutorial's cards): the
    declaration in monospace, the SQL it compiles to, the value the database returns, and the
    guard's notes — so a reader can check all four without leaving the card.
    """
    dsn = _dsn.resolved(profile)      # ${VAR:-default} in a profile's dsn is the deployment's
    out: list[dict] = []
    conn = psycopg2.connect(**dsn) if dsn else None
    try:
        cur = conn.cursor() if conn else None
        for name, m in sorted(sqlgen.metrics(g).items()):
            label = _label(g, name)
            try:
                compiled = sqlgen.compile_metric(g, name)
            except Exception as exc:                            # noqa: BLE001
                out.append({"name": name, "label": label, "error": str(exc)})
                continue
            card = {
                "name": name, "label": label, "sql": compiled.sql,
                "notes": list(compiled.notes),
                "aggregate": m.aggregate, "formula": m.formula, "grain": m.grain,
                "universe": m.universe, "where": m.where, "groupBy": m.group_by,
                "numerator": m.numerator, "denominator": m.denominator, "scale": m.scale,
                "unit": m.unit,
            }
            if cur is not None:
                try:
                    res = guard.run(cur, compiled.sql, cfg=profile.get("guard") or None,
                                    mode="declared")
                    rows = res.get("rows") or []
                    value = rows[0][0] if rows and rows[0] else None
                    if hasattr(value, "isoformat"):
                        value = value.isoformat()
                    elif value is not None and not isinstance(value, (int, float, str, bool)):
                        value = str(value)
                    card.update({"value": value, "plan_rows": res.get("plan_rows"),
                                 "ms": res.get("ms"), "guard_notes": res.get("notes") or []})
                except Exception as exc:                        # noqa: BLE001
                    card["run_error"] = str(exc)
            out.append(card)
    finally:
        if conn is not None:
            conn.close()
    return out


def _label(g, name: str):
    from rdflib import RDFS
    obj = next(iter(g.objects(P(name), RDFS.label)), None)
    return str(obj) if obj is not None else None


# ───────────────────────────────────────────────────────────── run / definition
def run_metric(profile: dict, g, name: str) -> dict:
    compiled = sqlgen.compile_metric(g, name)
    dsn = _dsn.resolved(profile)
    conn = psycopg2.connect(**dsn)
    try:
        cur = conn.cursor()
        res = guard.run(cur, compiled.sql, cfg=profile.get("guard") or None, mode="declared")
        rows = res.get("rows") or []
        value = rows[0][0] if rows and rows[0] else None
        if hasattr(value, "isoformat"):
            value = value.isoformat()
        elif value is not None and not isinstance(value, (int, float, str, bool)):
            value = str(value)
    finally:
        conn.close()
    return {"ok": True, "metric": name, "sql": compiled.sql, "value": value,
            "notes": compiled.notes + (res.get("notes") or []),
            "plan_rows": res.get("plan_rows"), "ms": res.get("ms")}


def definition(profile: dict, g, name: str) -> dict:
    pred = sqlgen.concept_sql(g, name)
    table = None
    base = sqlgen.concept_base_class(g, name)
    if base:
        table = sqlgen.table_of(g, base)
    if table is None:
        for m in sqlgen.metrics(g).values():
            if m.where == name and m.universe:
                table = sqlgen.table_of(g, m.universe)
                break
    rows = None
    if table:
        dsn = _dsn.resolved(profile)
        conn = psycopg2.connect(**dsn)
        try:
            cur = conn.cursor()
            cur.execute(f"SELECT count(*) FROM {table} WHERE {pred}")
            rows = int(cur.fetchone()[0])
        finally:
            conn.close()
    return {"ok": True, "class": name, "predicate": pred, "table": table, "rows": rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument("--mode", choices=("steps", "run", "definition", "cards"), default="steps")
    ap.add_argument("--metric", default="")
    ap.add_argument("--class", dest="klass", default="")
    args = ap.parse_args()
    path = pathlib.Path(args.profile).expanduser().resolve()
    try:
        if args.mode == "steps":
            doc = authored(path)
            if doc is not None:
                print(json.dumps(doc, ensure_ascii=False))
                return 0 if doc.get("ok") else 1
            profile = load_profile(path)
            g = sqlgen.load()
            steps = derive(profile, g)
            print(json.dumps({"ok": True, "source": "derived", "profile": path.name,
                              "title": profile.get("title"),
                              "guard": profile.get("guard") or {},
                              "features": profile.get("features") or {},
                              "intro": ("Derived from this ontology's own declarations: every step "
                                        "names something the graph declares, and every number is "
                                        "computed by the compiled SQL under the guardrails."),
                              "steps": steps}, ensure_ascii=False))
            return 0
        profile = load_profile(path)
        g = sqlgen.load()
        if args.mode == "cards":
            print(json.dumps({"ok": True, "profile": path.name,
                              "cards": metric_cards(profile, g)}, ensure_ascii=False))
            return 0
        if args.mode == "run":
            if not args.metric:
                raise ValueError("--metric is required for mode=run")
            out = run_metric(profile, g, args.metric)
        else:
            if not args.klass:
                raise ValueError("--class is required for mode=definition")
            out = definition(profile, g, args.klass)
        print(json.dumps(out, ensure_ascii=False))
        return 0
    except Exception as exc:                                    # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())

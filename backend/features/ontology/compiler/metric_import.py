#!/usr/bin/env python3
"""Import metrics into the computation overlay — from a sentence, or from a file.

The ontology's whole claim is that every number is *compiled* from declarations, so an
import has exactly one acceptance rule: **the declaration must compile**. Anything else is
refused by name and the overlay is left byte-identical — no half-applied metric, no
"it looks added" — because a metric that silently does not work is worse than one that is
missing. A refusal is a result: it names what the ontology cannot answer and why.

Two doors, one rule:

  * a sentence  — "按城市看诊疗收入", "no-show rate per doctor": the model proposes a
    declaration, the *compiler* decides whether it stands
  * a file      — .ttl (declarations as Turtle), .json ({"metrics": [...]}), or .csv
    (header: name,label,aggregate,...): parsed as given, same compiler check

Usage
-----
    python metric_import.py --profile clinic_probe/clinic_settings.json --mode nl \
        --text "按城市看诊疗收入" [--dry-run]
    python metric_import.py --profile clinic_probe/clinic_settings.json --mode upload \
        --file metrics.csv [--dry-run]

Prints one JSON object on stdout:

    {"ok": bool, "overlay": "…", "added": [{"name","label","sql","notes"}],
     "refused": [{"name","why"}], "notes": ["…"]}

Exit: 0 everything added (or dry-run proposable), 1 something was refused.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import pathlib
import sys
import tempfile
import urllib.request
from typing import Any

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import sqlgen  # noqa: E402  (the compiler this overlay must satisfy)
from rdflib import Graph  # noqa: E402

NS_KEY = "ns"
ALLOWED_AGGREGATES = ("sum", "count", "count_distinct", "avg", "min", "max")
DECL_FIELDS = ("name", "label", "aggregate", "formula", "grain", "universe", "where",
               "numerator", "denominator", "scale", "groupBy", "unit",
               "businessDescription")


# ────────────────────────────────────────────────────────────── the ontology as a menu
def resolve(profile: dict, key: str) -> pathlib.Path | None:
    """A profile-relative path: absolute as given, else relative to the PROFILE's folder.

    `HERE` (the app directory) is the wrong base for an archived profile — a clinic profile
    in `ontologies/clinic/` would quietly load the retail ontology, and the menu would look
    empty rather than wrong. Same rule as `serve_ui.prof_path`.
    """
    raw = profile.get(key) or ""
    if not raw:
        return None
    p = pathlib.Path(raw)
    return (p if p.is_absolute() else (profile["_base"] / p)).resolve()


def load_graph(profile: dict, extra_ttl: str | None = None) -> Graph:
    """Ontology + overlay (+ an in-memory candidate), through sqlgen's own loader."""
    ontology_dir = resolve(profile, "ontology_dir") or (HERE / "ontology")
    overlay = resolve(profile, "overlay")
    paths = sorted(pathlib.Path(ontology_dir).glob("*.ttl"))
    g = sqlgen.load(with_overlay=False,
                    paths=paths + ([overlay] if overlay and overlay.exists() else []))
    if extra_ttl:
        g.parse(data=extra_ttl, format="turtle")
    return g


def menu_of(g: Graph) -> dict:
    """What a sentence may legitimately refer to: classes with columns, declared metrics."""
    classes: dict[str, dict] = {}
    for name, table in _physical_classes(g):
        classes[name] = {"table": table, "columns": sorted(sqlgen.class_columns(g, name))}
    metrics = {}
    for name, m in sqlgen.metrics(g).items():
        metrics[name] = {k: getattr(m, k) for k in
                         ("formula", "aggregate", "grain", "universe", "where",
                          "numerator", "denominator", "group_by")}
    return {"classes": classes, "metrics": metrics}


def _physical_classes(g: Graph) -> list[tuple[str, str]]:
    from rdflib import OWL, RDF
    pred = _p(g, "physicalTable")
    out = []
    for s in g.subjects(pred, None):
        local = str(s).split("#")[-1]
        table = str(next(iter(g.objects(s, pred))))
        out.append((local, table))
    return sorted(out)


def _p(g: Graph, local: str):
    from rdflib import URIRef

    ns = getattr(sqlgen, "NS")
    return URIRef(f"{ns}{local}")


# ─────────────────────────────────────────────────────────── declarations → Turtle
def prefix_header(ns: str) -> str:
    """Prefixes for the fragment.

    A fragment validated on its own has no `@prefix` context, and one appended to an
    overlay that does not declare them would be unreadable there too — so the block
    carries its own header. Turtle allows a repeated @prefix; the overlay's meaning does
    not change.
    """
    return (f"@prefix :     <{ns}> .\n"
            "@prefix owl:  <http://www.w3.org/2002/07/owl#> .\n"
            "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n")


def render_ttl(decls: list[dict], ns: str) -> str:
    """A declaration block in the overlay's own vocabulary (Turtle)."""
    lines = ["", prefix_header(ns),
             "# ── imported " + _stamp() + " ────────────────────────────────────────"]
    for d in decls:
        subject = f"<{ns}{d['name']}>"
        lines.append(f"{subject} a owl:DatatypeProperty ;")
        body = []
        if d.get("label"):
            body.append(f'    rdfs:label "{_lit(d["label"])}"')
        if d.get("aggregate"):
            body.append(f'    :aggregate "{_lit(d["aggregate"])}"')
        if d.get("formula"):
            body.append(f'    :formula "{_lit(d["formula"])}"')
        for key in ("grain", "universe", "where", "numerator", "denominator"):
            if d.get(key):
                body.append(f"    :{key} :{d[key]}")
        if d.get("scale"):
            body.append(f'    :scale "{_lit(d["scale"])}"')
        for prop in d.get("groupBy") or []:
            body.append(f"    :groupBy :{prop}")
        if d.get("unit"):
            body.append(f'    :unit "{_lit(d["unit"])}"')
        if d.get("businessDescription"):
            body.append(f"    :businessDescription \"\"\"{d['businessDescription']}\"\"\"")
        if not body:                                  # never emit a bare subject
            continue
        lines.append(" ;\n".join(body) + " .")
        lines.append("")
    return "\n".join(lines)


def _lit(text: str) -> str:
    return str(text).replace("\\", "\\\\").replace('"', '\\"')


def _stamp() -> str:
    import datetime
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


# ─────────────────────────────────────────────────────────────── the acceptance rule
def check(decls: list[dict], g: Graph) -> tuple[list[dict], list[dict], list[str]]:
    """Compile every candidate against the ontology. Returns (added, refused, notes)."""
    added, refused, notes = [], [], []
    declared = sqlgen.metrics(g)
    for d in decls:
        name = (d.get("name") or "").strip()
        if not name:
            refused.append({"name": "(unnamed)", "why": "a declaration needs a :name"})
            continue
        agg = (d.get("aggregate") or "").strip()
        if agg and agg not in ALLOWED_AGGREGATES:
            refused.append({"name": name,
                            "why": f":aggregate \"{agg}\" is not one of {list(ALLOWED_AGGREGATES)}"})
            continue
        if not agg and not (d.get("numerator") and d.get("denominator")):
            refused.append({"name": name,
                            "why": "needs :aggregate, or :numerator + :denominator for a ratio"})
            continue
        for ref in (d.get("numerator"), d.get("denominator")):
            if ref and ref not in declared:
                refused.append({"name": name,
                                "why": f":{ref} is not a declared metric "
                                         f"(declared: {sorted(declared)})"})
                break
        else:
            try:
                compiled = sqlgen.compile_metric(g, name)
            except sqlgen.Refusal as exc:                      # the compiler is the judge
                refused.append({"name": name, "why": str(exc)})
                continue
            except Exception as exc:                           # noqa: BLE001
                refused.append({"name": name, "why": f"{type(exc).__name__}: {exc}"})
                continue
            added.append({"name": name, "label": d.get("label") or name,
                          "sql": compiled.sql, "notes": compiled.notes})
            notes.extend(f"{name}: {n}" for n in compiled.notes)
    return added, refused, notes


def apply_overlay(overlay_path: pathlib.Path, ttl_text: str, decls: list[dict],
                  profile: dict) -> tuple[bool, str, list[str]]:
    """Append, re-verify against the *saved* file, and revert on any mismatch."""
    overlay_path.parent.mkdir(parents=True, exist_ok=True)
    before = overlay_path.read_text(encoding="utf-8") if overlay_path.exists() else ""
    overlay_path.write_text(before + ttl_text, encoding="utf-8")
    try:
        g = load_graph(profile)
        added, refused, notes = check(decls, g)
        if refused:
            raise ValueError("; ".join(f"{r['name']}: {r['why']}" for r in refused))
        return True, "", notes
    except Exception as exc:                                   # noqa: BLE001
        overlay_path.write_text(before, encoding="utf-8")
        return False, f"reverted ({exc})", []


# ───────────────────────────────────────────────────────────────── a sentence in
def nl_declarations(text: str, g: Graph) -> tuple[list[dict], list[str]]:
    """Ask the model for a declaration, constrained to what the ontology already has."""
    menu = menu_of(g)
    notes: list[str] = []
    reply = _chat(_nl_prompt(text, menu))
    if reply is None:
        return [], ["no model backend: set DEEPSEEK_API_KEY (or run Ollama) — "
                    "no declaration was invented by guesswork"]
    data = _parse_json(reply)
    if not isinstance(data, dict):
        return [], [f"the model did not return JSON: {reply[:200]}"]
    decls = data.get("metrics") or ([data] if data.get("name") else [])
    if data.get("question"):
        notes.append(f"model read the sentence as: {data['question']}")
    for d in decls:
        if d.get("grain") and d["grain"] not in menu["classes"]:
            notes.append(f"{d['name']}: :grain :{d['grain']} is not a declared class")
    return [d for d in decls if isinstance(d, dict)], notes


def _nl_prompt(text: str, menu: dict) -> str:
    classes = "\n".join(
        f"  :{name}  (table {info['table']})  columns: {', '.join(info['columns']) or '(none)'}"
        for name, info in menu["classes"].items())
    metrics = "\n".join(
        f"  :{name}  aggregate={m.get('aggregate')} grain={m.get('grain')} "
        f"universe={m.get('universe')} where={m.get('where')} "
        f"numerator={m.get('numerator')} denominator={m.get('denominator')}"
        for name, m in menu["metrics"].items()) or "  (none declared yet)"
    return f"""You declare ONE metric for a semantic layer. Reply with JSON only.

The ontology's objects (classes) and their physical columns:
{classes}

Metrics already declared (a ratio may only reuse these):
{metrics}

The user said: "{text}"

Return exactly this shape and nothing else:
{{"metrics": [{{"name": "<CamelCase, unique>", "label": "<the user's words, short>",
  "aggregate": "sum|count|count_distinct|avg|min|max",
  "formula": "<row-level SQL-ish expression over that class's columns, e.g. qty*unit_price*(1-discount)>",
  "grain": "<class name from the list above>",
  "universe": "<class name from the list above, usually the same as grain>",
  "where": "<a declared axiom class, or null>",
  "numerator": "<declared metric, only for a ratio>",
  "denominator": "<declared metric, only for a ratio>",
  "scale": "100.0 for a percentage, else null",
  "groupBy": ["<dimension property, optional>"],
  "unit": "<CNY|count|…>"}}]}}

Rules you must not break:
- :grain and :universe are REQUIRED for an aggregate; a :formula column must exist on the
  grain class. Column names are the physical ones listed above.
- a ratio declares numerator/denominator over DECLARED metrics — never sum(a)/sum(b) typed
  as a formula.
- never invent a column, a class, a threshold or a "good/bad" definition: if the sentence
  cannot be answered by what is listed, return {{"metrics": []}} and put the reason in
  "question". A refusal is a valid answer.
"""


def _chat(prompt: str) -> str | None:
    """One OpenAI-compatible chat call, using the same env vars as nl.py."""
    base = (os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com/v1").rstrip("/")
    key = os.getenv("DEEPSEEK_API_KEY") or ""
    model = os.getenv("DEEPSEEK_MODEL") or "deepseek-flash"
    backend = os.getenv("NL_BACKEND", "auto").lower()
    candidates = []
    if key and backend in ("auto", "deepseek"):
        candidates.append((base + "/chat/completions", key, model))
    if backend in ("auto", "ollama"):
        candidates.append(((os.getenv("OLLAMA_BASE") or "http://127.0.0.1:11434/v1").rstrip("/")
                           + "/chat/completions", "ollama",
                           os.getenv("OLLAMA_MODEL") or "qwen3:4b"))
    for url, token, name in candidates:
        body = json.dumps({"model": name, "temperature": 0,
                           "messages": [{"role": "user", "content": prompt}]}).encode()
        req = urllib.request.Request(url, data=body, headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.load(r)
            return data["choices"][0]["message"]["content"]
        except Exception:                                     # noqa: BLE001
            continue
    return None


def _ollama_ok() -> bool:
    base = (os.getenv("OLLAMA_BASE") or "http://127.0.0.1:11434/v1").rstrip("/")
    probe = base[:-3] + "/api/tags" if base.endswith("/v1") else base + "/api/tags"
    try:
        urllib.request.urlopen(probe, timeout=1.5)
        return True
    except Exception:                                     # noqa: BLE001
        return False


def _parse_json(text: str) -> Any:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text[3:] else text.strip("`")
        text = text.removeprefix("json").strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


# ─────────────────────────────────────────────────────────────────── a file in
def file_declarations(filename: str, content: str) -> tuple[list[dict], str | None, list[str]]:
    """Parse an upload. Returns (decls, raw_ttl_or_None, notes)."""
    suffix = pathlib.Path(filename).suffix.lower()
    notes: list[str] = []
    if suffix in (".ttl", ".turtle"):
        notes.append("uploaded as Turtle — declarations are taken as written")
        return [], content, notes
    if suffix == ".json":
        data = json.loads(content)
        decls = data.get("metrics") if isinstance(data, dict) else data
        if not isinstance(decls, list):
            raise ValueError('a .json upload must be {"metrics": [...]} or a list')
        return [_norm(d) for d in decls if isinstance(d, dict)], None, notes
    if suffix == ".csv":
        rows = list(csv.DictReader(io.StringIO(content)))
        if not rows:
            raise ValueError("the .csv has no data rows")
        missing = {"name"} - set(rows[0])
        if missing:
            raise ValueError(f"the .csv needs a 'name' column (missing {sorted(missing)})")
        out = []
        for row in rows:
            d = {k: v for k, v in row.items() if v not in (None, "")}
            if "groupBy" in d:
                d["groupBy"] = [x.strip() for x in str(d["groupBy"]).split(";") if x.strip()]
            out.append(_norm(d))
        return out, None, notes
    raise ValueError(f"unsupported file type '{suffix}' — use .ttl, .json or .csv")


def _norm(d: dict) -> dict:
    out = {k: d.get(k) for k in DECL_FIELDS if k in d}
    if isinstance(out.get("groupBy"), str):
        out["groupBy"] = [x.strip() for x in out["groupBy"].split(";") if x.strip()]
    return out


# ───────────────────────────────────────────────────────────────────────── main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True, help="the app profile (settings JSON)")
    ap.add_argument("--mode", choices=("nl", "upload", "state"), default="state")
    ap.add_argument("--text", default="", help="mode=nl: the sentence")
    ap.add_argument("--file", default="", help="mode=upload: path to .ttl/.json/.csv")
    ap.add_argument("--dry-run", action="store_true", help="propose + compile, write nothing")
    ap.add_argument("--json", action="store_true", help="(always on; kept for symmetry)")
    args = ap.parse_args()

    profile_path = pathlib.Path(args.profile).resolve()
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile["_base"] = profile_path.parent          # every relative path hangs off here
    sqlgen.reconfigure(ns=profile.get("ns"),
                       ontology_dir=str(resolve(profile, "ontology_dir") or (HERE / "ontology")),
                       overlay=str(resolve(profile, "overlay") or ""),
                       drop_overlay=not profile.get("overlay"))

    result: dict[str, Any] = {"ok": False, "mode": args.mode, "added": [], "refused": [],
                              "notes": [], "overlay": "", "dry_run": args.dry_run}
    if args.mode == "state":
        # the page's read-only view: what is declared, and whether a model can parse a
        # sentence. No compile, no database, no write.
        g = load_graph(profile)
        rows = []
        from rdflib import RDFS, URIRef
        ns = profile.get("ns") or getattr(sqlgen, "NS")
        for name, m in sorted(sqlgen.metrics(g).items()):
            lab = next(iter(g.objects(URIRef(f"{ns}{name}"), RDFS.label)), None)
            rows.append({"name": name, "label": str(lab) if lab is not None else None,
                         "aggregate": m.aggregate, "grain": m.grain, "universe": m.universe,
                         "where": m.where, "numerator": m.numerator,
                         "denominator": m.denominator, "groupBy": m.group_by,
                         "missing": m.missing})
        backend = os.getenv("NL_BACKEND", "auto").lower()
        key = bool(os.getenv("DEEPSEEK_API_KEY"))
        ollama = _ollama_ok()
        if backend == "fallback" or (backend == "deepseek" and not key) or \
                (backend == "ollama" and not ollama) or (backend == "auto" and not (key or ollama)):
            nl_backend = "none"
        elif backend in ("auto", "deepseek") and key:
            nl_backend = f"deepseek:{(os.getenv('DEEPSEEK_MODEL') or 'deepseek-flash')}"
        else:
            nl_backend = f"ollama:{(os.getenv('OLLAMA_MODEL') or 'qwen3:4b')}"
        print(json.dumps({"ok": True, "metrics": rows,
                          "overlay": str(resolve(profile, "overlay") or ""),
                          "nl_backend": nl_backend}, ensure_ascii=False))
        return 0
    try:
        g = load_graph(profile)
        ttl = None
        if args.mode == "nl":
            if not args.text.strip():
                raise ValueError("--text is required for mode=nl")
            decls, notes = nl_declarations(args.text, g)
            result["notes"].extend(notes)
        else:
            content = pathlib.Path(args.file).read_text(encoding="utf-8")
            decls, ttl, notes = file_declarations(pathlib.Path(args.file).name, content)
            result["notes"].extend(notes)

        if not decls and ttl is None:
            result["ok"] = False
            result["refused"].append({"name": "(nothing)", "why": "no declaration to import"})
            print(json.dumps(result, ensure_ascii=False))
            return 1

        ns = profile.get("ns") or getattr(sqlgen, "NS")
        if ttl is None:
            ttl = render_ttl(decls, ns)
        # dry run first: the candidate graph, never the file
        g2 = load_graph(profile, extra_ttl=ttl)
        added, refused, check_notes = check(decls or _decls_from_graph(g2, ttl), g2)
        result["added"], result["refused"] = added, refused
        result["notes"].extend(check_notes)
        result["overlay"] = str(resolve(profile, "overlay") or "")

        if refused or not added:
            print(json.dumps(result, ensure_ascii=False))
            return 1

        if args.dry_run:
            result["ok"] = True
            print(json.dumps(result, ensure_ascii=False))
            return 0

        overlay = pathlib.Path(result["overlay"])
        ok, log, notes = apply_overlay(overlay, ttl, decls or _decls_from_graph(g2, ttl), profile)
        result["ok"] = ok
        if not ok:
            result["refused"].append({"name": "(write)", "why": log})
        result["notes"].extend(notes)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if ok else 1
    except Exception as exc:                                   # noqa: BLE001
        result["refused"].append({"name": "(import)", "why": f"{type(exc).__name__}: {exc}"})
        print(json.dumps(result, ensure_ascii=False))
        return 1


def _decls_from_graph(g: Graph, ttl: str) -> list[dict]:
    """For a raw .ttl upload: the subjects it introduces, as declarations."""
    names = set()
    for line in ttl.splitlines():
        line = line.strip()
        if line.startswith("<") and "owl:DatatypeProperty" in line:
            names.add(line[1:line.index(">")].split("#")[-1])
        elif line.startswith(":") and "owl:DatatypeProperty" in line:
            names.add(line[1:].split()[0])
    out = []
    for name in sorted(names):
        m = sqlgen.metrics(g).get(name)
        out.append({"name": name, "label": None, "aggregate": getattr(m, "aggregate", None)})
    return out


if __name__ == "__main__":
    sys.exit(main())

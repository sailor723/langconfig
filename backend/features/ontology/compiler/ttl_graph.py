"""ttl_graph — draw the ontology. Reads the TTL, writes a picture. No store, no server.

Why this file and not Neo4j: the merged ontology is 660 triples / ~78 nodes. A property
graph database would add a container and a second copy of the model to keep in sync, to
draw something `dot` draws in under a second. The TTL stays the only source.

What the picture says, and what it deliberately cannot say:

  · a PHYSICAL class is a box with its table (`:physicalTable`)      — structure
  · a DEFINED class is a grey box carrying the predicate its axiom   — meaning, compiled
    compiles to (`c_acctbal >= 5000.0`), or the reason it refuses      from the axiom
  · a METRIC is an ellipse joined to the class it measures, labelled
    with the declaration it is built from and the reason it cannot
    compile when it cannot (6 of 10 today — the debt, made visible)
  · an object property is a class-to-class edge named after the key   — the joins

Neo4j, n10s, RDFLib's own RDF->LPG and every other importer would turn each axiom into
anonymous blank nodes (6 here) — i.e. the picture would keep the shape and lose the
decisions. Flattening is the whole point: `5000` must be readable in the box.

Usage:
    /Users/weiping/dev/Learn/cube/tutorial/.venv/bin/python sql-first/ttl_graph.py
    ... --out sql-first/ontology.svg   (SVG by default; --format png for a raster)
"""
from __future__ import annotations

import argparse
import pathlib
import re
import shutil
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import sqlgen
from rdflib import OWL, RDF, RDFS, BNode

# Anonymous owl:Class nodes (measured: 6) are the inner half of the axioms — the
# owl:Restriction and the rdfs:Datatype facet. They are NOT drawn: their whole content is
# the predicate the box shows (`c_acctbal >= 5000.0`). Drawing them is what an importer
# does, and it is how the decision disappears into a blank circle.
def collect(graph) -> dict:
    """Turn the graph into the three things a reader needs: classes, edges, metrics."""
    everything = list(graph.subjects(RDF.type, OWL.Class))
    classes = [c for c in everything if not isinstance(c, BNode)]
    anonymous = len(everything) - len(classes)

    physical, defined, unexplained = [], [], []
    for cls in classes:
        name = sqlgen._local(cls)
        table = sqlgen._one(graph, cls, sqlgen.P("physicalTable"))
        label = sqlgen._one(graph, cls, RDFS.label) or name
        # A DEFINITION that names its own table is still a definition. Measured on new_coldchain:
        # :JudgedComplaint / :UnjudgedComplaint / :UnrecordedRefusalReason carry BOTH a
        # :physicalPredicate and a :physicalTable (C1b needs the table, because a predicate-only
        # definition has nothing else to say which table it counts), so `if table` filed them as
        # structure. The page then claimed "18/21 classes list their properties" and red-flagged a
        # correct ontology: a defined set has no properties of its own to list, by construction.
        # So the definition test comes FIRST, and the table only decides `physical` when there is
        # no definition to compile.
        has_def = ((cls, OWL.equivalentClass, None) in graph
                   or sqlgen._one(graph, cls, sqlgen.P("physicalPredicate")))
        if table and not has_def:
            # Every modelled column, in both shapes the ontology uses: a value column is an
            # owl:DatatypeProperty, a foreign key is an owl:ObjectProperty (l_orderkey).
            # Metrics are excluded on purpose — they carry :formula/:aggregate and are not
            # stored anywhere, so they are not columns of this table.
            columns = sorted({
                col for kind in (OWL.DatatypeProperty, OWL.ObjectProperty)
                for prop in graph.subjects(RDF.type, kind)
                if (prop, RDFS.domain, cls) in graph
                for raw in [sqlgen._one(graph, prop, sqlgen.P("physicalColumn"))]
                if raw and not sqlgen._one(graph, prop, sqlgen.P("formula"))
                and not sqlgen._one(graph, prop, sqlgen.P("aggregate"))
                for col in [c.strip() for c in raw.split(",") if c.strip()]})
            physical.append(dict(name=name, label=label, table=table, columns=columns,
                                 column_count=sqlgen._one(graph, cls, sqlgen.P("columnCount"))))
        elif (cls, OWL.equivalentClass, None) in graph:
            try:
                predicate = sqlgen.concept_sql(graph, name)
                notes = None
            except sqlgen.Refusal as exc:
                predicate, notes = None, "refused: " + short(exc)
            defined.append(dict(name=name, label=label, defined_by=predicate, note=notes,
                                table=table, via="equivalentClass"))
        else:
            # :LateLine is the one class defined by a `:physicalPredicate` instead of an
            # axiom — OWL cannot say "this line shipped after its own promise date",
            # because that compares two properties of one individual. It IS defined; an
            # earlier version of this file called it "unexplained", which was wrong.
            predicate = sqlgen._one(graph, cls, sqlgen.P("physicalPredicate"))
            if predicate:
                defined.append(dict(name=name, label=label, defined_by=predicate,
                                    table=table, via="physicalPredicate",
                                    note="declared as :physicalPredicate — OWL cannot say this"))
            else:
                unexplained.append(dict(name=name, label=label))

    # object properties -> class-to-class edges (the joins). A link with no domain is a
    # derived path, and is reported rather than drawn to nowhere.
    links, derived, incomplete = [], [], []
    for prop in graph.subjects(RDF.type, OWL.ObjectProperty):
        name = sqlgen._local(prop)
        dom = sqlgen._local(next(iter(graph.objects(prop, RDFS.domain)), None))
        rng = sqlgen._local(next(iter(graph.objects(prop, RDFS.range)), None))
        column = sqlgen._one(graph, prop, sqlgen.P("physicalColumn"))
        known = {c["name"] for c in physical + defined + unexplained}
        if not dom:
            # no :domain declared — but a property chain says where it starts, so the edge
            # exists even if the ontology will not name its source. `customerRegion` is the
            # one case: Customer -> Nation -> Region.
            chain = (next(iter(graph.objects(prop, OWL.propertyChainAxiom)), None)
                     or next(iter(graph.objects(prop, sqlgen.P("propertyChainAxiom"))), None))
            hops = [sqlgen._local(m) for m in graph.items(chain)] if chain else []
            start = (sqlgen._local(next(iter(graph.objects(sqlgen.P(hops[0]), RDFS.domain)), None))
                     if hops else None)
            if start and rng in known:
                derived.append(dict(name=name, src=start, dst=rng, column=None, via=hops))
            else:
                derived.append(dict(name=name, src=None, dst=rng, column=None, via=hops))
        elif dom in known and rng in known:
            links.append(dict(name=name, src=dom, dst=rng, column=column))
        else:
            incomplete.append(name)

    metrics, refused = [], []
    for name, m in sqlgen.metrics(graph).items():
        try:
            compiled = sqlgen.compile_metric(graph, name)
            line = f":aggregate {m.aggregate} · {m.formula or 'concept'}"
            metrics.append(dict(name=name, domain=m.domain, line=line, sql=compiled.sql))
        except sqlgen.Refusal as exc:
            refused.append(dict(name=name, domain=m.domain, line="refused: " + short(exc)))

    subclasses = [(sqlgen._local(a), sqlgen._local(b))
                  for a, b in graph.subject_objects(RDFS.subClassOf)
                  if a in classes and b in classes]
    return dict(physical=physical, defined=defined, unexplained=unexplained,
                links=links, metrics=metrics, refused=refused,
                anonymous=anonymous, derived=derived, incomplete=incomplete,
                subclasses=subclasses)


def short(text: str, limit: int = 44) -> str:
    """A refusal, cut to fit a box — the ellipsis is there so a cut is visible, not implied."""
    text = str(text).split(" — ")[0].split("; ")[0].strip()
    if "declares no" in text:            # "property :x on :x declares no :column" -> the cause
        text = text[text.index("declares no"):]
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def esc(text: str) -> str:
    return str(text).replace("\\", "\\\\").replace('"', '\\"')


def esc_label(text: str) -> str:
    """Quotes get escaped, `\\n` does not — it is the line break Graphviz should honour."""
    return str(text).replace('"', '\\"')


COLUMN_LIMIT = 8      # a box that lists 15 columns stops being a box


def box_label(c: dict) -> str:
    """A class box: the business label, the table, then the raw property names.

    The columns are the point — a reader looking at `Region` should see `r_name` and
    `r_regionkey` without clicking, and know that `:columnCount 3` counts one column this
    picture does not model (`r_comment`, excluded in the TTL).
    """
    count = c.get("column_count")
    stored = f'{len(c.get("columns") or [])}/{count} columns' if count else len(c.get("columns") or [])
    lines = [c["label"], f'{c["table"]} · {stored}' if count else c["table"]]
    columns = c.get("columns") or []
    lines += columns[:COLUMN_LIMIT]
    if len(columns) > COLUMN_LIMIT:
        lines.append(f"+{len(columns) - COLUMN_LIMIT} more")
    return "\\n".join(lines)


def to_dot(shape: dict, title: str) -> str:
    out = [
        "digraph ontology {",
        '  graph [rankdir=LR, splines=true, overlap=false, nodesep=0.34, ranksep=0.9,',
        f'         fontname=Helvetica, label="{esc(title)}", labelloc=t, fontsize=13];',
        "  node [fontname=Helvetica, fontsize=9, shape=box, style=solid, penwidth=1];",
        "  edge [fontname=Helvetica, fontsize=8, color=\"#666666\"];",
        "",
        '  subgraph cluster_structure { label="Classes — a declared table"; fontsize=10; '
        'color="#cccccc"; style=dashed;',
    ]
    for c in shape["physical"]:
        out.append(f'    "{c["name"]}" [label="{esc_label(box_label(c))}", fillcolor=white, style=filled];')
    out += ['  }', '',
            '  subgraph cluster_meaning { label="Defined classes — an axiom, compiled"; fontsize=10; '
            'color="#cccccc"; style=dashed;']
    for c in shape["defined"] + shape["unexplained"]:
        body = c.get("defined_by") or c.get("note") or "no axiom"
        fill = "#f0f0f0" if c.get("defined_by") else "#fff4e5"
        out.append(f'    "{c["name"]}" [label="{esc(c["label"])}\\n{esc(body)}", shape=box, '
                   f'fillcolor="{fill}", style=filled];')
    out += ['  }', '',
            '  subgraph cluster_metrics { label="Datatype Properties — what sqlgen compiles"; fontsize=10; '
            'color="#cccccc"; style=dashed;']
    for m in shape["metrics"]:
        out.append(f'    "m_{m["name"]}" [label="{m["name"]}\\n{esc(m["line"])}", shape=ellipse];')
    for m in shape["refused"]:
        out.append(f'    "m_{m["name"]}" [label="{m["name"]}\\n{esc(m["line"])}", shape=ellipse, '
                   f'fillcolor="#ffe0e0", style=filled];')
    out += ['  }', '']
    for link in shape["links"] + shape["derived"]:
        if not link.get("src"):
            continue
        derived = "" if link["column"] else " (derived)"
        style = "" if link["column"] else ', style=dashed'
        out.append(f'  "{link["src"]}" -> "{link["dst"]}" '
                   f'[label="{esc(link["name"] + derived)}"{style}];')
    for parent, child in shape["subclasses"]:
        out.append(f'  "{child}" -> "{parent}" [label="subClassOf", style=dotted];')
    for m in shape["metrics"] + shape["refused"]:
        if m["domain"]:
            out.append(f'  "m_{m["name"]}" -> "{m["domain"]}" [style=dashed, arrowhead=none, '
                       f'color="#999999"];')
    out.append("}")
    return "\n".join(out) + "\n"


def verify(path: pathlib.Path, shape: dict) -> tuple[int, int, int, int]:
    """The picture is a claim, so it gets counted: what landed in the SVG versus the shape
    that was just collected. A render that silently drops a node must not pass."""
    text = path.read_text()
    nodes = len(re.findall(r'class="node"', text))
    edges = len(re.findall(r'class="edge"', text))
    want_nodes = (len(shape["physical"]) + len(shape["defined"]) + len(shape["unexplained"])
                  + len(shape["metrics"]) + len(shape["refused"]))
    want_edges = (len(shape["links"]) + len([d for d in shape["derived"] if d.get("src")])
                  + len(shape["subclasses"])
                  + sum(1 for m in shape["metrics"] + shape["refused"] if m["domain"]))
    return nodes, edges, want_nodes, want_edges


def main() -> int:
    ap = argparse.ArgumentParser()
    here = pathlib.Path(__file__).parent
    ap.add_argument("--out", default=str(here / "ontology.svg"))
    ap.add_argument("--format", default="svg", choices=["svg", "png"])
    ap.add_argument("--keep-dot", action="store_true", help="also keep the .dot source")
    args = ap.parse_args()

    graph = sqlgen.load()
    shape = collect(graph)
    source = here / "ontology.dot"
    source.write_text(to_dot(shape, "Retail ontology, drawn from the TTL"))

    dot = shutil.which("dot")
    if dot is None:
        print("graphviz `dot` not found — wrote ontology.dot instead; "
              "brew install graphviz to render", file=sys.stderr)
        return 1
    out = pathlib.Path(args.out)
    subprocess.run([dot, f"-T{args.format}", str(source), "-o", str(out)], check=True)
    if not args.keep_dot:
        source.unlink()

    print(f"== drew {out.name} from {len(graph)} triples\n")
    print(f"  physical classes   {len(shape['physical']):>3}   (box + table)")
    print(f"  defined classes    {len(shape['defined']):>3}   "
          f"{sum(1 for c in shape['defined'] if c['defined_by'])} with a compiled predicate, "
          f"{sum(1 for c in shape['defined'] if not c['defined_by'])} refused")
    print(f"  unexplained        {len(shape['unexplained']):>3}   "
          f"{[c['name'] for c in shape['unexplained']]}")
    print(f"  object links       {len(shape['links']) + len(shape['derived']):>3}   "
          f"{len(shape['derived'])} derived (property chain, no physical column)")
    print(f"  subClassOf edges   {len(shape['subclasses']):>3}   (this is why it is not a tree)")
    print(f"  metrics            {len(shape['metrics']):>3} compiled, {len(shape['refused'])} refused")
    print(f"  anonymous class exprs  {shape['anonymous']:>2}   folded into their parent box, not drawn")
    for link in shape["derived"]:
        if not link.get("src"):
            print(f"  note: link :{link['name']} has no :domain and no chain — not drawn")
    for name in shape["incomplete"]:
        print(f"  note: link :{name} points at a class this file did not parse")

    if args.format == "svg":
        nodes, edges, want_nodes, want_edges = verify(out, shape)
        ok = (nodes, edges) == (want_nodes, want_edges)
        print(f"\n  gate: {nodes}/{want_nodes} nodes, {edges}/{want_edges} edges — "
              f"{'PASS' if ok else 'FAIL (the picture is missing something)'}")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""graph_view — one page that is both the picture and the documentation.

`ttl_graph.py` writes a static SVG for git. `pylode` writes a documentation page. This
writes a single self-contained HTML that does both jobs, because they answer one question
from two sides:

    the index (left)    every entity, like a documentation table of contents
    the graph (middle)  the same entities as a graph — Graphviz's layout, read back
                        through `-Tplain`, so pan/drag/zoom are all the JS does
    the panel (right)   the entity's documentation, generated from the TTL the moment you
                        click: every annotation it carries, the axiom it compiles to,
                        the SQL that compiles to, and the number that SQL returns now

Where this beats each half:

  · pyLODE renders `Equivalent Class` as `Customer ⊓ c_acctbal some n3554b64d…` — measured:
    `5000.0` appears 0 times in its 261 KB output, because a blank node has no rendering.
    Here the axiom is flattened to `c_acctbal >= 5000.0` and then run.
  · the static SVG has the flattened predicate but no annotations, no SQL, no numbers, and
    it cannot be clicked.
  · neither Protégé (stops at the schema) nor Palantir's Ontology Manager (stops at its
    JSON schema) shows a declaration and its rows on one screen.

Usage:
    /Users/weiping/dev/Learn/cube/tutorial/.venv/bin/python sql-first/graph_view.py
    ... --open        (also launch it in your browser)
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import sqlgen
import ttl_graph
from rdflib import OWL, RDF, RDFS, BNode

HERE = pathlib.Path(__file__).parent
OVERLAY = HERE / "metrics_ext.ttl"
DOC = HERE / "ontology-doc.html"
DSN = dict(host="127.0.0.1", port=15432, dbname="retail_db", user="postgres", password="postgres")


def parse_dsn(text: str) -> dict:
    """'host=127.0.0.1 port=15432 dbname=retail_db user=postgres password=postgres' -> dict"""
    out = {}
    for part in text.replace(";", " ").split():
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = int(v) if k.strip() == "port" else v
    if "dbname" not in out:
        raise SystemExit("--dsn must include dbname")
    out.setdefault("host", "127.0.0.1")
    out.setdefault("port", 5432)
    out.setdefault("user", "postgres")
    out.setdefault("password", "")
    return out

# Predicates that describe the model's shape rather than the term's meaning.
STRUCTURAL = {"type", "domain", "range", "subClassOf", "inverseOf", "propertyChainAxiom",
              "equivalentClass", "intersectionOf", "onProperty", "someValuesFrom",
              "withRestrictions", "onDatatype", "minInclusive", "minExclusive", "hasValue",
              "first", "rest", "label"}
# Not standard OWL, so nothing renders them automatically — a gloss keeps the panel read-
# able without inventing a vocabulary.
PREFIXES = {"http://www.w3.org/1999/02/22-rdf-syntax-ns#": "rdf",
            "http://www.w3.org/2000/01/rdf-schema#": "rdfs",
            "http://www.w3.org/2002/07/owl#": "owl",
            "http://www.w3.org/2001/XMLSchema#": "xsd"}
GLOSS = {
    "domain": "域 —— 这个属性属于哪个类", "range": "值域",
    "subClassOf": "子类于", "inverseOf": "互逆于",
    "equivalentClass": "等价类", "propertyChainAxiom": "属性链",
    "physicalTable": "物理表", "physicalColumn": "物理列",
    "physicalPredicate": "手写谓词", "primaryKey": "主键",
    "columnCount": "列数", "sqlType": "SQL 类型", "referencesColumn": "引用的列",
    "businessAlias": "业务别名", "businessDescription": "业务描述",
    "thresholdSource": "阈值来源", "formulaSource": "公式来源",
    "additivity": "可加性", "formula": "公式", "unit": "单位",
    "aggregate": "聚合", "grain": "粒度", "universe": "范围",
    "concept": "概念", "counts": "计数", "memberAlias": "成员别名（迁移遗留）",
    "labelProperty": "标签属性", "pendingModelling": "待建模",
}


def ttl_files() -> list[pathlib.Path]:
    """Every file this page documents: the overlay if this profile has one, then the ontology dir.

    The overlay is OPTIONAL — a profile may declare no computation layer at all (abc does not), and the
    generator used to crash on it with `FileNotFoundError: …/compiler/metrics_ext.ttl`, because the
    default overlay path was unconditionally put in the list.
    """
    files = sorted(sqlgen.CUBE.glob("*.ttl"))
    if OVERLAY and pathlib.Path(OVERLAY).is_file():
        files = [pathlib.Path(OVERLAY)] + files
    return files


def block_at(lines: list[str], start: int, limit: int = 20) -> str:
    """The statement beginning at `start`. It ends at the first blank line or the next
    subject: the blank line matters, because the comment block above the NEXT statement
    would otherwise be quoted as part of this one."""
    out = [lines[start]]
    for line in lines[start + 1 : start + limit]:
        if not line.strip() or re.match(r"^:\S", line):
            break
        out.append(line)
    return "\n".join(out)


def snippets(graph, name: str) -> dict:
    """Every piece of raw TTL that concerns `:name`, in three groups.

    `self`     the statements whose subject is this term
    `related`  the statements that *name* it — a property whose :domain or :range is this
               class. Without these, `Region`'s page would never show `:n_regionkey`, the
               very line that puts the arrow into the graph.
    `comments` comment lines that mention the term. RDF has no comment syntax, so this
               knowledge is invisible to a reasoner and dies when Protégé saves the file —
               which is exactly why it is worth showing.
    """
    self_blocks = []
    for path in ttl_files():
        lines = path.read_text().splitlines()
        for i, line in enumerate(lines):
            if re.match(rf"^:{re.escape(name)}\b", line):
                self_blocks.append(dict(file=path.name, line=i + 1, text=block_at(lines, i)))
                break

    node = sqlgen.P(name)
    related = []
    for relation, predicate in (("domain", RDFS.domain), ("range", RDFS.range)):
        for prop in graph.subjects(predicate, node):
            prop_name = _local_name(prop)
            for path in ttl_files():
                lines = path.read_text().splitlines()
                for i, line in enumerate(lines):
                    if re.match(rf"^:{re.escape(prop_name)}\b", line):
                        related.append(dict(file=path.name, line=i + 1, rel=relation,
                                            prop=prop_name, text=block_at(lines, i)))
                        break

    comments = []
    for path in ttl_files():
        for i, line in enumerate(path.read_text().splitlines()):
            if line.lstrip().startswith("#") and re.search(rf":{re.escape(name)}\b", line):
                comments.append(dict(file=path.name, line=i + 1, text=line.strip()))

    self_blocks.sort(key=lambda h: (h["file"] != OVERLAY.name, h["file"]))
    return dict(self=self_blocks[:3], related=related, comments=comments[:6])


def _values(graph, subject, predicate) -> list[str]:
    """Render every object of one predicate as a string, the way a reader wants it."""
    out = []
    for value in graph.objects(subject, predicate):
        if isinstance(value, BNode):
            continue
        text = str(value)
        if text.startswith(sqlgen.NS):
            out.append(":" + text.split("#")[-1])
        elif text.startswith(("http://", "https://")):
            out.append(text)
        else:
            out.append(text)                          # a literal: keep it verbatim
    return out


def _qname(iri) -> str:
    """`rdfs:domain` rather than a 44-character URL in a table cell."""
    text = str(iri)
    for base, prefix in PREFIXES.items():
        if text.startswith(base):
            return f"{prefix}:{text[len(base):]}"
    return text


def _local_name(iri) -> str:
    text = str(iri)
    return text.split("#")[-1] if "#" in text else text.rsplit("/", 1)[-1]


def terms(graph, subject) -> tuple[list[dict], list[dict]]:
    """Everything the TTL says about one term, split into shape and meaning.

    `graph.predicates()` yields one hit per triple, so it repeats a predicate that has
    several objects; dedupe first, or every multi-valued annotation (aliases) is listed
    twice. `rdf:type`/`rdfs:label`/`rdfs:comment` are skipped: the panel uses them for the
    heading and the description, and repeating them as rows with full IRIs is noise.
    """
    structural, annotations = [], []
    for predicate in dict.fromkeys(graph.predicates(subject)):
        key = _local_name(predicate)
        if key in ("type", "label", "comment"):
            continue
        values = _values(graph, subject, predicate)
        if not values:
            continue
        external = "" if str(predicate).startswith(sqlgen.NS) else _qname(predicate)
        row = dict(k=key, label=GLOSS.get(key, key), v=values, iri=external)
        (structural if key in STRUCTURAL else annotations).append(row)
    annotations.sort(key=lambda r: r["k"])
    structural.sort(key=lambda r: r["k"])
    return structural, annotations


def base_table(graph, concept: str) -> str | None:
    """The class an axiom restricts: first named class in its owl:intersectionOf."""
    for axiom in graph.objects(sqlgen.P(concept), OWL.equivalentClass):
        for lst in graph.objects(axiom, OWL.intersectionOf):
            for member in graph.items(lst):
                if (member, RDF.type, OWL.Class) in graph and str(member).startswith(sqlgen.NS):
                    table = sqlgen._one(graph, member, sqlgen.P("physicalTable"))
                    if table:
                        return table
    return None


def table_for(graph, cls: str) -> str | None:
    """A class's own table, or its parent's when it is a subclass (LateLine -> lineitem)."""
    node = sqlgen.P(cls)
    own = sqlgen._one(graph, node, sqlgen.P("physicalTable"))
    if own:
        return own
    for parent in graph.objects(node, RDFS.subClassOf):
        found = sqlgen._one(graph, parent, sqlgen.P("physicalTable"))
        if found:
            return found
    return None


def class_members(graph, name: str) -> tuple[list[dict], list[dict]]:
    """The object and datatype properties whose domain / range is this class.

    pyLODE calls these "In Domain Of" and "In Range Of"; without them a class panel showed
    a `:columnCount 8` and no sign of the eight columns — the documentation page was more
    complete than this one, which is the wrong way round.
    """
    node = sqlgen.P(name)
    out, into = [], []
    for prop in sorted(graph.subjects(RDFS.domain, node), key=_local_name):
        kind = ("object" if (prop, RDF.type, OWL.ObjectProperty) in graph else
                "datatype" if (prop, RDF.type, OWL.DatatypeProperty) in graph else None)
        if kind is None:
            continue
        row = dict(n=_local_name(prop), kind=kind,
                   col=sqlgen._one(graph, prop, sqlgen.P("physicalColumn")),
                   sqlType=sqlgen._one(graph, prop, sqlgen.P("sqlType")),
                   unit=sqlgen._one(graph, prop, sqlgen.P("unit")),
                   additivity=sqlgen._one(graph, prop, sqlgen.P("additivity")),
                   formula=sqlgen._one(graph, prop, sqlgen.P("formula")),
                   aggregate=sqlgen._one(graph, prop, sqlgen.P("aggregate")))
        if kind == "object":
            row["to"] = sqlgen._local(next(iter(graph.objects(prop, RDFS.range)), None))
            row["refs"] = sqlgen._one(graph, prop, sqlgen.P("referencesColumn"))
        out.append(row)
    for prop in sorted(graph.subjects(RDFS.range, node), key=_local_name):
        if (prop, RDF.type, OWL.ObjectProperty) not in graph:
            continue
        # a derived link states no :domain, but its chain does: the first hop's domain is
        # where the two-hop path actually starts (c_nationkey is a property of Customer).
        chain_list = (next(iter(graph.objects(prop, OWL.propertyChainAxiom)), None)
                      or next(iter(graph.objects(prop, sqlgen.P("propertyChainAxiom"))), None))
        hops = [_local_name(member) for member in graph.items(chain_list)] if chain_list else []
        head = sqlgen.P(hops[0]) if hops else None
        into.append(dict(n=_local_name(prop), chain=hops,
                         chain_start=(sqlgen._local(next(iter(graph.objects(head, RDFS.domain)), None))
                                      if head is not None else None),
                         **{"from": sqlgen._local(next(iter(graph.objects(prop, RDFS.domain)), None))}))
    out.sort(key=lambda r: (r["kind"] != "object", r["n"]))
    return out, into


SAMPLE = 20   # list the individuals themselves only when the extension is small
              # (override with --sample; `region` has 5, `nation` has 25, `orders` 150,000)


def base_class(graph, concept: str) -> str | None:
    """The named class an axiom restricts (HighBalanceCustomer -> Customer)."""
    for axiom in graph.objects(sqlgen.P(concept), OWL.equivalentClass):
        for lst in graph.objects(axiom, OWL.intersectionOf):
            for member in graph.items(lst):
                if (member, RDF.type, OWL.Class) in graph and str(member).startswith(sqlgen.NS):
                    return sqlgen._local(member)
    return None


def label_columns(graph, cls: str) -> tuple[list[str], str]:
    """Which column(s) show one individual of this class, and by what rule.

    Order, and it is reported in the panel so a reader can disagree with it:
      1. a declared `:labelProperty`        (Nation -> n_name, the only one declared)
      2. a column ending in `_name`         (r_name, c_name, p_name ...)
      3. a bare name-ish column             (customers.name -> "Dana Okafor", not "1")
      4. the primary key                    (orders -> o_orderkey, partsupp -> two columns)
    """
    node = sqlgen.P(cls)
    label = sqlgen._one(graph, node, sqlgen.P("labelProperty"))
    if label:
        column = sqlgen._one(graph, sqlgen.P(label), sqlgen.P("physicalColumn"))
        if column:
            return [column], f":labelProperty :{label}"
    for _, column in sorted(sqlgen.class_columns(graph, cls).items()):
        if column.endswith("_name"):
            return [column], "name column"
    for _, column in sorted(sqlgen.class_columns(graph, cls).items()):
        if column in ("name", "label", "title"):
            return [column], "name column"
    primary = sqlgen._one(graph, node, sqlgen.P("primaryKey")) or ""
    parts = [c.strip() for c in primary.split(",") if c.strip()]
    if parts:
        return parts, ":primaryKey"
    parent = base_class(graph, cls)
    return label_columns(graph, parent) if parent else ([], "none")


def id_order_columns(graph, cls: str, fallback: list[str]) -> list[str]:
    """ORDER BY the primary key: objects read 1,2,3 (not alphabetically by name).

    The sample and the object-details query share this list, so rows and objects stay
    aligned row-for-row.
    """
    pk = sqlgen._one(graph, sqlgen.P(cls), sqlgen.P("primaryKey"))
    if not pk:
        parent = base_class(graph, cls)
        pk = sqlgen._one(graph, sqlgen.P(parent), sqlgen.P("primaryKey")) if parent else None
    parts = [c.strip() for c in (pk or "").split(",") if c.strip()]
    return parts or fallback


def measured(graph, shape: dict, sample_limit: int = SAMPLE) -> dict:
    """Run the compiled SQL so the panel can show rows, not just hope."""
    out = {"metrics": {}, "concepts": {}, "individuals": {}, "note": None}
    try:
        import psycopg2
    except ImportError:
        out["note"] = "psycopg2 not importable — numbers omitted, SQL still shown"
        return out
    try:
        db = psycopg2.connect(**DSN, connect_timeout=3)
    except Exception as exc:  # noqa: BLE001 — the view must open without a database
        out["note"] = f"Postgres unavailable ({str(exc).splitlines()[0][:60]}) — numbers omitted"
        return out
    with db, db.cursor() as cur:
        for name in [m["name"] for m in shape["metrics"] + shape["refused"]]:
            try:
                sql = sqlgen.compile_metric(graph, name).sql
            except sqlgen.Refusal:
                continue
            try:
                cur.execute(sql)
                if " GROUP BY " in sql:
                    rows = cur.fetchall()
                    value = " · ".join(
                        f"{' / '.join(str(x) for x in r[:-1])}={r[-1]}" for r in rows[:4])
                else:
                    value = cur.fetchone()[0]
                out["metrics"][name] = {"sql": sql, "value": value}
            except Exception as exc:  # noqa: BLE001
                out["metrics"][name] = {"sql": sql, "error": str(exc).splitlines()[0][:90]}
        # every class, plain or defined: how many individuals, and their names if few
        for item in ([dict(name=c["name"], defined_by=None) for c in shape["physical"]]
                     + [c for c in shape["defined"] if c["defined_by"]]):
            cls = item["name"]
            table = table_for(graph, cls) or base_table(graph, cls)
            if not table:
                continue
            try:
                predicate = sqlgen.concept_sql(graph, cls)
            except sqlgen.Refusal:
                predicate = item["defined_by"]        # a :physicalPredicate is already SQL
            where = f" WHERE {predicate}" if predicate else ""
            sql = f"SELECT count(*) FROM {table}{where};"
            try:
                cur.execute(sql)
                total = cur.fetchone()[0]
            except Exception:  # noqa: BLE001
                continue
            columns, rule = label_columns(graph, cls)
            order = id_order_columns(graph, cls, columns)
            sample = None
            objects = None
            if total and total <= sample_limit and columns:
                list_sql = (f"SELECT {', '.join(columns)} FROM {table}{where} "
                            f"ORDER BY {', '.join(order)};")
                try:
                    cur.execute(list_sql)
                    sample = dict(cols=columns, rule=rule, sql=list_sql,
                                  rows=[[str(v) for v in row] for row in cur.fetchall()])
                except Exception:  # noqa: BLE001
                    sample = None
            if sample:
                objects = object_details(graph, shape, item, table, where, order, cur)
            out["individuals"][cls] = dict(value=total, sql=sql, rule=rule,
                                           cols=columns, sample=sample, objects=objects)
            if predicate:
                out["concepts"][cls] = {"sql": sql, "value": total}
    db.close()
    return out


def object_details(graph, shape: dict, item: dict, table: str, where: str,
                   order: list[str], cur) -> list[dict] | None:
    """One entry per sampled object: every column of its row + the defined classes it satisfies.

    The class membership is not stored anywhere: it is the compiled definition evaluated
    per row (`is:PremiumCustomer` = the same WHERE predicate the class itself uses), which
    is why the panel can say *why* an object is in a class instead of just listing it.
    """
    defined_here: list[tuple[str, str]] = []
    if item.get("defined_by") is None:            # physical class: which definitions apply?
        for d in shape["defined"]:
            if not d.get("defined_by"):
                continue
            d_table = base_table(graph, d["name"]) or table_for(graph, d["name"])
            if d_table != table:
                continue
            try:
                pred = sqlgen.concept_sql(graph, d["name"])
            except sqlgen.Refusal:
                continue
            defined_here.append((d["name"], pred.rstrip(";").strip()))

    select = "*" + "".join(f', ({pred}) AS "is:{name}"' for name, pred in defined_here)
    detail_sql = (f"SELECT {select} FROM {table}{where} "
                  f"ORDER BY {', '.join(order)};")
    try:
        cur.execute(detail_sql)
        desc = [d[0] for d in cur.description]
        rows = cur.fetchall()
    except Exception:  # noqa: BLE001
        return None

    out = []
    for row in rows:
        props = [[col, str(val)] for col, val in zip(desc, row) if not col.startswith("is:")]
        classes = [col[3:] for col, val in zip(desc, row)
                   if col.startswith("is:") and val is True]
        out.append({"props": props, "classes": classes})
    return out or None


def layout(dot_source: str) -> dict:
    """Graphviz's positions, read back: `-Tplain` is the cheapest good layout engine."""
    proc = subprocess.run([shutil.which("dot"), "-Tplain"], input=dot_source,
                          capture_output=True, text=True, check=True)
    nodes, width, height = {}, 1.0, 1.0
    for line in proc.stdout.splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "graph":
            width, height = float(parts[2]), float(parts[3])
        elif parts[0] == "node" and len(parts) >= 6:
            nodes[parts[1]] = dict(x=float(parts[2]), y=float(parts[3]),
                                   w=float(parts[4]), h=float(parts[5]))
    return dict(nodes=nodes, width=width, height=height)


def build_payload(sample_limit: int = SAMPLE) -> dict:
    graph = sqlgen.load()
    shape = ttl_graph.collect(graph)
    facts = measured(graph, shape, sample_limit)
    lay = layout(ttl_graph.to_dot(shape, "Retail ontology"))

    nodes, edges = [], []
    for cls in shape["physical"]:
        subject = sqlgen.P(cls["name"])
        structural, annotations = terms(graph, subject)
        members, incoming = class_members(graph, cls["name"])
        indiv = facts["individuals"].get(cls["name"], {})
        nodes.append(dict(id=cls["name"], kind="structure", badge="c", term="Class",
                          label=cls["label"], name=cls["name"], iri=str(subject),
                          sub=cls["table"], inDomain=members, inRange=incoming,
                          lines=ttl_graph.box_label(cls).split("\\n"),
                          value=indiv.get("value"), sample=indiv.get("sample"),
                          objects=indiv.get("objects"),
                          indivSql=indiv.get("sql"), labelRule=indiv.get("rule"),
                          description=sqlgen._one(graph, subject, RDFS.comment),
                          table=cls["table"], structural=structural, annotations=annotations,
                          sources=snippets(graph, cls["name"])))
    for cls in shape["defined"] + shape["unexplained"]:
        subject = sqlgen.P(cls["name"])
        structural, annotations = terms(graph, subject)
        fact = facts["concepts"].get(cls["name"], {})
        indiv = facts["individuals"].get(cls["name"], {})   # ← bugfix: was leaking the previous loop's dict
        members, incoming = class_members(graph, cls["name"])
        nodes.append(dict(id=cls["name"], kind="meaning", badge="c", term="Defined class",
                          label=cls["label"], name=cls["name"], iri=str(subject),
                          inDomain=members, inRange=incoming,
                          sub=cls.get("defined_by") or cls.get("note") or "no definition",
                          lines=[cls["label"], cls.get("defined_by") or cls.get("note")
                                 or "no definition"],
                          description=sqlgen._one(graph, subject, RDFS.comment),
                          definedBy=cls.get("defined_by"), definedVia=cls.get("via"),
                          refusal=cls.get("note"),
                          sql=fact.get("sql"), value=indiv.get("value"),
                          sample=indiv.get("sample"), objects=indiv.get("objects"),
                          labelRule=indiv.get("rule"),
                          structural=structural, annotations=annotations,
                          sources=snippets(graph, cls["name"])))
    for m in shape["metrics"] + shape["refused"]:
        compiled = m in shape["metrics"]
        subject = sqlgen.P(m["name"])
        structural, annotations = terms(graph, subject)
        fact = facts["metrics"].get(m["name"], {})
        nodes.append(dict(id="m_" + m["name"], name=m["name"],
                          kind="metric" if compiled else "metric-refused",
                          badge="dp", term="Datatype Property · metric",
                          label=m["name"], iri=str(subject), sub=m["line"],
                          lines=[m["name"], m["line"]],
                          refusal=None if compiled else m["line"],
                          description=sqlgen._one(graph, subject, RDFS.comment),
                          sql=fact.get("sql"), value=fact.get("value"),
                          error=fact.get("error"),
                          structural=structural, annotations=annotations,
                          sources=snippets(graph, m["name"])))
    for link in shape["links"] + shape["derived"]:
        if not link.get("src"):
            continue
        edges.append(dict(src=link["src"], dst=link["dst"], label=link["name"],
                          kind="link" if link["column"] else "derived"))
    for parent, child in shape["subclasses"]:
        edges.append(dict(src=child, dst=parent, label="subClassOf", kind="subclass"))
    for m in shape["metrics"] + shape["refused"]:
        if m["domain"]:
            edges.append(dict(src="m_" + m["name"], dst=m["domain"], label="",
                              kind="measures"))

    position = {}
    for node in nodes:
        box = lay["nodes"].get(node["id"])
        if box is None:
            continue
        # dot's y grows up, SVG's grows down; inches -> points
        position[node["id"]] = [round(box["x"] * 72, 1), round(box["y"] * 72, 1),
                                round(box["w"] * 72, 1), round(box["h"] * 72, 1)]
    missing = [n["id"] for n in nodes if n["id"] not in position]
    # A page has to be able to prove it is current: an mtime comparison breaks the moment a checkout
    # resets file times (measured: after `git pull` the page and its TTLs share one mtime and a stale
    # page looks fresh). A fingerprint of the inputs answers the question the reader actually has.
    import hashlib

    digest = hashlib.sha256()
    for path in ttl_files():
        digest.update(str(path.name).encode())
        digest.update(str(path.stat().st_size).encode())
        digest.update(path.read_bytes())
    # …and the GENERATOR: a page built by a broken generator from identical TTLs is still a broken page.
    # Measured right after fixing two unterminated template literals here: every profile's page carried a
    # matching fingerprint, so nothing regenerated and the window stayed blank.
    digest.update(pathlib.Path(__file__).read_bytes())
    return dict(nodes=nodes, edges=edges, pos=position,
                width=round(lay["width"] * 72 + 40), height=round(lay["height"] * 72 + 40),
                missing=missing, note=facts["note"],
                triples=len(graph), files=len(ttl_files()), sample=sample_limit,
                dsn=f"{DSN['dbname']} @ {DSN['host']}:{DSN['port']}",
                doc=DOC.name if DOC.exists() else None,
                generated=time.strftime("%Y-%m-%d %H:%M"),
                fingerprint=digest.hexdigest()[:16],
                counts=dict(structure=len(shape["physical"]),
                            meaning=len(shape["defined"]) + len(shape["unexplained"]),
                            metrics=len(shape["metrics"]), refused=len(shape["refused"]),
                            links=len(shape["links"])))


HTML = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<title>__TITLE__ —— 图谱与文档（由 TTL 生成）</title>
<style>
  :root { --ink:#1b1b1b; --dim:#777; --faint:#999; --line:#c9c9c9; --pick:#ffe9a8; }
  * { box-sizing:border-box }
  body { margin:0; font:13px/1.45 -apple-system,Helvetica,Arial,sans-serif; color:var(--ink);
         display:flex; height:100vh; overflow:hidden; background:#fbfbfb }
  code, pre, .mono { font-family:ui-monospace,SFMono-Regular,Menlo,monospace }
  /* ── index: a documentation table of contents that drives the graph ────── */
  #index { width:232px; border-right:1px solid #e2e2e2; background:#fff; overflow-y:auto;
           padding:10px 0 40px; flex:none }
  #index .head { padding:0 12px 8px; font-size:10px; letter-spacing:.06em;
                 text-transform:uppercase; color:var(--dim) }
  #index .grp { padding:12px 12px 3px; font-size:10px; letter-spacing:.06em;
                text-transform:uppercase; color:var(--dim); border-top:1px solid #f0f0f0 }
  #index .grp:first-child { border-top:none }
  #index a { display:block; padding:2px 12px 2px 16px; font-size:12px; color:var(--ink);
             text-decoration:none; cursor:pointer; white-space:nowrap; overflow:hidden;
             text-overflow:ellipsis }
  #index a:hover { background:#f4f4f4 }
  #index a.on { background:var(--pick); font-weight:600 }
  #index a.off, #index .grp.off { display:none }
  /* ── stage ─────────────────────────────────────────────────────────────── */
  #stage { flex:1; position:relative; overflow:hidden; cursor:grab; min-width:0 }
  #stage.dragging { cursor:grabbing }
  svg { width:100%; height:100%; display:block }
  .node { cursor:pointer }
  .node rect, .node ellipse { stroke:#333; stroke-width:1; fill:#fff }
  .node.meaning rect { fill:#efefef }
  .node.metric ellipse { fill:#f7f7f7 }
  .node.metric-refused ellipse { fill:#ffe2e2 }
  .node text { font-size:9px; fill:var(--ink); pointer-events:none }
  .node .name { font-size:10px; font-weight:600 }
  .node .sub { font-size:8.5px; fill:#333 }
  .node .col { font-size:8px; fill:#666; font-family:ui-monospace,Menlo,monospace }
  .node.dim { opacity:.14 }
  .node.reach rect, .node.reach ellipse { stroke:#888 }
  .node.hit rect, .node.hit ellipse { stroke:var(--pick); stroke-width:3 }
  .node.sel rect, .node.sel ellipse { stroke:#c99a00; stroke-width:4 }
  .edge { fill:none; stroke:var(--line); stroke-width:1.1 }
  .edge.measures { stroke-dasharray:3 3; stroke:#bbb }
  .edge.subclass { stroke-dasharray:1 3 }
  .edge.dim { opacity:.1 }
  .edge.hit { stroke:#c99a00; stroke-width:1.8 }
  .edge-label { font-size:8px; fill:var(--dim); pointer-events:none }
  #bar { position:absolute; top:10px; left:12px; right:12px; display:flex; gap:6px;
         align-items:center; font-size:11px; background:rgba(255,255,255,.93);
         padding:6px 8px; border-radius:4px; border:1px solid #e2e2e2 }
  #bar input { border:1px solid #ddd; border-radius:3px; padding:3px 6px; font-size:11px;
               width:140px }
  #bar button { border:1px solid #ddd; background:#fff; border-radius:3px; padding:3px 7px;
                font-size:11px; cursor:pointer }
  #bar button.on { background:#333; color:#fff; border-color:#333 }
  #bar .sp { flex:1 }
  #bar .meta { color:var(--dim); font-size:10px; white-space:nowrap; overflow:hidden;
               text-overflow:ellipsis }
  #hint { position:absolute; bottom:8px; left:12px; font-size:10px; color:var(--faint) }
  #controls { position:absolute; right:12px; bottom:12px; user-select:none }
  #controls .row { display:flex; gap:4px; justify-content:flex-end; margin-top:4px }
  #controls button { width:26px; height:26px; padding:0; border:1px solid #ddd; background:rgba(255,255,255,.95);
                     border-radius:3px; cursor:pointer; font-size:13px; line-height:1; color:var(--ink) }
  #controls button:hover { background:#f1f1f1 }
  #controls button:active { background:#e8e8e8 }
  #controls button.on { background:#333; color:#fff; border-color:#333 }
  #controls button[data-mode] { width:auto; padding:0 6px; font-size:11px }
  /* ── panel: the documentation ──────────────────────────────────────────── */
  #panel { width:432px; border-left:1px solid #e2e2e2; background:#fff; overflow-y:auto;
           padding:14px 16px 60px; flex:none }
  #panel h1 { font-size:15px; margin:0 0 2px }
  #panel .kind { color:var(--dim); font-size:11px; margin-bottom:10px }
  #panel h2 { font-size:10px; text-transform:uppercase; letter-spacing:.08em; color:var(--dim);
              margin:16px 0 4px; font-weight:600 }
  #panel pre { margin:0; background:#f5f5f5; border:1px solid #e8e8e8; border-radius:3px;
               padding:7px 8px; overflow-x:auto; font-size:11px; line-height:1.4;
               white-space:pre-wrap; word-break:break-word }
  #panel .desc { margin:0; font-size:12.5px; line-height:1.5 }
  #panel .big { font:600 20px/1.2 ui-monospace,Menlo,monospace; margin:2px 0 0 }
  #panel table.ann { width:100%; border-collapse:collapse; font-size:11.5px }
  #panel table.ann th { text-align:left; vertical-align:top; width:38%; padding:3px 8px 3px 0;
                        color:#555; font-weight:500 }
  #panel table.ann td { padding:3px 0; word-break:break-word; vertical-align:top }
  /* id columns hug their content instead of stealing a third of the row */
  #panel table.ann th.idcol, #panel table.ann td.idcol { width:1%; white-space:nowrap;
                                                         padding-right:14px }
  #panel .why { color:#a11; font-size:11.5px; margin:0 }
  #panel .file { font-family:ui-monospace,Menlo,monospace; font-size:10px; color:var(--dim) }
  #panel .muted { color:var(--dim) }
  #panel .db { background:#eef4fb; border-left:3px solid #7aa7d9; border-radius:3px;
               padding:8px 10px }
  #panel .db .src { font-size:10px; color:#4a6f9c; margin-top:5px;
                    font-family:ui-monospace,Menlo,monospace }
  #panel .db table.ann th, #panel .db table.ann td { border-color:#d5e3f2 }
  #bar .dbchip { font-size:10px; color:#4a6f9c; white-space:nowrap }
</style></head>
<body>
<div id="index"><div class="head">实体</div><div id="idx"></div></div>
<div id="stage">
  <div id="bar">
    <input id="q" placeholder="搜索…">
    <button data-k="structure" class="on">类</button>
    <button data-k="meaning" class="on">定义</button>
    <button data-k="metric" class="on">属性</button>
    <button id="reset">适配</button>
    <span class="sp"></span>
    <span class="dbchip" id="scope"></span>
    <span class="dbchip">■ 蓝色 = 在 Postgres 里实测</span>
    <span class="meta" id="meta"></span>
  </div>
  <svg id="svg"><g id="view"></g></svg>
  <div id="controls">
    <div class="row">
      <button id="c-fit" title="适配窗口 — 快捷键 0">⤢</button>
      <button id="c-zin" title="放大 — 快捷键 +">＋</button>
      <button id="c-zout" title="缩小 — 快捷键 −">−</button>
    </div>
    <div class="row">
      <button data-mode="domain" title="这个词的属性指向谁 — 快捷键 d">域→</button>
      <button data-mode="range" title="谁指向这个词 — 快捷键 r">←值域</button>
      <button data-mode="both" title="两个方向都看 — 快捷键 b">双向</button>
    </div>
    <div class="row">
      <button data-pan="left" title="左移 — 快捷键 ←">←</button>
      <button data-pan="up" title="上移 — 快捷键 ↑">↑</button>
      <button data-pan="down" title="下移 — 快捷键 ↓">↓</button>
      <button data-pan="right" title="右移 — 快捷键 →">→</button>
    </div>
  </div>
  <div id="hint">点一个实体 · <b>域→ / ←值域</b> 只留与它相关的 · 拖动节点 · 滚轮缩放 · 方向键平移 · 快捷键 + − 0 ← ↑ ↓ → d r b</div>
</div>
<div id="panel">
  <h1>__TITLE__</h1>
  <div class="kind">__GENERATED__ · 由 __FILES__ 个文件里的 __TRIPLES__ 条三元组生成</div>
  <p class="muted">在左侧或图里点一个 <b>c</b> 类或一个 <b>dp</b> 数据属性。这一栏是它的文档，
  由 <code>.ttl</code> 生成，用词与 <code>ontology-doc.html</code> 一致：描述、等价类、注解属性、
  公理、IRI。<b>域</b>/<b>值域</b> 两个列表就是那一页里说的 <i>In Domain Of</i> 与
  <i>In Range Of</i>。</p>
  <p class="muted" id="note">__NOTE__</p>
</div>
<script>
const DATA = __DATA__;
const NS = "http://www.w3.org/2000/svg";
const svg = document.getElementById("svg"), view = document.getElementById("view");
const stage = document.getElementById("stage"), panel = document.getElementById("panel");
const byId = Object.fromEntries(DATA.nodes.map(n => [n.id, n]));
let scale = 1, tx = 0, ty = 0, selected = null;

// dot's y grows up, so flip once, here, using the box height
const pos = {};
for (const [id, b] of Object.entries(DATA.pos)) {
  const kind = (byId[id] || {}).kind || "";
  pos[id] = {x: b[0], y: DATA.height - b[1], w: b[2], h: b[3],
             shape: kind.startsWith("metric") ? "ellipse" : "rect"};
}
const have = id => pos[id] !== undefined;
const centre = id => ({x: pos[id].x, y: pos[id].y});
// An arrow that ends in the middle of a box says nothing about direction, so each end is
// pulled back to the border of the node it touches: rectangle for a class, ellipse for a
// datatype property.
function border(center, toward, node) {
  const dx = toward.x - center.x, dy = toward.y - center.y;
  const len = Math.hypot(dx, dy) || 1;
  const ux = dx / len, uy = dy / len;
  const hw = Math.max(node.w / 2, 6), hh = Math.max(node.h / 2, 6);
  const ellipse = node.shape === "ellipse";
  const t = ellipse
    ? 1 / Math.sqrt((ux * ux) / (hw * hw) + (uy * uy) / (hh * hh))
    : Math.min(Math.abs(ux) > 1e-6 ? hw / Math.abs(ux) : Infinity,
               Math.abs(uy) > 1e-6 ? hh / Math.abs(uy) : Infinity);
  return {x: center.x + ux * t, y: center.y + uy * t};
}
const edgePoints = e => {
  const a = centre(e.src), b = centre(e.dst);
  const A = pos[e.src], B = pos[e.dst];
  return {start: border(a, b, A), end: border(b, a, B)};
};
const edgePath = e => {
  const {start, end} = edgePoints(e), m = (start.x + end.x) / 2;
  return `M${start.x},${start.y} C${m},${start.y} ${m},${end.y} ${end.x},${end.y}`;
};

function draw() {
  const mk = (t, attrs) => { const el = document.createElementNS(NS, t);
    for (const k in attrs) el.setAttribute(k, attrs[k]); return el };
  const defs = mk("defs", {});
  for (const [id, fill] of [["arrow", "#9a9a9a"], ["arrow-hit", "#c99a00"]]) {
    const marker = mk("marker", {id, viewBox: "0 0 10 10", refX: "9", refY: "5",
                                 markerWidth: "6", markerHeight: "6", orient: "auto"});
    marker.appendChild(mk("path", {d: "M0,0 L10,5 L0,10 z", fill}));
    defs.appendChild(marker);
  }
  svg.appendChild(defs);
  const gEdges = mk("g", {}), gNodes = mk("g", {});
  view.appendChild(gEdges); view.appendChild(gNodes);

  for (const e of DATA.edges) {
    if (!have(e.src) || !have(e.dst)) continue;
    const p = mk("path", {d: edgePath(e), class: "edge " + e.kind,
                          "data-src": e.src, "data-dst": e.dst,
                          "marker-end": "url(#arrow)"});
    const t = mk("title", {}); t.textContent = e.label || e.kind;
    p.appendChild(t); gEdges.appendChild(p);
    if (e.label) {
      const a = centre(e.src), b = centre(e.dst);
      const lab = mk("text", {x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 - 3, class: "edge-label",
                              "text-anchor": "middle", "data-src": e.src, "data-dst": e.dst});
      lab.textContent = e.label; gEdges.appendChild(lab);
    }
  }

  for (const n of DATA.nodes) {
    if (!have(n.id)) continue;
    const p = pos[n.id];
    const g = mk("g", {class: "node " + n.kind, "data-id": n.id,
                       transform: `translate(${p.x},${p.y})`});
    if (n.kind.startsWith("metric")) {
      g.appendChild(mk("ellipse", {rx: p.w / 2, ry: p.h / 2, cx: 0, cy: 0}));
    } else {
      g.appendChild(mk("rect", {x: -p.w / 2, y: -p.h / 2, width: p.w, height: p.h, rx: 3}));
    }
    const lines = n.lines || [n.label];
    const step = 11, top = -((lines.length - 1) * step) / 2;
    lines.forEach((text, i) => {
      const cls = i === 0 ? "name" : (i === 1 ? "sub" : "col");
      const el = mk("text", {x: 0, y: top + i * step + 3, "text-anchor": "middle", class: cls});
      el.textContent = text;
      g.appendChild(el);
    });
    const tip = mk("title", {}); tip.textContent = n.id; g.appendChild(tip);
    gNodes.appendChild(g);
  }
  applyTransform();
}
const applyTransform = () => view.setAttribute("transform", `translate(${tx},${ty}) scale(${scale})`);
function fit() {
  const w = stage.clientWidth, h = stage.clientHeight;
  scale = Math.min(w / DATA.width, h / DATA.height, 1.3);
  tx = (w - DATA.width * scale) / 2; ty = (h - DATA.height * scale) / 2;
  applyTransform();
}

// ── the index ──────────────────────────────────────────────────────────────
const GROUPS = [["structure", "Classes"], ["meaning", "Defined classes"],
                ["metric", "Datatype Properties — compiled"],
                ["metric-refused", "Datatype Properties — refused"]];
function buildIndex() {
  const box = document.getElementById("idx");
  for (const [kind, title] of GROUPS) {
    const rows = DATA.nodes.filter(n => n.kind === kind);
    if (!rows.length) continue;
    const h = document.createElement("div");
    h.className = "grp";
    h.dataset.k = kind === "metric-refused" ? "metric" : kind;
    h.textContent = `${title} (${rows.length})`; box.appendChild(h);
    for (const n of rows) {
      const a = document.createElement("a");
      a.dataset.id = n.id; a.dataset.k = kind;
      a.textContent = n.label; a.title = n.id;
      a.onclick = () => show(n.id);
      box.appendChild(a);
    }
  }
}

// ── the panel ──────────────────────────────────────────────────────────────
function clearMarks() {
  document.querySelectorAll(".node").forEach(el => el.classList.remove("hit", "sel", "dim", "reach"));
  document.querySelectorAll(".edge, .edge-label").forEach(el => {
    el.classList.remove("hit", "dim"); el.style.display = "";
  });
  const scope = document.getElementById("scope"); if (scope) scope.textContent = "";
}
// The radius was the wrong idea: what a reader wants to see is the RELATION, not a hop
// count. `domain` lights the classes this term's properties point at, `range` lights what
// points at this term — which is how `Region` reaches `Nation` (n_regionkey) and
// `Customer` (the customerRegion chain) in one step, instead of a 2-hop walk.
let mode = "both";
function litBy(id, how) {
  const out = new Set([id]);
  for (const e of DATA.edges) {
    if (how !== "range" && e.src === id) out.add(e.dst);     // my properties, my metrics
    if (how !== "domain" && e.dst === id) out.add(e.src);    // properties that point at me
  }
  return out;
}
function setMode(value) {
  mode = value;
  document.querySelectorAll("#controls button[data-mode]").forEach(b =>
    b.classList.toggle("on", b.dataset.mode === value));
  if (selected) focus(selected);
}
function focus(id) {
  clearMarks();
  const near = litBy(id, mode);
  const el = document.querySelector(`.node[data-id="${id}"]`);
  document.querySelectorAll(".node").forEach(n => {
    const lit = near.has(n.dataset.id);
    n.classList.toggle("dim", n !== el && !lit);
    if (lit) n.classList.add("reach");
  });
  if (!el) return;
  el.classList.add("sel");
  // In `domain`/`range` mode the other edges are not dimmed — they are removed from the
  // picture, so what remains IS the answer to "show me the range relations".
  let shown = 0, total = 0;
  document.querySelectorAll(".edge, .edge-label").forEach(edge => {
    // `range` shows only the edges that END here; `domain` only the ones that LEAVE here.
    // The lit set is still two-way, but the picture is the relation you asked for.
    const hit = mode === "range" ? edge.dataset.dst === id
              : mode === "domain" ? edge.dataset.src === id
              : (near.has(edge.dataset.src) && near.has(edge.dataset.dst));
    total += edge.classList.contains("edge") ? 1 : 0;
    shown += edge.classList.contains("edge") && hit ? 1 : 0;
    edge.style.display = (mode === "both" || hit) ? "" : "none";
    edge.classList.toggle("hit", hit);
    edge.classList.toggle("dim", mode === "both" && !hit);
    if (edge.classList.contains("edge"))
      edge.setAttribute("marker-end", hit ? "url(#arrow-hit)" : "url(#arrow)");
  });
  const scope = document.getElementById("scope");
  if (scope) scope.textContent =
    `${mode} · ${near.size}/${DATA.nodes.length} lit · ` +
    (mode === "both" ? `${total} edges` : `${shown}/${total} edges shown`);
}
const esc = s => String(s).replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
const num = v => typeof v === "number" ? v.toLocaleString(undefined, {maximumFractionDigits: 4}) : v;
const section = (title, body, cls) =>
  body ? `<h2>${title}</h2><div class="${cls || ""}">${body}</div>` : "";
const dbSrc = () => `<div class="src">来自 Postgres · ${DATA.dsn} · 实测于 ${DATA.generated}</div>`;
function propTable(rows) {
  if (!rows || !rows.length) return "";
  const tr = rows.map(r => {
    const facts = [r.col, r.sqlType, r.unit, r.additivity, r.aggregate && ("aggregate " + r.aggregate)]
      .filter(Boolean).join(" · ");
    const tail = r.kind === "object"
      ? `<span class="file">→ ${esc(r.to || "?")}${r.refs ? " · references " + esc(r.refs) : ""}</span>`
      : (facts ? `<span class="file">${esc(facts)}</span>` : "");
    return `<tr><td class="mono">:${esc(r.n)}</td><td>${tail}` +
      (r.formula ? `<div class="file">formula: ${esc(r.formula)}</div>` : "") + `</td></tr>`;
  }).join("");
  return `<table class="ann">${tr}</table>`;
}
function rangeTable(rows) {
  if (!rows || !rows.length) return "";
  return `<table class="ann">` + rows.map(r => {
    // A plain link names its :domain. A derived one has none, so name the chain instead —
    // and its origin, which is the first hop's :domain, not a guess.
    let src;
    if (r.from) src = `from :${esc(r.from)}`;
    else if (r.chain && r.chain.length)
      src = `derived: ${r.chain.map(h => ":" + esc(h)).join(" → ")}` +
            (r.chain_start ? ` · from :${esc(r.chain_start)}` : "");
    else src = "no :domain declared";
    return `<tr><td class="mono">:${esc(r.n)}</td><td><span class="file">${src}</span></td></tr>`;
  }).join("") + `</table>`;
}
function indivTable(sample, rule, objects) {
  // Tabular, like the SQL it came from: one row per object, every column of the physical
  // row, and a last column with the defined classes the row satisfies (evaluated from the
  // axiom — the membership is never stored).
  if (objects && objects.length) {
    const cols = [];
    objects.forEach(o => o.props.forEach(([k]) => { if (!cols.includes(k)) cols.push(k); }));
    const idcol = c => /(^|_)id$/i.test(c);
    const head = `<tr>${cols.map(c => `<th class="${idcol(c) ? "idcol" : ""}">${esc(c)}</th>`)
      .join("")}<th>defined classes</th></tr>`;
    const body = objects.map(o => {
      const byCol = Object.fromEntries(o.props);
      const cells = cols.map(c =>
        `<td class="mono${idcol(c) ? " idcol" : ""}">${esc(byCol[c] ?? "")}</td>`).join("");
      const cls = o.classes.length
        ? o.classes.map(c => `<b>:${esc(c)}</b>`).join("<br>") : "—";
      return `<tr>${cells}<td>${cls}</td></tr>`;
    }).join("");
    return `<table class="ann">${head}${body}</table>` +
      `<div class="file" style="margin-top:4px">rows from ${esc(rule)} · ` +
      `defined classes evaluated from the axiom, not stored</div>`;
  }
  const head = `<tr>${sample.cols.map(c => `<th>${esc(c)}</th>`).join("")}</tr>`;
  const body = sample.rows.map(r =>
    `<tr>${r.map(v => `<td class="mono">${esc(v)}</td>`).join("")}</tr>`).join("");
  return `<table class="ann">${head}${body}</table>` +
    `<div class="file" style="margin-top:4px">columns from ${esc(rule)}</div>`;
}
function annTable(rows) {
  if (!rows || !rows.length) return "";
  const tr = rows.map(r =>
    `<tr><th>${esc(r.label)}${r.iri ? `<br><span class="file">${esc(r.iri)}</span>` : ""}</th>` +
    `<td>${r.v.map(v => esc(v)).join("<br>")}</td></tr>`).join("");
  return `<table class="ann">${tr}</table>`;
}
function show(id) {
  const n = byId[id]; if (!n) return;
  selected = id; focus(id);
  document.querySelectorAll("#idx a").forEach(a => a.classList.toggle("on", a.dataset.id === id));
  document.querySelector(`#idx a[data-id="${id}"]`)?.scrollIntoView({block: "nearest"});

  let html = `<h1>${esc(n.label)}</h1><div class="kind"><b>${esc(n.badge)}</b> · ` +
    `${esc(n.term || n.kind)} · <code>:${esc(n.name)}</code></div>`;
  if (n.description) html += section("描述", `<p class="desc">${esc(n.description)}</p>`);
  if (n.definedBy) {
    const title = n.definedVia === "physicalPredicate" ? "手写谓词" : "等价类";
    html += section(title, `<pre>${esc(n.definedBy)}</pre>`);
  }
  if (n.refusal) html += section("Definition", `<p class="why">${esc(n.refusal)}</p>`);
  if (n.sql) html += section("SQL", `<pre>${esc(n.sql)}</pre>`);
  // ONE container for anything that comes out of the database: the count and the values
  // it belongs to. Two boxes made them look like two different kinds of evidence.
  if (n.value !== undefined && n.value !== null) {
    let body = `<div class="big">${num(n.value)}</div>`;
    if (n.kind.startsWith("metric")) {
      html += section("Measured now", body + dbSrc(), "db");
    } else {
      if (n.sample) body += `<div style="margin-top:9px">${indivTable(n.sample, n.sample.rule, n.objects)}</div>`;
      else if (n.indivSql && n.value > DATA.sample)
        body += `<p class="muted" style="margin:6px 0 0">more than ${DATA.sample} — counted, not listed.</p>`;
      html += section("Individuals", body + dbSrc(), "db");
    }
  }
  if (n.error) html += `<p class="why">${esc(n.error)}</p>`;
  // Read the way a reader says it out loud: "domain :Region has two properties, r_name and
  // r_regionkey". pyLODE calls the same list "In Domain Of" — the count is there so the
  // claim can be checked at a glance against the rows underneath.
  if ((n.inDomain || []).length)
    html += section(`域 :${esc(n.name)} — ${n.inDomain.length} 个属性`,
                    propTable(n.inDomain));
  if ((n.inRange || []).length)
    html += section(`值域 :${esc(n.name)} — ${n.inRange.length} 个属性`,
                    rangeTable(n.inRange));
  html += section("注解属性", annTable(n.annotations));
  html += section("公理", annTable(n.structural));
  const src = n.sources || {};
  for (const s of src.self || [])
    html += section(`TTL · <span class="file">${esc(s.file)}:${s.line}</span>`,
                    `<pre>${esc(s.text)}</pre>`);
  if ((src.related || []).length) {
    const body = src.related.map(s =>
      `<div class="file" style="margin:0 0 2px">:${esc(s.prop)} names it · ${esc(s.rel)} · ${esc(s.file)}:${s.line}</div>` +
      `<pre style="margin:0 0 8px">${esc(s.text)}</pre>`).join("");
    html += section("TTL — statements that name this term", body);
  }
  if ((src.comments || []).length) {
    const body = src.comments.map(c =>
      `<div class="file">${esc(c.file)}:${c.line}</div>` +
      `<pre style="margin:0 0 6px">${esc(c.text)}</pre>`).join("");
    html += section("Mentioned in comments — not data; Protégé deletes these", body);
  }
  html += section("IRI", `<p class="file">${esc(n.iri || "")}</p>`);
  panel.innerHTML = html;
  panel.scrollTop = 0;
}

// ── interaction ────────────────────────────────────────────────────────────
svg.addEventListener("click", ev => {
  const node = ev.target.closest(".node");
  if (node) return show(node.dataset.id);
  if (!ev.target.closest(".edge")) { clearMarks(); selected = null;
    document.querySelectorAll("#idx a").forEach(a => a.classList.remove("on")); }
});
let drag = null;
svg.addEventListener("mousedown", ev => {
  const node = ev.target.closest(".node");
  drag = node ? {id: node.dataset.id, x: ev.clientX, y: ev.clientY}
              : {pan: true, x: ev.clientX, y: ev.clientY};
  if (drag.pan) stage.classList.add("dragging");
});
window.addEventListener("mousemove", ev => {
  if (!drag) return;
  const dx = ev.clientX - drag.x, dy = ev.clientY - drag.y;
  if (drag.pan) { tx += dx; ty += dy; drag.x = ev.clientX; drag.y = ev.clientY; applyTransform(); }
  else {
    const p = pos[drag.id];
    p.x += dx / scale; p.y += dy / scale;
    drag.x = ev.clientX; drag.y = ev.clientY;
    document.querySelector(`.node[data-id="${drag.id}"]`)
      ?.setAttribute("transform", `translate(${p.x},${p.y})`);
    document.querySelectorAll(`.edge[data-src="${drag.id}"], .edge[data-dst="${drag.id}"]`)
      .forEach(el => el.setAttribute("d", edgePath({src: el.dataset.src, dst: el.dataset.dst})));
  }
});
window.addEventListener("mouseup", () => { drag = null; stage.classList.remove("dragging"); });
function zoomBy(k, cx, cy) {
  const r = stage.getBoundingClientRect();
  const mx = cx === undefined ? r.width / 2 : cx;
  const my = cy === undefined ? r.height / 2 : cy;
  const next = Math.min(4, Math.max(0.15, scale * k));
  tx = mx - (mx - tx) * (next / scale);
  ty = my - (my - ty) * (next / scale);
  scale = next; applyTransform();
}
function panBy(dx, dy) { tx += dx; ty += dy; applyTransform(); }

svg.addEventListener("wheel", ev => {
  ev.preventDefault();
  const r = stage.getBoundingClientRect();
  zoomBy(ev.deltaY < 0 ? 1.12 : 1 / 1.12, ev.clientX - r.left, ev.clientY - r.top);
}, {passive: false});

document.getElementById("c-zin").onclick = () => zoomBy(1.25);
document.getElementById("c-zout").onclick = () => zoomBy(1 / 1.25);
document.getElementById("c-fit").onclick = () => { fit(); clearMarks(); };
document.querySelectorAll("#controls button[data-pan]").forEach(b => {
  b.onclick = () => {
    const step = 70, dir = b.dataset.pan;
    panBy(dir === "left" ? step : dir === "right" ? -step : 0,
          dir === "up" ? step : dir === "down" ? -step : 0);
  };
});
window.addEventListener("keydown", ev => {
  const tag = (document.activeElement || {}).tagName;
  if (tag === "INPUT" || tag === "TEXTAREA") return;
  const k = ev.key;
  if (k === "+" || k === "=") { zoomBy(1.25); ev.preventDefault(); }
  else if (k === "-" || k === "_") { zoomBy(1 / 1.25); ev.preventDefault(); }
  else if (k === "0") { fit(); ev.preventDefault(); }
  else if (k === "d" || k === "D") { setMode("domain"); ev.preventDefault(); }
  else if (k === "r" || k === "R") { setMode("range"); ev.preventDefault(); }
  else if (k === "b" || k === "B") { setMode("both"); ev.preventDefault(); }
  else if (k === "ArrowLeft") { panBy(60, 0); ev.preventDefault(); }
  else if (k === "ArrowRight") { panBy(-60, 0); ev.preventDefault(); }
  else if (k === "ArrowUp") { panBy(0, 60); ev.preventDefault(); }
  else if (k === "ArrowDown") { panBy(0, -60); ev.preventDefault(); }
});

const filters = {structure: true, meaning: true, metric: true};
document.querySelectorAll("#bar button[data-k]").forEach(b => {
  b.onclick = () => {
    const k = b.dataset.k; filters[k] = !filters[k]; b.classList.toggle("on", filters[k]);
    document.querySelectorAll(".node").forEach(el => {
      const kind = el.dataset.id.startsWith("m_") ? "metric" : byId[el.dataset.id].kind;
      el.style.display = filters[kind] === false ? "none" : "";
    });
    document.querySelectorAll("#idx a").forEach(a => {
      const kind = a.dataset.k === "metric-refused" ? "metric" : a.dataset.k;
      a.classList.toggle("off", filters[kind] === false);
    });
    document.querySelectorAll("#idx .grp").forEach(g => {
      const kind = g.dataset.k === "metric-refused" ? "metric" : g.dataset.k;
      g.classList.toggle("off", filters[kind] === false);
    });
  };
});
document.getElementById("reset").onclick = () => { fit(); clearMarks(); };
document.querySelectorAll("#controls button[data-mode]").forEach(b => {
  b.onclick = () => setMode(b.dataset.mode);
});
document.getElementById("q").oninput = ev => {
  const q = ev.target.value.toLowerCase().trim();
  clearMarks();
  document.querySelectorAll("#idx a").forEach(a => {
    const n = byId[a.dataset.id];
    const hay = (n.label + " " + a.dataset.id + " " + (n.sub || "") + " " +
                 (n.description || "")).toLowerCase();
    a.classList.toggle("off", q !== "" && !hay.includes(q));
    a.classList.toggle("on", q !== "" && hay.includes(q));
  });
  document.querySelectorAll(".node").forEach(el => {
    const n = byId[el.dataset.id];
    const hay = (n.label + " " + el.dataset.id + " " + (n.sub || "")).toLowerCase();
    el.classList.toggle("hit", q !== "" && hay.includes(q));
    el.classList.toggle("dim", q !== "" && !hay.includes(q));
  });
};

document.getElementById("meta").textContent =
  `${DATA.triples} triples · ${DATA.counts.structure} classes · ` +
  `${DATA.counts.meaning} defined classes · ${DATA.counts.metrics + DATA.counts.refused} ` +
  `datatype properties (${DATA.counts.metrics} compiled, ${DATA.counts.refused} refused)` +
  (DATA.doc ? ` · doc: ${DATA.doc}` : "");
draw();
buildIndex();
fit();
setMode("both");
if (DATA.missing.length) document.getElementById("note").textContent =
  "no layout position for: " + DATA.missing.join(", ");
</script></body></html>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE / "ontology.html"))
    ap.add_argument("--open", action="store_true", help="open it in the browser")
    ap.add_argument("--sample", type=int, default=SAMPLE,
                    help="list a class's individuals when it has at most this many")
    ap.add_argument("--ns", default=None, help="ontology namespace IRI")
    ap.add_argument("--ontology-dir", default=None,
                    help="folder containing ontology/*.ttl files")
    ap.add_argument("--overlay", default=None,
                    help="overlay TTL declaring :aggregate/:grain/:universe")
    ap.add_argument("--dsn", default=None,
                    help="JDBC-ish DSN: host=… port=… dbname=… user=… password=…")
    ap.add_argument("--title", default="Retail ontology",
                    help="page title shown in the header")
    args = ap.parse_args()

    # ---- settings panel / CLI overrides (applied before any graph build) ----
    global DSN, OVERLAY
    if args.dsn:
        DSN = parse_dsn(args.dsn)
    if args.overlay:
        OVERLAY = pathlib.Path(args.overlay).expanduser()
    # the compiler loads through sqlgen.OVERLAY, so tell it — its own global is not enough
    sqlgen.reconfigure(ns=args.ns, ontology_dir=args.ontology_dir,
                       overlay=str(OVERLAY) if args.overlay else None,
                       drop_overlay=not args.overlay)

    payload = build_payload(args.sample)
    html = (HTML.replace("__DATA__", json.dumps(payload, ensure_ascii=False, default=float))
                .replace("__GENERATED__", payload["generated"])
                .replace("__TRIPLES__", str(payload["triples"]))
                .replace("__FILES__", str(payload["files"]))
                .replace("__NOTE__", payload["note"] or
                         "这个文件写出时实测的数字。"))
    # `__TITLE__` explicitly, instead of the old string surgery: the page used to hardcode
    # "Retail ontology" in two places and be fixed up with `html.replace("Retail ontology", title)`,
    # which silently did nothing for any profile whose title differed (and would have rewritten the
    # phrase anywhere else it appeared).
    html = html.replace("__TITLE__", args.title)
    out = pathlib.Path(args.out)
    out.write_text(html)

    drawn, want = len(payload["pos"]), len(payload["nodes"])
    documented = sum(1 for n in payload["nodes"]
                     if n["annotations"] or (n["sources"] or {}).get("self"))
    props = sum(len(n["inDomain"]) for n in payload["nodes"] if n.get("inDomain") is not None)
    with_props = sum(1 for n in payload["nodes"]
                     if n["kind"] == "structure" and n.get("inDomain"))
    incoming = sum(len(n["inRange"]) for n in payload["nodes"] if n.get("inRange") is not None)
    print(f"== wrote {out.name} — {out.stat().st_size // 1024} KB, self-contained\n")
    print(f"  entities {want} · positioned {drawn} · edges {len(payload['edges'])}")
    print(f"  structure {payload['counts']['structure']} · meaning {payload['counts']['meaning']} "
          f"· metrics {payload['counts']['metrics']} compiled + {payload['counts']['refused']} refused")
    print(f"  entities with documentation {documented}/{want} (annotations or TTL source)")
    counted = sum(1 for n in payload["nodes"]
                  if not n["kind"].startswith("metric") and n.get("value") is not None)
    listed = sum(1 for n in payload["nodes"] if n.get("sample"))
    print(f"  live numbers {sum(1 for n in payload['nodes'] if n.get('value') is not None)} · "
          f"individuals counted for {counted} classes, listed for {listed} · "
          f"annotation rows {sum(len(n['annotations']) for n in payload['nodes'])} · "
          f"{props} properties listed In Domain Of, {incoming} In Range Of")
    if payload["note"]:
        print(f"  note: {payload['note']}")

    ok = (drawn == want and not payload["missing"] and documented == want
          and with_props == payload["counts"]["structure"])
    print(f"\n  gate: {drawn}/{want} positioned, {documented}/{want} documented, "
          f"{with_props}/{payload['counts']['structure']} classes list their properties, "
          f"{counted}/{payload['counts']['structure'] + payload['counts']['meaning']} classes have individuals — "
          f"{'PASS' if ok else 'FAIL ' + str(payload['missing'])}")
    print(f"\n  open: open {out}")
    if args.open:
        import webbrowser
        webbrowser.open(out.as_uri())
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""sqlgen — compile a metric declared in the ontology into SQL. No semantic layer, no LLM.

The contract this file implements is deliberately small, because the contract is the
product:

    declaration in TTL  ->  SQL text, or a Refusal that says which declaration is missing

Three metric classes, each with a different SQL shape (and only three — a metric that
does not fit one of them is refused, not guessed):

    ① derived instance property   :formula only                     -> an expression
    ② aggregate over an object set :formula + :aggregate + :grain    -> agg(expr)
    ③ ratio of sums               :aggregate "ratio_of_sums"        -> sum(expr)/count(*)

What it refuses, and why that list is the point:

    · no :aggregate  -> "an aggregate request needs :aggregate; Cube used to hold this"
    · no :grain      -> "which object grain? SUM without a grain is the fanout bug"
    · unknown :aggregate -> named, never coerced
    · a concept with no compiled predicate -> the number would silently widen

The concept predicate is compiled FROM THE AXIOM (sqlgen.concept_sql), so the threshold
`5000` exists in exactly one place: the ontology.
"""
from __future__ import annotations

import pathlib
import re
import sys
from dataclasses import dataclass, field

from rdflib import OWL, RDF, RDFS, Graph, URIRef
from rdflib.namespace import XSD

CUBE = pathlib.Path(__file__).resolve().parent / "ontology"   # folder of TTL files
NS = "https://cube.local/ontology/retail#"
P = lambda local: URIRef(NS + local)  # noqa: E731  (reads the current NS)


def reconfigure(ns: str | None = None, ontology_dir: str | None = None,
                overlay: str | None = None, drop_overlay: bool = False) -> None:
    """Point the generator at another namespace/ontology folder/overlay (settings profile)."""
    global NS, CUBE, OVERLAY
    if ns:
        NS = ns
    if ontology_dir:
        CUBE = pathlib.Path(ontology_dir)
    if drop_overlay:
        OVERLAY = pathlib.Path("/nonexistent/metrics_ext.ttl")   # a profile with no overlay
    elif overlay is not None:
        OVERLAY = pathlib.Path(overlay) if overlay else OVERLAY

# Physical tables, from the generated Tier A files (`:physicalTable` on each class).
OVERLAY = pathlib.Path(__file__).with_name("metrics_ext.ttl")


def load(with_overlay: bool = True, paths: list[pathlib.Path] | None = None) -> Graph:
    """Load the tutorial ontology, plus (by default) the sql-first overlay.

    `with_overlay=False` is not a debug switch — it is the measurement: the tutorial
    ontology ALONE cannot answer an aggregate, because :aggregate/:grain/:universe were
    Cube's, and `check_metric.py` asserts that refusal by name.
    """
    g = Graph()
    for p in (paths or sorted(CUBE.glob("*.ttl"))):
        g.parse(p, format="turtle")
    if with_overlay and OVERLAY.exists():
        g.parse(OVERLAY, format="turtle")
    return g


def _apply_env_profile() -> None:
    """APP_SETTINGS=<profile.json> points this process at that profile's ontology.

    The app, the NL subprocess and the CLI all import sqlgen, so doing it here means one
    place decides which ontology a process is compiling.
    """
    import json as _json
    import os as _os
    path = _os.environ.get("APP_SETTINGS")
    if not path:
        return
    try:
        prof = _json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return
    # Relative to the PROFILE's folder, not to this module's folder. Resolving against
    # retail_graph/ worked for the retail profile only because its profile file happens to sit
    # there; every other ontology got a directory that does not exist, so its graph loaded
    # EMPTY — the logistics workbench answered every NL question with "metrics []" and nobody
    # could tell that from "this ontology declares nothing".
    base = pathlib.Path(path).resolve().parent
    reconfigure(ns=prof.get("ns") or None,
                ontology_dir=str((base / prof["ontology_dir"]).resolve())
                if prof.get("ontology_dir") else None,
                overlay=str((base / prof["overlay"]).resolve()) if prof.get("overlay") else "",
                drop_overlay=not prof.get("overlay"))


ALIAS_NOTES: list[str] = []

# The truncations a `:timeBucket` may name. Closed on purpose: `date_trunc` accepts a bare word, so an
# open-ended declaration would let a typo ("weeks") compile into a runtime error instead of a refusal.
TIME_BUCKETS = ("day", "week", "month", "quarter")

_apply_env_profile()


class Refusal(Exception):
    """A result, not an error — same rule as the track's resolver."""


@dataclass
class Metric:
    name: str
    domain: str | None
    unit: str | None
    additivity: str | None
    formula: str | None
    aggregate: str | None
    grain: str | None
    universe: str | None
    concept: str | None
    counts: str | None
    where: str | None = None
    group_by: list[str] = field(default_factory=list)
    time_bucket: str | None = None     # ":timeBucket \"week\"" — a declared time axis
    numerator: str | None = None
    denominator: str | None = None
    scale: str | None = None          # multiply a ratio (e.g. "100.0" for a percentage)
    missing: list[str] = field(default_factory=list)


def OWL_STR(text: str):
    """A plain literal (the mutation tests build triples with it)."""
    from rdflib import Literal
    return Literal(text)


def _one(g: Graph, s, pred) -> str | None:
    o = next(iter(g.objects(s, pred)), None)
    return str(o) if o is not None else None


def _local(iri) -> str | None:
    return str(iri).split("#")[-1] if iri is not None else None


def metrics(g: Graph) -> dict[str, Metric]:
    out: dict[str, Metric] = {}
    for s, _, _ in g.triples((None, RDF.type, OWL.DatatypeProperty)):
        formula = _one(g, s, P("formula"))
        aggregate = _one(g, s, P("aggregate"))
        if not (formula or aggregate):
            continue
        m = Metric(
            name=_local(s), domain=_local(next(iter(g.objects(s, RDFS.domain)), None)),
            unit=_one(g, s, P("unit")), additivity=_one(g, s, P("additivity")),
            formula=formula, aggregate=aggregate,
            grain=_local(next(iter(g.objects(s, P("grain"))), None)),
            universe=_local(next(iter(g.objects(s, P("universe"))), None)),
            concept=_local(next(iter(g.objects(s, P("concept"))), None)),
            counts=_local(next(iter(g.objects(s, P("counts"))), None)),
            where=_local(next(iter(g.objects(s, P("where"))), None)),
            group_by=[_local(o) for o in g.objects(s, P("groupBy")) if _local(o)],
            time_bucket=_one(g, s, P("timeBucket")),
            numerator=_local(next(iter(g.objects(s, P("numerator"))), None)),
            denominator=_local(next(iter(g.objects(s, P("denominator"))), None)),
            scale=_one(g, s, P("scale")),
        )
        for fieldname, required in (("formula", "formula"), ("grain", "grain"),
                                    ("universe", "universe")):
            if getattr(m, fieldname) is None:
                m.missing.append(f":{required}")
        out[m.name] = m
    return out


def table_of(g: Graph, cls: str) -> str:
    t = _one(g, P(cls), P("physicalTable"))
    if not t:
        raise Refusal(f"class :{cls} declares no :physicalTable")
    return t


def column_of(g: Graph, cls: str, prop: str) -> str:
    col = _one(g, P(prop), P("physicalColumn"))
    if not col:
        raise Refusal(f"property :{prop} on :{cls} declares no :physicalColumn")
    return col


def concept_sql(g: Graph, concept: str) -> str:
    """Compile a concept's definition into a WHERE predicate (no notes)."""
    return concept_predicate(g, concept)[0]


def concept_predicate(g: Graph, concept: str) -> tuple[str, list[str]]:
    """(predicate, notes) — the notes carry the declared-by-hand warning when it applies."

    The shape this ontology actually uses (measured in 03-customer-meaning.ttl):

        :HighBalanceCustomer owl:equivalentClass [ owl:intersectionOf (
            :Customer
            [ a owl:Restriction ; owl:onProperty :c_acctbal ;
              owl:withRestrictions ( [ xsd:minInclusive "5000.0"^^xsd:decimal ] ) ] ) ] .

    i.e. the facet lives in an `owl:withRestrictions` LIST, not as a predicate on the
    restriction node. Both shapes are accepted here; anything else is refused BY NAME
    rather than half-compiled, because a half-compiled predicate silently widens a
    definition (that is the failure this whole track is about).
    """
    cls = P(concept)
    axioms = list(g.objects(cls, OWL.equivalentClass))
    # `owl:unionOf` is the OR of definitions: a risky driver is late OR damaged OR overloaded.
    # Compile each member with the same machinery and join them with OR, in one parenthesis
    # so a surrounding AND cannot silently change the meaning.
    for axiom in axioms:
        for lst in g.objects(axiom, OWL.unionOf):
            members = list(g.items(lst))
            parts = [_member_predicate(g, concept, member) for member in members]
            if not parts:
                raise Refusal(f":{concept} owl:unionOf has no compilable member")
            return "(" + " OR ".join(dict.fromkeys(parts)) + ")", [
                f":{concept} is a union of {len(parts)} criteria (OR-ed, as declared)"]
    declared = _one(g, cls, P("physicalPredicate"))
    if not axioms:
        # THE ONE ESCAPE HATCH, and it says so. OWL cannot express "one column is greater than
        # another column" — a comparison between two properties is not a facet — so an
        # ontology may declare the predicate itself with :physicalPredicate. It compiles, and
        # the note reports that this definition is declared rather than derived.
        if declared:
            return str(declared).strip(), [
                f":{concept} is declared by hand (:physicalPredicate) — OWL cannot compare two "
                f"columns, so this predicate is the one place a definition is not compiled "
                f"from an axiom: {declared}"]
        raise Refusal(f":{concept} has no owl:equivalentClass axiom — nothing to compile")
    if declared:
        raise Refusal(f":{concept} has BOTH an owl:equivalentClass axiom and a "
                      f":physicalPredicate — pick one (the declared predicate would silently "
                      f"replace the compiled definition)")

    parts: list[str] = []
    for axiom in axioms:
        # walk THIS axiom only: owl:intersectionOf members, then each owl:Restriction.
        # (An earlier version scanned every restriction in the graph and refused a
        # concept because of a restriction belonging to a different axiom.)
        members: list = []          # axiom shapes that are not intersectionOf (e.g. union):
        for lst in g.objects(axiom, OWL.intersectionOf):   # must reach the Refusal below,
            members = list(g.items(lst))                   # not an UnboundLocalError
        if not members:
            members = [axiom]
        for member in members:
            if (member, RDF.type, OWL.Restriction) not in g:
                continue
            on = next(iter(g.objects(member, OWL.onProperty)), None)
            if on is None:
                continue
            prop = _local(on) or ""
            # datatype restriction (tier = 'PREMIUM', amount >= 500, ...)
            if (on, RDF.type, OWL.DatatypeProperty) in g or \
                    (on, RDF.type, OWL.ObjectProperty) not in g:
                col = column_of(g, prop, prop)
                facets = _facets(g, member)
                if not facets:
                    raise Refusal(f":{concept} restriction on :{prop} carries no facet "
                                  f"(owl:withRestrictions / :minInclusive / owl:hasValue)")
                for op, value in facets:
                    parts.append(f"{col} {op} {value}")
                continue
            # object restriction:  ∃:placesOrder.(:Order ⊓ (:amount ≥ 500))  → EXISTS (…)
            some = next(iter(g.objects(member, OWL.someValuesFrom)), None)
            if some is None:
                raise Refusal(f":{concept} restriction on object property :{prop} has no "
                              f"owl:someValuesFrom — the object-restriction compiler only "
                              f"supports existential restrictions")
            target_cls, nested = _object_restriction_target(g, some)
            if target_cls is None:
                raise Refusal(f":{concept} object restriction on :{prop}: cannot identify the "
                              f"restricted CLASS inside owl:someValuesFrom — refusing rather "
                              f"than guessing")
            pred = _object_restriction_sql(g, prop, target_cls, nested)
            parts.append(pred)
    if not parts:
        raise Refusal(f":{concept} axiom has no compilable restriction")
    return " AND ".join(dict.fromkeys(parts)), []


def _member_predicate(g: Graph, concept: str, member) -> str:
    """One criterion of a union: a restriction (column op value) or a named class."""
    if (member, RDF.type, OWL.Restriction) in g:
        on = next(iter(g.objects(member, OWL.onProperty)), None)
        if on is None:
            raise Refusal(f":{concept}: a union member restriction has no owl:onProperty")
        prop = _local(on) or ""
        if (on, RDF.type, OWL.DatatypeProperty) in g or (on, RDF.type, OWL.ObjectProperty) not in g:
            col = column_of(g, prop, prop)
            facets = _facets(g, member)
            if not facets:
                raise Refusal(f":{concept}: the union member on :{prop} carries no facet")
            return " AND ".join(f"{col} {op} {value}" for op, value in facets)
        some = next(iter(g.objects(member, OWL.someValuesFrom)), None)
        if some is None:
            raise Refusal(f":{concept}: the union member on object property :{prop} has no "
                          f"owl:someValuesFrom")
        target_cls, nested = _object_restriction_target(g, some)
        if target_cls is None:
            raise Refusal(f":{concept}: cannot identify the restricted class inside a union member")
        return _object_restriction_sql(g, prop, target_cls, nested)
    name = _local(member)
    if name and (P(name), RDF.type, OWL.Class) in g:
        return concept_predicate(g, name)[0]
    raise Refusal(f":{concept}: a union member is neither a restriction nor a named class — "
                  f"refusing rather than dropping a criterion")


def _object_restriction_target(g: Graph, some) -> tuple[str | None, list]:
    """(class, extra restrictions) inside an owl:someValuesFrom expression.

    Accepts a named class, or an intersection of a named class and restrictions.
    """
    if (some, RDF.type, OWL.Class) in g and not list(g.objects(some, OWL.intersectionOf)):
        return _local(some), []
    for lst in g.objects(some, OWL.intersectionOf):
        items = list(g.items(lst))
        cls = None
        extra: list = []
        for item in items:
            if (item, RDF.type, OWL.Restriction) in g:
                extra.append(item)
            elif (item, RDF.type, OWL.Class) in g or (item, RDF.type, OWL.Class) not in g:
                if _local(item) and not list(g.objects(item, OWL.intersectionOf)):
                    cls = _local(item)
        if cls:
            return cls, extra
    return None, []


def _object_restriction_sql(g: Graph, prop: str, target_cls: str, nested: list) -> str:
    """Compile  ∃:prop.TargetClass  into a correlated EXISTS over the declared FK.

    The FK may live on either side:
      · :prop has :physicalColumn + :references (FK on the subject's side)
      · :prop owl:inverseOf Q, and Q has the FK (FK on the target's side)
    """
    base_cls = _local(next(iter(g.objects(P(prop), RDFS.domain)), None))
    if base_cls is None:
        raise Refusal(f":{prop} declares no rdfs:domain — cannot compile its restriction")
    base_table = table_of(g, base_cls)
    target_table = table_of(g, target_cls)
    base_pk = _one(g, P(base_cls), P("primaryKey"))
    target_pk = _one(g, P(target_cls), P("primaryKey"))

    fk = _one(g, P(prop), P("physicalColumn"))
    refs = _one(g, P(prop), P("references"))
    if fk and refs and _local(refs) == target_cls:
        # FK on the subject side: FROM base JOIN target ON base.fk = target.pk
        join = f"{base_table}.{fk} = {target_table}.{target_pk}"
        outer = f"EXISTS (SELECT 1 FROM {target_table} WHERE {join}"
    else:
        inv = next(iter(g.objects(P(prop), OWL.inverseOf)), None)
        if inv is None:
            raise Refusal(f":{prop} has no :physicalColumn/:references and no owl:inverseOf — "
                          f"cannot compile its object restriction (declare the FK)")
        inv_local = _local(inv) or ""
        ifk = _one(g, P(inv_local), P("physicalColumn"))
        iref = _local(next(iter(g.objects(P(inv_local), P("references"))), None))
        if not ifk or iref != base_cls:
            raise Refusal(f":{prop} inverse :{inv_local} does not point at :{base_cls} — "
                          f"cannot compile its object restriction")
        # FK on the target side: FROM base JOIN target ON target.fk = base.pk
        join = f"{target_table}.{ifk} = {base_table}.{base_pk}"
        outer = f"EXISTS (SELECT 1 FROM {target_table} WHERE {join}"

    preds = []
    for node in nested:
        on = next(iter(g.objects(node, OWL.onProperty)), None)
        if on is None:
            continue
        nprop = _local(on) or ""
        if not (on, RDF.type, OWL.DatatypeProperty) in g:
            raise Refusal(f":{prop} nested restriction on :{nprop}: only datatype "
                          f"restrictions are supported inside an object restriction")
        col = column_of(g, nprop, nprop)
        facets = _facets(g, node)
        if not facets:
            raise Refusal(f":{prop} nested restriction on :{nprop} carries no facet")
        for op, value in facets:
            preds.append(f"{target_table}.{col} {op} {value}")
    inner = " AND ".join(preds)
    return outer + (f" AND {inner}" if inner else "") + ")"


def class_assignment(g: Graph, concept: str) -> tuple[str, str, str]:
    """Derive the WRITE that makes an individual a member of :concept: (property, column, value).

    This is the write-side twin of `concept_sql`: the same `owl:equivalentClass` axiom that
    answers "who belongs to :{concept}?" for lane A/B is compiled here into the assignment
    "property = value" that CAUSES membership. Lane C effects therefore name a CLASS, not a
    column — change the axiom and the guard AND the effect move together (mutation M2).

    Only the `hasValue` shape is assignable: an axiom pinning the property to one value. A
    range/cardinality axiom makes membership a condition, not an assignment, and is refused
    BY NAME instead of guessing a value.
    """
    cls = P(concept)
    axioms = list(g.objects(cls, OWL.equivalentClass))
    if not axioms:
        raise Refusal(f":{concept} has no owl:equivalentClass axiom — no membership write "
                      f"can be derived")
    found: list[tuple[str, str, str]] = []
    for axiom in axioms:
        members: list = []
        for lst in g.objects(axiom, OWL.intersectionOf):
            members = list(g.items(lst))
        if not members:
            members = [axiom]
        for member in members:
            if (member, RDF.type, OWL.Restriction) not in g:
                continue
            on = next(iter(g.objects(member, OWL.onProperty)), None)
            if on is None:
                continue
            prop = _local(on) or ""
            facets = _facets(g, member)
            eq = [(op, v) for op, v in facets if op == "="]
            if len(eq) == 1 and len(facets) == 1:
                found.append((prop, column_of(g, prop, prop), eq[0][1]))
    if not found:
        raise Refusal(f":{concept} axiom is not a single `:property hasValue value` "
                      f"restriction — membership cannot be written as one assignment "
                      f"(declare an explicit effect `property: …, value: …` instead)")
    if len(set(found)) > 1:
        raise Refusal(f":{concept} axiom pins membership by MORE THAN ONE assignment "
                      f"{sorted(set(found))} — refusing to guess which one to write")
    return found[0]


FACETS = {
    str(XSD.minInclusive): ">=",
    str(XSD.maxInclusive): "<=",
    str(XSD.minExclusive): ">",
    str(XSD.maxExclusive): "<",
}


def _facets(g: Graph, node, depth: int = 0) -> list[tuple[str, str]]:
    """Every facet reachable from a restriction node, in any of the shapes this ontology uses.

    Measured shapes:
      · `owl:withRestrictions ( [ xsd:minInclusive "5000.0" ] )`   — directly on the restriction
      · `owl:someValuesFrom [ a rdfs:Datatype ; owl:withRestrictions ( … ) ]`  — nested,
        which is what :HighBalanceCustomer actually uses, and the reason an earlier
        version of this function reported "no facet" for a concept that has one.
    Anything else contributes nothing; the CALLER decides whether an empty facet list is a
    refusal (it is).
    """
    if depth > 5:
        return []
    out: list[tuple[str, str]] = []
    for pred, value in g.predicate_objects(node):
        op = FACETS.get(str(pred))
        if op:
            out.append((op, f"{value}"))
            continue
        if pred == OWL.hasValue:
            out.append(("=", f"'{value}'"))
            continue
        if pred in (OWL.withRestrictions, OWL.someValuesFrom, OWL.allValuesFrom):
            if pred == OWL.withRestrictions:
                for item in g.items(value):
                    out += _facets(g, item, depth + 1)
            else:
                out += _facets(g, value, depth + 1)
    return out


def concept_base_class(g: Graph, concept: str) -> str | None:
    """The class a defined concept's axiom is built ON (:PremiumCustomer -> :Customer).

    That class is where the predicate's columns live, so it decides whether a metric over
    the OTHER class needs a join.
    """
    cls = P(concept)
    for axiom in g.objects(cls, OWL.equivalentClass):
        for lst in g.objects(axiom, OWL.intersectionOf):
            for member in g.items(lst):
                if (member, RDF.type, OWL.Restriction) not in g and _local(member):
                    return _local(member)
    sub = next(iter(g.objects(cls, RDFS.subClassOf)), None)
    return _local(sub)


def relationship(g: Graph, from_cls: str, to_cls: str) -> tuple[str, str]:
    """(foreign-key column on the FROM side, primary-key column on the TO side).

    Declared by an owl:ObjectProperty with :physicalColumn (the FK) and :references (the
    target class). Nothing is inferred from column-name coincidence: a join that is not
    declared is refused by name, so the ontology stays the only source of the join graph.
    """
    for prop in g.subjects(RDF.type, OWL.ObjectProperty):
        dom = _local(next(iter(g.objects(prop, RDFS.domain)), None))
        rng = _local(next(iter(g.objects(prop, RDFS.range)), None))
        if dom != from_cls or rng != to_cls:
            continue
        if _one(g, prop, P("references")) is None:
            raise Refusal(f":{_local(prop)} crosses :{from_cls} -> :{to_cls} but declares no "
                          f":references — a join without a declared relationship is a guess")
        fk = _one(g, prop, P("physicalColumn"))
        if not fk:
            raise Refusal(f":{_local(prop)} crosses :{from_cls} -> :{to_cls} but declares no "
                          f":physicalColumn (the FK lives on the :{from_cls} side)")
        pk = _one(g, P(to_cls), P("primaryKey"))
        if not pk:
            raise Refusal(f":{to_cls} declares no :primaryKey — cannot build a join target")
        return fk, pk
    raise Refusal(f"no declared relationship :{from_cls} -> :{to_cls} (add an owl:ObjectProperty "
                  f"with :physicalColumn + :references) — refused rather than guessed")


def class_columns(g: Graph, cls: str) -> dict[str, str]:
    """property name -> physical column, for one class (its own :physicalColumn set)."""
    out: dict[str, str] = {}
    for prop in g.subjects(RDF.type, OWL.DatatypeProperty):
        dom = next(iter(g.objects(prop, RDFS.domain)), None)
        if _local(dom) != cls:
            continue
        col = _one(g, prop, P("physicalColumn"))
        if col:
            out[_local(prop) or ""] = col
    return out


def _expand(g: Graph, cls: str, ident: str, depth: int = 0) -> str:
    """Resolve one identifier used in a formula, or refuse by name.

    Order (first hit wins, and nothing is guessed):
      1. a physical column of this class            -> the column
      2. a MEMBER reference (a property with :formula) -> expand its formula recursively
      3. a declared count (:aggregate "count")      -> `count(*)`
      4. anything else                              -> Refusal naming the identifier
    """
    if depth > 5:
        raise Refusal(f"formula expansion recursed too deep at {ident!r} (cycle?)")
    columns = class_columns(g, cls)
    if ident in columns:
        return columns[ident]
    props = {_local(p): p for p in g.subjects(RDF.type, OWL.DatatypeProperty)}
    # an explicitly declared member alias (migration residue, see metrics_ext.ttl)
    node = props.get(ident)
    if node is None:
        for owner, _, alias in g.triples((None, P("memberAlias"), None)):
            if str(alias) == ident:
                alias_of = _local(owner)
                ALIAS_NOTES.append(f"{ident!r} is a declared alias of :{alias_of}")
                node = props.get(alias_of or "")
                if node is None:
                    raise Refusal(f"alias {ident!r} points at :{alias_of}, which is not a declared property")
                ident = alias_of or ident
                break
    if node is not None:
        formula = _one(g, node, P("formula"))
        aggregate = _one(g, node, P("aggregate"))
        if formula:
            expr = re.sub(r"\{([a-z_]+)\}", lambda mm: _expand(g, cls, mm.group(1), depth + 1), formula)
            return "(" + re.sub(r"[a-z_][a-z0-9_]*",
                                lambda mm: _expand(g, cls, mm.group(0), depth + 1)
                                if mm.group(0) not in SQL_WORDS else mm.group(0), expr) + ")"
        if aggregate == "count":
            return "count(*)"
    if ident in SQL_WORDS:
        return ident
    raise Refusal(f"formula mentions {ident!r}, which is neither a column of {cls} "
                  f"({sorted(columns)}), a declared member, nor a declared count — "
                  f"refused rather than guessed")


def _expr(g: Graph, m: Metric) -> str:
    """Expand `:formula` into SQL through the ontology. Nothing is typed twice: the
    threshold `5000` appears only in the concept axiom, the columns only in Tier A."""
    if not m.formula:
        raise Refusal(f":{m.name} declares no :formula")
    cls = m.domain or m.grain
    if cls is None:
        raise Refusal(f":{m.name} declares neither :domain nor :grain")
    expanded = re.sub(r"\{([a-z_]+)\}", lambda mm: _expand(g, cls, mm.group(1)), m.formula)
    return re.sub(r"[a-z_][a-z0-9_]*",
                  lambda mm: mm.group(0) if mm.group(0) in SQL_WORDS else _expand(g, cls, mm.group(0)),
                  expanded)


SQL_WORDS = {"case", "when", "then", "else", "end", "and", "or", "not", "null", "is",
             "cast", "as", "numeric", "float", "int", "true", "false", "distinct"}


@dataclass
class Compiled:
    metric: str
    sql: str
    notes: list[str]


def time_column(g: Graph, grain_cls: str | None, depth: int = 2) -> tuple[str | None, str]:
    """The column a TimeWindow filters on, DECLARED per class (`:timeColumn`).

    Why this is not one global name: a window filters a fact's own time column, and different
    ontologies have different ones — retail's orders have `placed_at`, logistics' trips have
    `trip_date`, complaints have `opened_at`. The first version of the slot mechanism hard-coded
    `placed_at`, so declaring `:supportsSlot :TimeWindow` in logistics produced
    `column "placed_at" does not exist` for every metric: a slot that could only ever fail.

    Resolution order, each step declared rather than guessed:
      1. `:timeColumn` on the metric's own grain class;
      2. `:timeColumn` on a class reachable through a declared relationship (stops have no time of
         their own — their trip does), `depth` hops at most;
      3. nothing → (None, reason), and a TimeWindow request is then REFUSED by name instead of being
         silently dropped.
    """
    if not grain_cls:
        return None, "the metric declares no :grain"
    own = _one(g, P(grain_cls), P("timeColumn"))
    if own:
        return own, f":timeColumn on :{grain_cls}"
    # A time column on ANOTHER class is not usable as a filter here: pushing `WHERE trips.trip_date`
    # onto a query whose FROM is `stops` produced `column "trip_date" does not exist` — the predicate
    # needs a JOIN the compiler did not emit, and adding joins by string surgery is how a number goes
    # quietly wrong. So the window works on a grain that declares its own :timeColumn, and the
    # refusal names the column that exists one hop away (that is the backlog item, stated).
    nearest: str | None = None
    for target, entry in _closure(g, grain_cls, depth).items():
        edges = (entry or {}).get("edges") or []
        if target == grain_cls or not edges:
            continue
        col = _one(g, P(target), P("timeColumn"))
        if not col:
            continue
        via = " → ".join([grain_cls] + [edge[1] for edge in edges])
        nearest = f":{target}.{col} (reached via {via})"
        break
    return None, (f":{grain_cls} declares no :timeColumn"
                  + (f"; the nearest one is {nearest}, but a window cannot be pushed down through "
                     f"another table yet — the compiler would have to add that join, and it does "
                     f"not" if nearest else " and no class reachable from it declares one"))


def _apply_filters(sql: str, filters: dict, time_col: str | None = None,
                   time_how: str = "") -> str:
    """Push declared slot filters into the compiled statement.

    Only called after capability.resolve() proved the metric declares each slot. The
    predicates are appended inside the single statement (before LIMIT/tail), and the
    values travel as bound parameters — the SQL text itself never contains data.

    The time window needs `time_col`: a metric that declares the slot for a grain with no declared
    time column is REFUSED here, because dropping the constraint would answer a different question.
    """
    if not filters:
        return sql
    preds = []
    if filters.get("customer_id") is not None:
        preds.append("customer_id = %(customer_id)s")
    if filters.get("since") is not None or filters.get("until") is not None:
        if not time_col:
            raise Refusal("this metric declares the TimeWindow slot but no time column is declared "
                          f"for its grain ({time_how or 'no :timeColumn'}) — refusing rather than "
                          "answering without the window")
        if filters.get("since") is not None:
            preds.append(f"{time_col} >= %(since)s")
        if filters.get("until") is not None:
            preds.append(f"{time_col} < %(until)s")
    if not preds:
        return sql
    frag = " AND ".join(preds)
    if " WHERE " in sql:
        return sql.replace(" WHERE ", f" WHERE {frag} AND ", 1)
    return sql.replace(";", f" WHERE {frag};", 1)


def _literal(value) -> str:
    """A filter value as a SQL literal, from a DECLARED group key only.

    The value always comes from a grouped metric's returned key (the dashboard refuses a value that
    is not in that set), so this is not a user string reaching SQL — but it is still quoted properly:
    a dimension filter that can be used for injection would be the one hole in "the ontology is the
    only writer of SQL".
    """
    if value is None or (isinstance(value, str) and value.lower() in ("null", "none")):
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def _dimension_predicate(g: Graph, grain_cls: str, prop: str, value) -> str:
    """`SELECT f0.<pk> FROM <grain> f0 JOIN … WHERE <owner>.<column> = <value>` for one dimension.

    EVERY table in the subquery is aliased (f0, t0, t1 …). The first version joined on bare table
    names, so the ON clause referred to the OUTER `trips` instead of the subquery's own row — the
    correlation made the statement unplannable and a compile-and-run timed out after 60 s.
    """
    paths = _closure(g, grain_cls)
    owners = [cls for cls in paths if prop in class_columns(g, cls)]
    if not owners:
        raise Refusal(f"cannot filter :{grain_cls} by :{prop} — it is not a column of :{grain_cls} or "
                      f"of any class reachable through declared relationships "
                      f"({sorted(paths)}), so this panel cannot be cut that way")
    if len(owners) > 1:
        raise Refusal(f"cannot filter :{grain_cls} by :{prop} — it is a column of MORE THAN ONE "
                      f"class ({owners}); refusing rather than picking one")
    owner = owners[0]
    grain_table = table_of(g, grain_cls)
    grain_pk = _one(g, P(grain_cls), P("primaryKey"))
    if not grain_pk or "," in grain_pk:
        raise Refusal(f"cannot filter :{grain_cls} — a filter needs a single-column :primaryKey "
                      f"(got {grain_pk!r})")

    sql = f"SELECT f0.{grain_pk} FROM {grain_table} f0"
    alias = {grain_cls: "f0"}
    for i, (dom, rng, fks, refs, extras) in enumerate(paths[owner]["edges"]):
        here = f"t{i}"
        on = " AND ".join(f"{alias[dom]}.{fk} = {here}.{ref}"
                          for fk, ref in zip(fks, refs))
        on += _render_join_extra(extras, alias[dom], here)
        sql += f" JOIN {table_of(g, rng)} {here} ON {on}"
        alias[rng] = here
    lit = _literal(value)
    column = f"{alias[owner]}.{class_columns(g, owner)[prop]}"
    pred = f"{column} IS NULL" if lit is None else f"{column} = {lit}"
    return f"{sql} WHERE {pred}"


def apply_dimension_filters(g: Graph, sql: str, grain_cls: str,
                            filters: dict[str, object]) -> tuple[str, list[str]]:
    """Narrow a compiled metric to declared dimension VALUES — on every grain relation in the SQL.

    Why a SEMIJOIN instead of an `AND` appended to the WHERE: a ratio is compiled as TWO aggregate
    subqueries (`(SELECT … FROM trips) / (SELECT … FROM trips)`), and appending one predicate to the
    first WHERE would filter the numerator only — the classic "silently wrong rate". Rewriting each
    `FROM <grain>` into a derived table with the SAME NAME puts the constraint everywhere the grain is
    read, and every outer `trips.col` reference keeps working:

        FROM trips   →   FROM (SELECT * FROM trips WHERE trips.id IN (SELECT f0.id FROM trips f0
                                                    JOIN routes ON … WHERE routes.version = 'v2')) trips
    """
    if not filters:
        return sql, []
    grain_table = table_of(g, grain_cls)
    grain_pk = _one(g, P(grain_cls), P("primaryKey"))
    preds = {prop: _dimension_predicate(g, grain_cls, prop, value) for prop, value in filters.items()}
    if not preds:
        return sql, []
    # the predicate is a SUBQUERY: it becomes `<grain>.<pk> IN (…)`, not a bare expression
    combined = " AND ".join(f"{grain_table}.{grain_pk} IN ({sub})" for sub in preds.values())
    needle = f"FROM {grain_table}"
    occurrences = sql.count(needle)
    if not occurrences:
        raise Refusal(f":{grain_cls} (table {grain_table}) does not appear in the compiled SQL — "
                      f"cannot apply the filter, and dropping it would answer a different question")
    replaced = sql.replace(
        needle,
        f"FROM (SELECT * FROM {grain_table} WHERE {combined}) {grain_table}")
    notes = [f"dimension filter pushed into {occurrences} grain relation(s): "
             + ", ".join(f"{p}={v!r}" for p, v in filters.items())]
    return replaced, notes


def compile_metric(g: Graph, name: str, *, customer_id=None, since=None, until=None,
                   dim_filters: dict[str, object] | None = None) -> Compiled:
    raw = _compile_metric_raw(g, name)
    filters = {k: v for k, v in (("customer_id", customer_id), ("since", since),
                                 ("until", until)) if v is not None}
    if not filters:
        if not dim_filters:
            return raw
        grain_cls = _local(_one(g, P(name), P("grain")))
        out, dim_notes = apply_dimension_filters(g, raw.sql, grain_cls or "", dim_filters)
        return Compiled(raw.metric, out, raw.notes + dim_notes)
    notes = raw.notes + [f"slots pushed down: {sorted(filters)}"]
    time_col, time_how = (None, "")
    if since is not None or until is not None:
        # the grain is stored as a full IRI; time_column() works in local class names
        grain_cls = _local(_one(g, P(name), P("grain")))
        time_col, time_how = time_column(g, grain_cls)
        if time_col:
            notes.append(f"window column: {time_col} — {time_how}")
    out = _apply_filters(raw.sql, filters, time_col, time_how)
    if dim_filters:
        grain_cls = _local(_one(g, P(name), P("grain")))
        out, dim_notes = apply_dimension_filters(g, out, grain_cls or "", dim_filters)
        notes.extend(dim_notes)
    return Compiled(raw.metric, out, notes)


# ------------------------------------------------------------------ multi-hop joins
def _idents(text: str | None) -> set[str]:
    return set(re.findall(r"[a-z_][a-z0-9_]*", (text or "").lower())) - SQL_WORDS


_JOIN_EXTRA_TOKEN = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


def _render_join_extra(extras, dom_table: str, rng_table: str) -> str:
    """`{d}.col = …` → the real table names, joined with AND. Empty list → empty string."""
    out = ""
    for extra in extras or []:
        rendered = (str(extra)
                    .replace("{d}", dom_table)
                    .replace("{r}", rng_table))
        out += " AND " + rendered
    return out


def _check_join_extra(g: Graph, prop, dom: str, rng: str, fks: list, refs: list, extra: str) -> None:
    """Refuse a `:joinExtra` that names a column neither side has, or forgets its placeholders.

    A join predicate is SQL, so a typo in it fails at RUN time as "column does not exist" — which
    reads like a broken database instead of a broken declaration. Checking the identifiers against
    both sides here keeps the failure at compile time and names the declaration.
    """
    seen = set(_JOIN_EXTRA_TOKEN.findall(extra))
    unknown = seen - {"d", "r"}
    if unknown:
        raise Refusal(f":{_local(prop)} :joinExtra uses unknown placeholder(s) {sorted(unknown)} — "
                      f"only {{d}} (the domain table) and {{r}} (the range table) are available")
    allowed = set(class_columns(g, dom).values()) | set(class_columns(g, rng).values())
    # String literals are VALUES, not columns: `side = 'front'` must not look for a column
    # called `front`. Strip them (SQL-style doubled quotes included) before looking at tokens.
    bare_sql = re.sub(r"'(?:[^']|'')*'", " ", str(extra))
    bare_sql = re.sub(r"\{[a-z_][a-z0-9_]*\}", " ", bare_sql)   # {d}/{r} are tables, not columns
    for ident in sorted(_idents(bare_sql)):
        if ident in allowed:
            continue
        # `case`/`when`/`then`/`else`/`end` and string literals are SQL, not columns.
        if ident in {"case", "when", "then", "else", "end", "and", "or", "not", "in", "null",
                     "true", "false", "like", "is", "distinct"}:
            continue
        raise Refusal(f":{_local(prop)} :joinExtra mentions {ident!r}, which is a column of "
                      f"neither :{dom} nor :{rng} ({sorted(allowed)[:8]}…) — refusing")


def _closure(g: Graph, cls: str, depth: int = 6) -> dict[str, dict]:
    """Declared-relationship BFS from a class: {class: path-edges-from-start}.

    Edges are the same `owl:ObjectProperty` declarations the capability graph uses
    (:physicalColumn FK + :references). No edge ⇒ no path ⇒ the metric is refused.
    """
    edges = []
    for prop in g.subjects(RDF.type, OWL.ObjectProperty):
        dom = _local(next(iter(g.objects(prop, RDFS.domain)), None))
        # `rdfs:range` is not required: the skill tells a builder to write
        # ":physicalColumn <fk> ; :references :Target", and that IS the range. Requiring a second
        # declaration made the closure ignore every such link — measured on new_coldchain_v6, whose
        # 21 links all say exactly that, so ":"damagedBoxesPer1kStopsByVehicle groups by :vehiclePlate"
        # refused with "not ... of any class reachable through declared relationships (['Stop'])" while
        # the path Stop→Trip→Vehicle was declared the whole time.
        rng = (_local(next(iter(g.objects(prop, RDFS.range)), None))
               or _local(_one(g, prop, P("references"))))
        fk = _one(g, prop, P("physicalColumn"))
        if not (dom and rng and fk and _one(g, prop, P("references"))):
            continue
        # a composite FK names both sides: :physicalColumn "a, b" + :referencesKey "x, y".
        # Without the second half the join would silently compare only the first column.
        fks = [c.strip() for c in str(fk).split(",") if c.strip()]
        keyed = _one(g, prop, P("referencesKey"))
        refs = ([c.strip() for c in str(keyed).split(",") if c.strip()] if keyed
                else [c.strip() for c in (str(_one(g, P(rng), P("primaryKey")) or "")
                                          .split(",")) if c.strip()])
        if len(fks) != len(refs):
            raise Refusal(f":{_local(prop)} declares {len(fks)} FK column(s) but {len(refs)} "
                          f"key column(s) on :{rng} — a join needs both sides to match")
        # `:joinExtra` — an extra predicate ON the join, for relationships a column EQUALITY
        # cannot express. Measured on eff_ops_v1 (team-3's 產出標工): the standard-hours row is
        # keyed (part_no, side), and which side a production row needs is decided by its
        # work-center description — `side = CASE WHEN work_center_desc='前工序' THEN 'front'
        # ELSE 'back' END`. Declared as a plain equality the join either misses every packaging
        # row (−29.4% of i) or doubles it (+100%); only the conditional form reproduces the
        # client's 5,771.679. The predicate is SQL the declaration owns, rendered with {d} = the
        # domain table and {r} = the range table, and it is validated against both sides'
        # columns here so a typo is a refusal at compile time, not a number at run time.
        extras = [str(v).strip() for v in g.objects(prop, P("joinExtra")) if str(v).strip()]
        for extra in extras:
            _check_join_extra(g, prop, dom, rng, fks, refs, extra)
        edges.append((dom, rng, fks, refs, prop, extras))
    paths: dict[str, dict] = {cls: {"edges": []}}
    frontier = [cls]
    for _ in range(depth):
        nxt = []
        for cur in frontier:
            for dom, rng, fks, refs, prop, extras in edges:
                if dom != cur or rng in paths:
                    continue
                paths[rng] = {"edges": paths[cur]["edges"] + [(dom, rng, fks, refs, extras)]}
                nxt.append(rng)
        frontier = nxt
        if not frontier:
            break
    return paths


def _owners(g: Graph, closure: dict, ident: str) -> list[str]:
    """Which closure classes own a formula identifier (column)."""
    return [cls for cls in closure
            if ident in {c for c in class_columns(g, cls).values()}]


def _qualify(sql: str, table: str, cols: set[str]) -> str:
    """Prefix bare column tokens with their table, keep string literals untouched."""
    out = []
    for tok in re.split(r"('(?:[^']|'')*')", sql):
        if tok.startswith("'"):
            out.append(tok)
        else:
            for col in cols:
                tok = re.sub(rf"(?<![A-Za-z0-9_.]){re.escape(col)}(?![A-Za-z0-9_])",
                             f"{table}.{col}", tok)
            out.append(tok)
    return "".join(out)


def _compile_grouped_metric(g: Graph, m: Metric) -> Compiled:
    """GROUP BY metric: "revenue by city", "revenue by product", "by product AND city".

    `:groupBy` may be declared more than once; each names a property (on THIS class or on a
    class reachable through declared relationships). The compiler joins to every property's
    owner and emits SELECT k1, [k2,] agg(value) ... GROUP BY k1[, k2] ORDER BY agg DESC.
    """
    name = m.name
    grain = m.grain or m.domain or ""
    grain_table = table_of(g, grain)
    paths = _closure(g, grain)
    if not m.group_by and not m.time_bucket:
        raise Refusal(f":{name} declares no :groupBy (and no :timeBucket) — a metric with no "
                      f"dimension is a single number, not a grouped one")

    groups: list[tuple[str, str, str]] = []      # (prop, owner class, column)
    for prop in m.group_by:
        owners = [cls for cls in paths if prop in class_columns(g, cls)]
        # THE GRAIN'S OWN COLUMN WINS. Two tables can carry the same column name (routes.planned_stops
        # and trips.planned_stops both exist), so once the closure is real a dimension that lives on
        # the grain itself must not become "ambiguous" because a joined class happens to reuse the
        # name. Measured on new_coldchain_v6: the fix that taught the closure to read `:references`
        # as the target made :avgStopsPerTrip refuse "planned_stops ... a column of MORE THAN ONE
        # joined class (['Trip', 'Route'])" — a correct-looking refusal for a column the metric names
        # on its own grain.
        if grain in owners:
            owners = [grain]
        if not owners:
            raise Refusal(f":{name} groups by :{prop}, which is not a column of :{grain} "
                          f"or of any class reachable through declared relationships "
                          f"({sorted(paths)}) — refusing rather than guessing")
        if len(owners) > 1:
            raise Refusal(f":{name} groups by :{prop}, which is a column of MORE THAN ONE "
                          f"class ({owners}) — ambiguous; refusing")
        groups.append((prop, owners[0], class_columns(g, owners[0])[prop]))

    # A TIME AXIS IS DECLARED, NEVER INFERRED. `:timeBucket "week"` becomes the FIRST key,
    # date_trunc('week', <the grain's own :timeColumn>), and the result is ordered by that key
    # ASCENDING — a series whose x axis is sorted by its own y value is not a time series.
    # The bucket column obeys the same rule as the TimeWindow slot: the grain's OWN :timeColumn.
    # A column one hop away cannot be bucketed without the compiler adding that join, so it is
    # refused BY NAME with the column that does exist (the backlog item, stated).
    bucket = (m.time_bucket or "").strip().lower() or None
    if bucket and bucket not in TIME_BUCKETS:
        raise Refusal(f":{name} declares :timeBucket {m.time_bucket!r}; this compiler emits "
                      f"{list(TIME_BUCKETS)} — refusing rather than passing the word through "
                      f"to date_trunc and failing at run time")
    bucket_key = None
    if bucket:
        own_col, why = time_column(g, grain)
        if not own_col:
            raise Refusal(f":{name} declares :timeBucket {bucket!r} but {why} — a time series "
                          f"needs a bucketable column on the grain itself")
        bucket_key = f"date_trunc('{bucket}', {grain_table}.{own_col})"

    tables: dict[str, str] = {grain: grain_table}
    join_edges: list[tuple[str, str, list, list, list]] = []

    def add_joins_for(target: str) -> None:
        if target == grain:
            return
        for dom, rng, fks, refs, extras in paths[target]["edges"]:
            if rng in tables:
                continue
            tables[rng] = table_of(g, rng)
            join_edges.append((dom, rng, fks, refs, extras))

    for _, owner, _ in groups:
        add_joins_for(owner)
    # a `:where` class may have no axiom at all (a declared predicate): then its columns are
    # the GRAIN's own columns, so the predicate is qualified against the grain table. Without
    # this the grouped path looked up ``tables[None]`` and raised KeyError instead of compiling.
    where_class = concept_base_class(g, m.where) if m.where else None
    if m.where and where_class is None:
        where_class = grain
        notes_declared = True
    if where_class:
        if where_class not in paths:
            raise Refusal(f":{name} filters on :{where_class}, which is not reachable from "
                          f":{grain} through declared relationships")
        add_joins_for(where_class)

    # value expression: columns of any joined class, each resolved to its owner
    #
    # SORTED, not set order: `_idents` returns a set, so the REFUSAL for an unknown identifier named
    # whichever token the hash order surfaced first — the same declaration refused with "mentions
    # 'from'" in one process and "mentions 'epoch'" in another. A refusal message that changes between
    # runs cannot be gated on, and cannot be quoted in a backlog.
    def _qualify_formula(label: str, body: str) -> str:
        # WHERE "THE GRAIN WINS" APPLIES, AND WHERE IT DOES NOT.
        #
        # A formula that is NOTHING BUT a column name is a value OF THIS GRAIN's row — there is no
        # second table in the expression, so the grain's own column is the only reading and picking
        # it is not a guess. Measured: new_coldchain's `:plannedStopsTotal` / `:avgStopsPerTrip` are
        # `:formula "planned_stops"` on grain Trip, while `routes` carries a column of the same name;
        # refusing those would refuse correct declarations that pass today.
        #
        # In an expression with more than one identifier the compiler cannot know which table a
        # shared name means, and guessing silently changes the number: retail's
        # `premiumProductRevenue` (`qty * price` over order_lines JOIN products) compiled
        # `qty * order_lines.price` for a `price` declared on BOTH sides. check_metrics' J6 mutation
        # asserts that refusal, so the rule is gated, not stylistic.
        bare = len(_idents(body)) == 1
        for ident in sorted(_idents(body)):
            owners_id = [cls for cls in tables if ident in class_columns(g, cls).values()]
            if not owners_id:
                raise Refusal(f":{label} formula mentions {ident!r}, not a column of the joined "
                              f"classes {sorted(tables)} — refusing")
            if len(owners_id) > 1 and bare and grain in owners_id:
                owners_id = [grain]
            if len(owners_id) > 1:
                raise Refusal(f":{label} formula column {ident!r} is ambiguous across "
                              f"{owners_id} — refusing")
            body = re.sub(rf"(?<![A-Za-z0-9_.]){re.escape(ident)}(?![A-Za-z0-9_])",
                          f"{tables[owners_id[0]]}.{ident}", body)
        return body

    pred_q = None
    if m.where:
        pred = concept_sql(g, m.where)
        pred_q = _qualify(pred, tables[where_class],
                          set(class_columns(g, where_class).values()))
    where_sql = f" WHERE {pred_q}" if pred_q else ""
    keys = ([bucket_key] if bucket_key else []) + [f"{tables[owner]}.{col}"
                                                   for _prop, owner, col in groups]

    def _emit(agg: str) -> str:
        """The full SELECT once every JOIN the branch needed has been declared.

        Built this late on purpose: a ratio's second side can add a join (a FILTER predicate on
        another class), and a join list snapshotted before that would emit a query referring to a
        table that was never joined.
        """
        join_sql = grain_table
        joined = {grain}
        for dom, rng, fks, refs, extras in join_edges:
            if rng in joined:
                continue
            on = " AND ".join(f"{tables[dom]}.{fk} = {tables[rng]}.{ref}"
                              for fk, ref in zip(fks, refs))
            on += _render_join_extra(extras, tables[dom], tables[rng])
            join_sql += f" JOIN {tables[rng]} ON {on}"
            joined.add(rng)
        key_selects = ", ".join(f"{k} AS {_snake(name)}_key{i + 1}" for i, k in enumerate(keys))
        order = "1 ASC" if bucket_key else f"{len(keys) + 1} DESC"
        return (f"SELECT {key_selects}, {agg} AS {_snake(name)} "
                f"FROM {join_sql}{where_sql} GROUP BY {', '.join(keys)} ORDER BY {order};")

    # ── a RATE per group ───────────────────────────────────────────────────
    # `:aggregate "ratio_of_sums"` used to be refused the moment a :groupBy appeared, which left
    # every per-vehicle / per-route RATE undeclarable — and a dashboard's whole point is "per what".
    # A grouped ratio is legitimate ONLY when both sides live at the SAME grain: then a group's rate
    # is (numerator summed inside the group) / (denominator summed inside the group). A cross-grain
    # ratio (complaints per km: complaints at :Complaint, km at :Trip) has no per-group denominator
    # that is not a choice, so it stays REFUSED, by name, saying which grains disagree.
    if m.aggregate == "ratio_of_sums":
        if not (m.numerator and m.denominator):
            raise Refusal(f":{name} declares :aggregate \"ratio_of_sums\" without "
                          f":numerator/:denominator — the denominator must be declared")

        def _side(side_name: str) -> str:
            side = metrics(g).get(side_name)
            if side is None:
                raise Refusal(f":{name} names :{side_name} in :numerator/:denominator, but no "
                              f"such metric is declared")
            side_grain = side.grain or side.domain or ""
            if side_grain != grain:
                raise Refusal(
                    f":{name} is a ratio grouped by a dimension, but :{side_name} counts at "
                    f":{side_grain} while the metric's grain is :{grain} — a grouped ratio "
                    f"compiles only when both sides share the grain (otherwise a group's "
                    f"denominator is a choice, not a number); refusing rather than dividing "
                    f"two differently-grouped numbers")
            if side.numerator or side.denominator:
                raise Refusal(f":{name} divides by :{side_name}, which is itself a ratio — a "
                              f"ratio of ratios has no declared :scale; refusing")
            if side.additivity == "non-additive" and side.aggregate == "sum":
                raise Refusal(f":{side_name} is non-additive; :aggregate \"sum\" contradicts "
                              f":additivity")
            filt = ""
            # `:concept` OR `:where` — the ungrouped path reads `m.concept or m.where`, because a
            # metric may carry its predicate either as a concept (compiled FROM the axiom, e.g.
            # :onTimeStops) or as a bare declared filter (:overloadedTrips). Reading only `:where`
            # here compiled :stopOnTimeRateByRouteVersion to count()/count() = 100%: a SILENT wrong
            # number rather than a refusal. Both paths read the same two fields now.
            side_concept = side.concept or side.where
            if side_concept:
                base = concept_base_class(g, side_concept) or grain
                if base not in paths:
                    raise Refusal(f":{name}: :{side_name} filters on :{base}, which is not "
                                  f"reachable from :{grain} through declared relationships")
                add_joins_for(base)
                pred_side = concept_sql(g, side_concept)
                filt = " FILTER (WHERE %s)" % _qualify(pred_side, tables[base],
                                                       set(class_columns(g, base).values()))
            if side.aggregate == "count":
                return f"count(DISTINCT {_pk_expr(g, grain, grain_table)}){filt}"
            if side.aggregate == "sum":
                if not side.formula:
                    raise Refusal(f":{side_name} declares :aggregate \"sum\" but no :formula")
                return f"sum({_qualify_formula(side_name, side.formula)}){filt}"
            raise Refusal(f":{name}: :{side_name} has :aggregate {side.aggregate!r}; a grouped "
                          f"ratio needs count or sum on both sides — refusing")

        body = f"(({_side(m.numerator)})::numeric) / NULLIF(({_side(m.denominator)}), 0)"
        if m.scale:
            body = f"({m.scale}) * ({body})"
        notes = [f"grouped by {', '.join(':' + p for p, _, _ in groups) or '(nothing)'}"
                 + (f" · :timeBucket {bucket!r} on {grain_table}" if bucket else "")
                 + f" (owners {sorted({o for _, o, _ in groups})}, joined via declared relationships)",
                 f"grouped ratio: (:{m.numerator}) / (:{m.denominator}), both declared at :{grain}"]
        if m.scale:
            notes.append(f"scaled by {m.scale} (declared :scale)")
        return Compiled(name, _emit(body), notes)

    expr = _qualify_formula(name, m.formula or "")

    if m.additivity == "non-additive" and m.aggregate == "sum":
        raise Refusal(f":{name} is non-additive; :aggregate \"sum\" contradicts :additivity")
    if m.aggregate == "sum":
        agg = f"sum({expr})"
    elif m.aggregate in {"avg", "min", "max"}:
        agg = f"{m.aggregate}({expr})"
    elif m.aggregate == "count":
        agg = f"count(DISTINCT {_pk_expr(g, grain, grain_table)})"
    else:
        raise Refusal(f":{name}: :aggregate {m.aggregate!r} with :groupBy is not supported "
                      f"(sum/count/avg/min/max are)")
    notes = [f"grouped by {', '.join(':' + p for p, _, _ in groups) or '(nothing)'}"
             + (f" · :timeBucket {bucket!r} on {grain_table}" if bucket else "")
             + f" (owners {sorted({o for _, o, _ in groups})}, joined via declared relationships)"]
    return Compiled(name, _emit(agg), notes)


def _compile_cross_metric(g: Graph, m: Metric) -> Compiled:
    """A metric whose formula and/or filter live on OTHER classes: compile the join path.

    Example (the video's 4-table case):
        :premiumProductRevenue  grain :OrderLine  where :PremiumCustomer
                                formula "qty * price"
      → order_lines JOIN orders ON order_lines.order_id = orders.id
                   JOIN customers ON orders.customer_id = customers.id
                   JOIN products ON order_lines.product_id = products.id
        WHERE customers.tier = 'PREMIUM'   sum(order_lines.qty * products.price)
    """
    name = m.name
    grain = m.grain or m.domain or ""
    grain_table = table_of(g, grain)
    paths = _closure(g, grain)
    where_class = concept_base_class(g, m.where) if m.where else None

    for target in ([where_class] if where_class else []):
        if target not in paths:
            raise Refusal(f":{name} needs :{grain} -> :{target} but the ontology declares "
                          f"no relationship path (no :references edge) — refusing rather "
                          f"than guessing a join")

    # which tables participate: grain + every formula identifier's owner + the where base
    tables: dict[str, str] = {grain: grain_table}
    join_edges: list[tuple[str, str, list, list, list]] = []

    def add_joins_for(target: str) -> None:
        if target == grain:
            return
        for dom, rng, fks, refs, extras in paths[target]["edges"]:
            if rng in tables:
                continue
            tables[rng] = table_of(g, rng)
            join_edges.append((dom, rng, fks, refs, extras))

    if where_class:
        add_joins_for(where_class)
    formula_owners: dict[str, str] = {}
    # Same rule as `_compile_grouped_metric`'s `_qualify_formula`: a ONE-TOKEN formula is a value of
    # the grain's own row (the grain's column wins, because there is no second table in the
    # expression); a MULTI-TOKEN formula has to have every column unambiguous, because picking one
    # of two joined tables silently changes the number.
    bare = len(_idents(m.formula)) == 1
    for ident in _idents(m.formula):
        owners = _owners(g, paths, ident)
        if len(owners) > 1 and bare and grain in owners:
            owners = [grain]
        if not owners:
            raise Refusal(f":{name} formula mentions {ident!r}, which is not a column of "
                          f":{grain} or of any class reachable through declared relationships "
                          f"({sorted(paths)}) — refusing rather than guessing")
        if len(owners) > 1:
            raise Refusal(f":{name} formula mentions {ident!r}, which is a column of MORE "
                          f"THAN ONE joined class ({owners}) — ambiguous; refusing rather "
                          f"than guessing")
        formula_owners[ident] = owners[0]
        add_joins_for(owners[0])

    # predicate and formula columns must be unambiguous across the joined tables
    used_cols: dict[str, str] = {}
    for ident, owner in formula_owners.items():
        used_cols[ident] = tables[owner]
    pred = None
    if m.where:
        pred = concept_sql(g, m.where)
    if pred:
        for col in re.findall(r"[a-z_][a-z0-9_]*", pred.lower()):
            for cls, table in tables.items():
                if col in class_columns(g, cls).values():
                    if col in used_cols and used_cols[col] != table:
                        raise Refusal(f":{name}: column {col!r} is owned by both "
                                      f"{used_cols[col]!r} and {table!r} — ambiguous across the "
                                      f"join; refusing rather than guessing")
                    used_cols[col] = table

    expr = m.formula
    for ident in _idents(m.formula):
        col = class_columns(g, formula_owners[ident]).get(
            next(p for p, c in class_columns(g, formula_owners[ident]).items()
                 if c == ident), ident)
        expr = re.sub(rf"(?<![A-Za-z0-9_.]){re.escape(ident)}(?![A-Za-z0-9_])",
                      f"{tables[formula_owners[ident]]}.{ident}", expr)
    pred_q = (_qualify(pred, tables[where_class], set(class_columns(g, where_class).values()))
              if pred and where_class else None)

    join_sql = grain_table
    joined = {grain}
    for dom, rng, fks, refs, extras in join_edges:
        if rng in joined:
            continue
        on = " AND ".join(f"{tables[dom]}.{fk} = {tables[rng]}.{ref}"
                          for fk, ref in zip(fks, refs))
        on += _render_join_extra(extras, tables[dom], tables[rng])
        join_sql += f" JOIN {tables[rng]} ON {on}"
        joined.add(rng)
    where_sql = f" WHERE {pred_q}" if pred_q else ""
    notes = [f"cross-class join over {len(joined)} tables via declared relationships"]
    if m.additivity == "non-additive" and m.aggregate == "sum":
        raise Refusal(f":{name} is non-additive; :aggregate \"sum\" contradicts :additivity")
    if m.aggregate == "sum" and expr:
        return Compiled(name, f"SELECT sum({expr}) AS {_snake(name)} FROM {join_sql}{where_sql};",
                        notes)
    if m.aggregate == "count":
        # a metric that says `:counts :Customer` counts the JOINED target, not the grain
        if m.counts and where_class and where_class in tables:
            target, target_table = where_class, tables[where_class]
        else:
            target, target_table = grain, grain_table
        return Compiled(name, f"SELECT count(DISTINCT {_pk_expr(g, target, target_table)}) AS "
                              f"{_snake(name)} FROM {join_sql}{where_sql};")
    if m.aggregate in {"avg", "min", "max"} and expr:
        return Compiled(name, f"SELECT {m.aggregate}({expr}) AS {_snake(name)} "
                              f"FROM {join_sql}{where_sql};", notes)
    raise Refusal(f":{name}: :aggregate {m.aggregate!r} with a cross-class formula is not "
                  f"supported (sum/count/avg/min/max are)")


def _compile_metric_raw(g: Graph, name: str) -> Compiled:
    m = metrics(g).get(name)
    if m is None:
        raise Refusal(f"no metric :{name} declared in the ontology")
    if ":grain" in m.missing:
        raise Refusal(f":{name} declares no :grain — an aggregate needs the object grain "
                      f"it is counted at (this is what Cube held implicitly)")
    if ":universe" in m.missing:
        raise Refusal(f":{name} declares no :universe — the denominator must be declared")
    table = table_of(g, m.grain or "")
    cls = m.domain or m.grain or ""
    notes: list[str] = []

    # multi-hop is needed only when a formula column lives OUTSIDE the grain class, or
    # when the :where base class has no DIRECT declared relationship with the grain
    # (a one-hop join is already handled by the single-hop compiler below).
    if m.group_by or m.time_bucket:
        return _compile_grouped_metric(g, m)

    if m.numerator and m.denominator:
        # a CROSS-GRAIN ratio: each side is a full compiled metric (different tables)
        if m.numerator == name or m.denominator == name:
            raise Refusal(f":{name} cannot reference itself in :numerator/:denominator")
        num = _compile_metric_raw(g, m.numerator).sql.rstrip(";")
        den = _compile_metric_raw(g, m.denominator).sql.rstrip(";")
        notes.append(f"cross-grain ratio: (:{m.numerator}) / (:{m.denominator})")
        # cast the numerator: two bigint counts would integer-divide to 0 (a rate of 0.37
        # would report as 0 — the silent-zero failure this repo keeps catching)
        expr = f"(({num})::numeric) / NULLIF(({den}), 0)"
        if m.scale:
            expr = f"({m.scale}) * ({expr})"
            notes.append(f"scaled by {m.scale} (declared :scale)")
        return Compiled(name, f"SELECT {expr} AS {_snake(name)};", notes)

    cross_needed = False
    if m.formula:
        try:
            _expr(g, m)          # a single-hop expansion succeeds -> no cross join needed
        except Refusal:
            cross_needed = True
    where_base = concept_base_class(g, m.where) if m.where else None
    if where_base and where_base != m.grain:
        try:
            relationship(g, m.grain or "", where_base)
        except Refusal:
            cross_needed = True
    if cross_needed:
        return _compile_cross_metric(g, m)

    expr = _expr(g, m) if m.formula else None
    if m.additivity == "non-additive" and m.aggregate == "sum":
        raise Refusal(f":{name} is non-additive; :aggregate \"sum\" contradicts :additivity "
                      f"— refuse rather than emit a wrong total")
    # JOIN: a :where concept whose axiom is built on another class (e.g. PremiumCustomer
    # is built on Customer while the facts are Orders at grain :Order). The join comes from
    # the DECLARED relationship (:physicalColumn FK + :references), never from guessing.
    where_class = concept_base_class(g, m.where) if m.where else None
    from_sql, from_table = table, table
    collide: set[str] = set()
    if m.where and where_class and where_class != (m.grain or cls):
        pred = concept_sql(g, m.where)
        notes.append(f"where :{m.where} joins :{m.grain} -> :{where_class} via a declared "
                     f"relationship")
        target_table = table_of(g, where_class)
        fk, pk = relationship(g, m.grain or cls, where_class)
        collide = (set(class_columns(g, m.grain or cls).values()) &
                   set(class_columns(g, where_class).values()))
        collide -= {pk} if pk != fk else set()
        if collide:
            raise Refusal(f":{name}: joined predicate is built on :{where_class} but the columns "
                          f"{sorted(collide)} exist on BOTH sides — an unqualified predicate "
                          f"would be ambiguous; refused rather than guessed")
        from_sql = f"{table} JOIN {target_table} ON {table}.{fk} = {target_table}.{pk}"
        where_sql = f" WHERE {pred}"
    elif m.where:
        pred = concept_sql(g, m.where)
        where_sql = f" WHERE {pred}"
    else:
        where_sql = ""
    fanout = "JOIN" in from_sql
    if m.aggregate in {"sum", "avg", "min", "max"} and expr is None:
        raise Refusal(f":{m.name} declares no :formula — {m.aggregate} needs the value to "
                      f"aggregate over")
    if m.aggregate == "sum":
        return Compiled(m.name,
                        f"SELECT sum({expr}) AS {_snake(m.name)} FROM {from_sql}{where_sql};",
                        notes)
    if m.aggregate == "ratio_of_sums":
        num, _, den = expr.rpartition(" / ")
        if not num:
            raise Refusal(f":{m.name} is a ratio but its formula has no `num / den` shape")
        num_expr = _wrap_aggregate(g, cls, num, "sum")
        den_expr = den.strip()
        if "count(*)" not in den_expr:
            den_expr = _wrap_aggregate(g, cls, den_expr, "sum")
        notes.append("non-additive: emitted as a ratio of SUMS, not avg() of per-line values")
        return Compiled(
            m.name,
            f"SELECT {num_expr} / NULLIF({den_expr}, 0) AS {_snake(m.name)} FROM {from_sql}{where_sql};",
            notes,
        )
    if m.aggregate == "count":
        # count of a concept at a grain: if the concept's class is not the grain, the join
        # fans the grain out over the target, so count DISTINCT target pk (fan-out safe).
        concept = m.concept or m.where
        if concept:
            pred = concept_sql(g, concept)
            base = concept_base_class(g, concept) or (m.grain or cls)
            notes.append(f"predicate compiled from :{concept} axiom")
            if base != (m.grain or cls):
                target_table = table_of(g, base)
                if not fanout:
                    fk, pk = relationship(g, m.grain or cls, base)
                    from_sql = f"{table} JOIN {target_table} ON {table}.{fk} = {target_table}.{pk}"
                    where_sql = f" WHERE {pred}"
                pk = _one(g, P(base), P("primaryKey"))
                collide = (set(class_columns(g, m.grain or cls).values()) &
                           set(class_columns(g, base).values())) - {pk}
                if collide:
                    raise Refusal(f":{name}: joined predicate is built on :{base} but the columns "
                                  f"{sorted(collide)} exist on BOTH sides — an unqualified "
                                  f"predicate would be ambiguous; refused rather than guessed")
                notes.append(f"counted at :{base} with count(DISTINCT {_pk_expr(g, base, target_table)}) — "
                             f"fan-out safe")
                return Compiled(
                    m.name,
                    f"SELECT count(DISTINCT {_pk_expr(g, base, target_table)}) AS {_snake(m.name)} "
                    f"FROM {from_sql}{where_sql};", notes)
            return Compiled(
                m.name,
                f"SELECT count(*) AS {_snake(m.name)} FROM {table} WHERE {pred};", notes)
        return Compiled(m.name,
                        f"SELECT count(*) AS {_snake(m.name)} FROM {from_sql}{where_sql};",
                        notes)
    if m.aggregate in {"avg", "min", "max"}:
        return Compiled(m.name,
                        f"SELECT {m.aggregate}({expr}) AS {_snake(m.name)} FROM {from_sql}{where_sql};",
                        notes)
    raise Refusal(f":{name} declares :aggregate {m.aggregate!r}, which this generator does "
                  f"not know — named, never coerced")


def main() -> int:
    """CLI: compile/evaluate metrics without Cube.

        sqlgen.py --list                 compile every declared metric
        sqlgen.py --list --run           ... and evaluate it on the demo DB
        sqlgen.py --metric NAME          one metric (SQL + notes)
        sqlgen.py --metric NAME --run    ... and its live value
        sqlgen.py --list --no-overlay    what the ontology says when Cube's implicit
                                         :aggregate/:grain/:universe are REMOVED
    """
    import argparse
    ap = argparse.ArgumentParser(description="compile ontology metrics to SQL (no Cube)")
    ap.add_argument("--metric", help="metric name (single)")
    ap.add_argument("--list", action="store_true", help="compile every declared metric")
    ap.add_argument("--run", action="store_true", help="evaluate the compiled SQL on the DB")
    ap.add_argument("--no-overlay", action="store_true",
                    help="drop metrics_ext.ttl (the declarations Cube held implicitly)")
    ap.add_argument("--ontology-dir", default=str(pathlib.Path(__file__).parent / "ontology"))
    ap.add_argument("--dsn", default="retail_db@127.0.0.1:15432")
    args = ap.parse_args()

    reconfigure(ns="https://cube.local/ontology/retail#", ontology_dir=args.ontology_dir)
    g = load(with_overlay=not args.no_overlay)
    conn = None
    if args.run:
        import psycopg2
        dbname, _, hostport = args.dsn.partition("@")
        host, _, port = hostport.partition(":")
        conn = psycopg2.connect(host=host or "127.0.0.1", port=int(port or 15432),
                                dbname=dbname, user="postgres", password="postgres")
        cur = conn.cursor()
    names = [args.metric] if args.metric else list(metrics(g))
    if not names:
        print("no metrics declared (overlay off? see --no-overlay)", file=sys.stderr)
        return 1
    rc = 0
    for name in names:
        try:
            c = compile_metric(g, name)
        except Refusal as exc:
            print(f"{name}: REFUSED — {str(exc).splitlines()[0]}")
            rc = 2                      # a refusal is a result: exit 2, like actions.py
            continue
        print(c.sql)
        for n in c.notes:
            print(f"  note: {n}")
        if conn is not None:
            import guard
            g = guard.run(cur, c.sql, mode="declared")
            if g["notes"] or g.get("plan_rows"):
                print(f"  guard: {guard.report(g)}")
            if " GROUP BY " in c.sql:
                for row in g["rows"]:
                    key = " / ".join(str(x) for x in row[:-1])
                    print(f"  {key}: {row[-1]}")
            else:
                print(f"  value: {g['rows'][0][0] if g['rows'] else None}")
    if conn is not None:
        conn.rollback()
        conn.close()
    return rc


def _wrap_aggregate(g: Graph, cls: str, expr: str, agg: str) -> str:
    """Aggregate a formula fragment, expanding member references inside it first."""
    expanded = re.sub(r"[a-z_][a-z0-9_]*",
                      lambda mm: mm.group(0) if mm.group(0) in SQL_WORDS
                      else _expand(g, cls, mm.group(0)),
                      expr.strip())
    if "count(*)" in expanded:          # already an aggregate
        return expanded
    return f"{agg}({expanded})"


def _pk_expr(g: Graph, cls: str, table: str | None = None) -> str:
    """The class's identity as one SQL expression.

    A single-column key stays `table.col`; a COMPOSITE key becomes `(a, b)`, which is what
    `count(DISTINCT …)` needs on Postgres (count(DISTINCT x, y) is not a function there).
    """
    pk = str(_one(g, P(cls), P("primaryKey")) or "id")
    cols = [c.strip() for c in pk.split(",") if c.strip()]
    table = table or table_of(g, cls)
    if len(cols) == 1:
        return f"{table}.{cols[0]}"
    return "(" + ", ".join(f"{table}.{c}" for c in cols) + ")"


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


if __name__ == "__main__":
    sys.exit(main())

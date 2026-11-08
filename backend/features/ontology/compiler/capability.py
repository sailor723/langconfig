#!/usr/bin/env python3
"""capability.py — the capability graph: what this ontology can ANSWER or DO, and the
PATH that proves it, replacing the `if kind == ...` dispatch with graph resolution.

The graph is DERIVED from the same TTL / actions.yml the compilers read — never hand-written:

    metric  --measures--> class        (from :domain/:grain)
    metric  --filters-->  class        (from :where's base class, the join predicate's owner)
    class   --physicalTable--> table   (from :physicalTable; a defined class via its base)
    class   --joins--> class           (owl:ObjectProperty + :physicalColumn FK + :references)
    action  --appliesTo--> class       (from actions.yml applies_to)

Resolution = node lookup + path existence:

    intent {kind, name} -> node  (not on the menu -> refuse by name)
    metric  -> needs measures/filters edges AND every class on them must reach a table AND
               a compiled SQL must exist (declared but refused -> refuse with that reason)
    class   -> needs a table (own :physicalTable or its base class's)
    action  -> needs an appliesTo edge to a class with a table

nl.py then dispatches through a registry (`EXECUTORS[node["kind"]]`) — no if/elif chain
on the intent kind. A new kind of capability = new node type + one registry entry.
"""
from __future__ import annotations

import os
import sys

from rdflib import OWL, RDF, RDFS, URIRef

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import actions  # noqa: E402
import sqlgen   # noqa: E402

P = sqlgen.P


class CapabilityError(Exception):
    """Result, not error: the ontology cannot answer this intent, and Says Why."""


def _table_of(graph, cls: str) -> str | None:
    table = sqlgen._one(graph, P(cls), P("physicalTable"))
    if table is None:
        base = sqlgen.concept_base_class(graph, cls)
        if base:
            table = sqlgen._one(graph, P(base), P("physicalTable"))
    return table


def build(graph, menu_: dict) -> dict:
    """Nodes = menu entries; edges = the declared paths that make them executable."""
    nodes: dict[tuple[str, str], dict] = {}
    edges: list[dict] = []

    metrics_meta = sqlgen.metrics(graph)
    for m in menu_["metrics"]:
        meta = metrics_meta.get(m["name"])
        nodes[("metric", m["name"])] = {"kind": "metric", "name": m["name"],
                                        "sql": m.get("sql"),
                                        "refused": m.get("refused"),
                                        "grain": meta.grain if meta else None,
                                        "where": (sqlgen.concept_base_class(graph, meta.where)
                                                  if meta and meta.where else None)}
    for c in menu_["classes"]:
        nodes[("class", c["name"])] = {"kind": "class", "name": c["name"],
                                       "predicate": c.get("predicate")}
    for a in menu_["actions"]:
        nodes[("action", a["name"])] = {"kind": "action", "name": a["name"],
                                        "applies_to": a["applies_to"],
                                        "parameters": a["parameters"]}

    # metric -> class edges (their meaning, from the TTL declarations)
    metrics = sqlgen.metrics(graph)
    for name, m in metrics.items():
        cls = m.domain or m.grain
        if cls:
            edges.append({"src": name, "dst": cls, "kind": "measures"})
        if m.where:
            # A `:where` class that is a DECLARED PREDICATE (:physicalPredicate, no axiom) has no
            # base class: its columns are the GRAIN's own, which is the rule the compiler already
            # applies (`where_class = concept_base_class(...) or grain`). The capability graph used
            # to put such a class in the `filters` edge and then fail `_reach_table` on it — measured
            # on new_coldchain_v6: every metric whose :where is a declared predicate refused
            # ":overloadedTrips filters :OverloadedTrip, but that class reaches no physical table",
            # while the same metric compiled and ran. The NL/Query path (this graph) disagreed with
            # the compiler about the same declaration.
            base = (sqlgen.concept_base_class(graph, m.where)
                    or (m.grain or m.domain)
                    or m.where)
            edges.append({"src": name, "dst": base, "kind": "filters"})

    # class -> table edges
    for (kind, name) in list(nodes):
        if kind != "class":
            continue
        table = _table_of(graph, name)
        if table:
            edges.append({"src": name, "dst": table, "kind": "physicalTable"})

    # class -> class joins (declared relationships)
    for prop in graph.subjects(RDF.type, OWL.ObjectProperty):
        dom = sqlgen._local(next(iter(graph.objects(prop, RDFS.domain)), None))
        rng = sqlgen._local(next(iter(graph.objects(prop, RDFS.range)), None))
        fk = sqlgen._one(graph, prop, P("physicalColumn"))
        if dom and rng and fk and sqlgen._one(graph, prop, P("references")):
            edges.append({"src": dom, "dst": rng, "kind": "joins",
                          "via": sqlgen._local(prop), "fk": fk})

    # slot nodes are DECLARED in the TTL (:isSlot), so an unsupported slot still exists
    # as a node — that is what makes "does not support TimeWindow" a precise refusal.
    for cls in graph.subjects(RDF.type, OWL.Class):
        if sqlgen._one(graph, cls, P("isSlot")) == "true":
            slot_name = sqlgen._local(cls)
            nodes.setdefault(("slot", slot_name), {"kind": "slot", "name": slot_name})

    # slot nodes + metric -> slot edges (:supportsSlot)
    for (kind, name) in list(nodes):
        if kind != "metric":
            continue
        for slot in graph.objects(P(name), P("supportsSlot")):
            slot_name = sqlgen._local(slot)
            if not slot_name:
                continue
            nodes.setdefault(("slot", slot_name),
                             {"kind": "slot", "name": slot_name})
            edges.append({"src": name, "dst": slot_name, "kind": "supportsSlot"})

    # action -> class edges
    for (kind, name) in list(nodes):
        if kind != "action":
            continue
        applied = nodes[(kind, name)]["applies_to"]
        edges.append({"src": name, "dst": applied, "kind": "appliesTo"})

    return {"nodes": nodes, "edges": edges}


def _out(cap: dict, src: str, kinds: set[str]) -> list[dict]:
    return [e for e in cap["edges"] if e["src"] == src and e["kind"] in kinds]


def _reach_table(cap: dict, cls: str) -> dict | None:
    """The path from a class to its physical table (defined classes bind via their base)."""
    direct = _out(cap, cls, {"physicalTable"})
    return direct[0] if direct else None


def resolve(intent: dict, cap: dict) -> dict:
    """Validate the intent against the graph; return {node, path, table} or raise."""
    kind, name = intent["kind"], intent["name"]
    node = cap["nodes"].get((kind, name))
    if node is None:
        avail = sorted(name for (_kind, name) in cap["nodes"].keys())
        raise CapabilityError(f"{kind} {name!r} is not on the capability graph — refusing "
                              f"rather than guessing (nodes: {avail})")
    _check_slots(cap, intent, kind, name)
    if kind == "metric":
        if node.get("refused"):
            raise CapabilityError(f":{name} is declared but refused by the compiler: "
                                  f"{node['refused']}")
        if not node.get("sql"):
            raise CapabilityError(f":{name} has no compiled SQL — cannot answer")
        path = _out(cap, name, {"measures", "filters"})
        if not path:
            raise CapabilityError(f":{name} has no measures/filters edge to a class — "
                                  f"nothing proves it is answerable")
        for edge in path:
            table_edge = _reach_table(cap, edge["dst"])
            if table_edge is None:
                raise CapabilityError(f":{name} {edge['kind']} :{edge['dst']}, but that class "
                                      f"reaches no physical table — refusing instead of emitting "
                                      f"a wrong query")
            path = path + [table_edge] if table_edge not in path else path
        # append the DECLARED join chain (grain → … → where base) so the provenance
        # shows every table the metric touches, not just the one-hop table edges
        joins = _join_chain(cap, node.get("grain"), node.get("where"))
        path = path + joins if joins else path
        return {"node": node, "path": path, "table": None}
    if kind == "class":
        table_edge = _reach_table(cap, name)
        if table_edge is None:
            raise CapabilityError(f":{name} reaches no physical table — cannot answer")
        return {"node": node, "path": [table_edge], "table": table_edge["dst"]}
    if kind == "action":
        path = _out(cap, name, {"appliesTo"})
        if not path:
            raise CapabilityError(f":{name} has no appliesTo edge — cannot dry-run")
        table_edge = _reach_table(cap, path[0]["dst"])
        if table_edge is None:
            raise CapabilityError(f":{name} applies to :{path[0]['dst']}, but that class reaches "
                                  f"no physical table — refusing")
        return {"node": node, "path": path + [table_edge], "table": table_edge["dst"]}
    raise CapabilityError(f"unknown capability kind {kind!r}")


def _join_chain(cap: dict, src: str | None, dst: str | None) -> list[dict]:
    """BFS over the declared class→class joins edges; [] when no path or nothing to join."""
    if not src or not dst or src == dst:
        return []
    seen = {src}
    frontier = [(src, [])]
    while frontier:
        nxt = []
        for node, acc in frontier:
            for e in cap["edges"]:
                if e["kind"] != "joins" or e["src"] != node or e["dst"] in seen:
                    continue
                if e["dst"] == dst:
                    return acc + [e]
                seen.add(e["dst"])
                nxt.append((e["dst"], acc + [e]))
        frontier = nxt
    return []


def _check_slots(cap: dict, intent: dict, kind: str, name: str) -> None:
    """Every requested slot must have a :supportsSlot edge from THIS node.

    A slot request with no edge is refused by name — the silent alternative would be to
    ignore the constraint and answer a different question (e.g. "last month" answered as
    "all time"), which is exactly the failure this project treats as a bug.
    """
    for slot in (intent.get("slots") or {}):
        have = [e for e in _out(cap, name, {"supportsSlot"}) if e["dst"] == slot]
        if not have:
            supported = sorted(e["dst"] for e in _out(cap, name, {"supportsSlot"}))
            raise CapabilityError(
                f":{name} does not support the {slot} slot (declared slots: "
                f"{supported or 'none'}) — refusing rather than ignoring the constraint")


def edges_text(plan: dict) -> list[str]:
    """The path as lines for provenance/UI."""
    return [f"{e['src']} -{e['kind']}-> {e['dst']}"
            + (f" ({e['via']}: {e['fk']})" if e.get("via") else "")
            for e in plan["path"]]

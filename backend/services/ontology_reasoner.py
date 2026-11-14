"""The tutorial's window onto the reasoner: the same question, before and after entailment.

The authored chapters for `talent_v1` teach one thing — that the useful answer is **entailed, not
stored** — and a page cannot teach that with a static picture: it has to run the query over `abox.ttl`
and then over the same graph plus the type assertions HermiT derived, and print both counts.

    GET /api/ontology/talent_v1/reason?class_name=matches_业务跟单&limit=5
    {"asserted": 0, "entailed": 47, "added": 247, "rows": [...], "engine": "hermit", "elapsed_ms": 3216}

Two properties are deliberate:

  * **it answers only for a profile that HAS an ABox** — a profile with no `abox.ttl` gets a 404 naming
    that fact, never an empty "0 → 0" that reads like "nothing matched";
  * **the reasoner is cached per profile+file-hash** for this process, because every chapter in the
    tutorial asks the same question and 3.2 s of HermiT per page view is a bad way to teach patience.

The counts are the measurement, not decoration: `asserted 0` is the whole point.
"""
from __future__ import annotations

import json
import logging
import pathlib
import threading

logger = logging.getLogger(__name__)


class Unavailable(Exception):
    """This ontology has no ABox, so there is nothing to reason over (a 404, by name)."""


#: (key, abox hash, reasoning hash) -> the reasoning result and the derived membership
_CACHE: dict[tuple[str, str, str], dict] = {}
_LOCK = threading.Lock()


def _profile_dir(key: str) -> pathlib.Path:
    from services import ontology_pages
    try:
        return ontology_pages._profile(key).parent
    except Exception as exc:                                    # noqa: BLE001
        raise Unavailable(str(exc)) from exc


def _files(key: str) -> tuple[pathlib.Path, pathlib.Path, dict]:
    base = _profile_dir(key)
    settings_path = next(iter(sorted(base.glob("*_settings.json"))), None) or base / "settings.json"
    if not settings_path.is_file():
        raise Unavailable(f"{key} has no settings file")
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    abox = (base / (settings.get("abox") or "abox.ttl")).resolve()
    axioms = (base / (settings.get("reasoning") or "reasoning.ttl")).resolve()
    if not (abox.is_file() and axioms.is_file()):
        raise Unavailable(
            f"{key} declares no ABox (needs abox.ttl + reasoning.ttl), so there is nothing to reason over")
    return abox, axioms, settings


def _signature(path: pathlib.Path) -> str:
    stat = path.stat()
    return f"{stat.st_size}:{int(stat.st_mtime)}:{path}"


def reasoned(key: str) -> dict:
    """{classes: [...], members: {...}, engine, elapsed_ms, consistent} — cached per file state."""
    abox, axioms, settings = _files(key)
    cache_key = (key, _signature(abox), _signature(axioms))
    with _LOCK:
        cached = _CACHE.get(cache_key)
    if cached is not None:
        return cached

    import sys

    backend = pathlib.Path(__file__).resolve().parents[1]
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    from features.ontology.reasoning import reasoner as R

    usable, why = R.available()
    if not usable:
        raise Unavailable(f"the reasoner is unavailable: {why}")

    ns = (settings.get("ns") or "").rstrip("#") + "#"
    graph = R.load_graph([axioms, abox])
    classes = sorted({str(node) for node in graph.subjects(None, None)
                      if str(node).startswith(ns)})
    # only the DEFINED classes (a match class carries `owl:equivalentClass`); reasoning over structure
    # classes would return their asserted members and blur the very distinction this page teaches
    from rdflib import URIRef
    from rdflib.namespace import OWL

    defined = [c for c in classes
               if list(graph.objects(URIRef(c), OWL.equivalentClass))]
    result = R.reason(graph, watch_classes=defined)
    payload = {"classes": defined, "members": result.members, "engine": result.engine,
               "elapsed_ms": round(result.elapsed_ms, 1), "consistent": result.consistent,
               "ns": ns, "graph_size": len(graph)}
    with _LOCK:
        _CACHE[cache_key] = payload
    return payload


def reason_view(key: str, class_name: str, limit: int = 5) -> dict:
    """The tutorial's payload: how many the ABox asserts vs how many the reasoner entails."""
    payload = reasoned(key)
    ns = payload["ns"]
    classes = payload["classes"]
    chosen = class_name.strip()
    if chosen:
        iri = chosen if chosen.startswith("http") else ns + chosen
        if iri not in classes:
            raise Unavailable(
                f"{key} has no defined class {chosen!r} (known: "
                + ", ".join(c.rsplit('#', 1)[-1] for c in classes) + ")")
    else:
        iri = classes[0] if classes else ""
    members = payload["members"].get(iri) or []
    asserted = 0
    if iri:
        import sys

        backend = pathlib.Path(__file__).resolve().parents[1]
        if str(backend) not in sys.path:
            sys.path.insert(0, str(backend))
        from features.ontology.reasoning import reasoner as R

        abox, axioms, _settings = _files(key)
        graph = R.load_graph([axioms, abox])
        from rdflib import URIRef
        from rdflib.namespace import RDF

        asserted = len(list(graph.subjects(RDF.type, URIRef(iri))))
    return {
        "class": iri.rsplit("#", 1)[-1],
        "asserted": asserted,
        "entailed": len(members),
        "added": sum(len(v) for v in payload["members"].values()),
        "rows": [m.rsplit("#", 1)[-1] for m in members[: max(1, limit)]],
        "classes": [c.rsplit("#", 1)[-1] for c in classes],
        "engine": payload["engine"],
        "elapsed_ms": payload["elapsed_ms"],
        "consistent": payload["consistent"],
    }

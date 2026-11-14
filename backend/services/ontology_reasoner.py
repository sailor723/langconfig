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


def layers(key: str) -> dict:
    """The three layers, counted: axioms, individuals, entailments. Live, never typed in."""
    payload = reasoned(key)
    import sys

    backend = pathlib.Path(__file__).resolve().parents[1]
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    from rdflib import Graph
    from rdflib.namespace import OWL, RDF

    abox, axioms, _settings = _files(key)
    tbox = Graph(); tbox.parse(str(axioms), format="turtle")
    data = Graph(); data.parse(str(abox), format="turtle")
    defined = [c for c in tbox.subjects(RDF.type, OWL.Class)
               if list(tbox.objects(c, OWL.equivalentClass))]
    return {
        "tbox": {"triples": len(tbox),
                 "classes": len(list(tbox.subjects(RDF.type, OWL.Class))),
                 "defined": len(defined),
                 "restrictions": len(list(tbox.subjects(RDF.type, OWL.Restriction))),
                 "facets": len([1 for t in tbox if str(t[1]).endswith("minInclusive")])},
        "abox": {"triples": len(data),
                 "individuals": len(set(data.subjects(RDF.type, None))),
                 "type_assertions": len(list(data.triples((None, RDF.type, None))))},
        "entailed": {"total": sum(len(v) for v in payload["members"].values()),
                     "classes": len(payload["classes"])},
        "engine": payload["engine"], "elapsed_ms": payload["elapsed_ms"],
        "consistent": payload["consistent"],
    }


def why(key: str, candidate: str, role: str) -> dict:
    """Why this person clears this role: the facts that matched, the thresholds that passed, the axiom.

    HermiT does not hand back a proof tree, and it does not need to: the axioms are OURS, so naming the
    one that fired plus the facts it consumed IS the justification a recruiter can read.
    """
    payload = reasoned(key)
    ns = payload["ns"]
    cls = role if role.startswith("matches_") else f"matches_{role}"
    iri = ns + cls
    if iri not in payload["classes"]:
        raise Unavailable(f"{key} has no defined class {cls!r}")
    member = f"{ns}{candidate}" if not candidate.startswith("http") else candidate
    if member not in set(payload["members"].get(iri) or []):
        raise Unavailable(f"{candidate} is not a member of {cls}")

    import sys

    backend = pathlib.Path(__file__).resolve().parents[1]
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    from rdflib import Graph, Literal, URIRef
    from rdflib.namespace import RDF

    abox, axioms, _settings = _files(key)
    data = Graph(); data.parse(str(abox), format="turtle")
    tbox = Graph(); tbox.parse(str(axioms), format="turtle")

    node = URIRef(member)
    skills = sorted(str(o).rsplit("#", 1)[-1] for o in data.objects(node, URIRef(ns + "hasSkill")))
    categories = {}
    for skill in skills:
        for t in data.objects(URIRef(ns + skill), RDF.type):
            cat = str(t).rsplit("#", 1)[-1]
            if cat not in ("SkillTag", "NamedIndividual"):
                categories.setdefault(skill, cat)
    years = next((int(v) for v in data.objects(node, URIRef(ns + "yearsExperience"))
                  if isinstance(v, Literal)), None)
    rank = next((int(v) for v in data.objects(node, URIRef(ns + "educationRank"))
                 if isinstance(v, Literal)), None)
    role_name = cls[len("matches_"):]
    role_node = URIRef(ns + "role_" + role_name)
    required_years = next((int(v) for v in data.objects(role_node, URIRef(ns + "requiredYears"))
                           if isinstance(v, Literal)), None)
    required_rank = next((int(v) for v in data.objects(role_node, URIRef(ns + "requiredEducationRank"))
                          if isinstance(v, Literal)), None)
    # the definition as written, printed so the page can show the sentence that fired
    lines = [f":{cls} a owl:Class ;", "    owl:equivalentClass [ owl:intersectionOf ("]
    for t in tbox.triples((URIRef(iri), None, None)):
        lines.append(f"        # {t[1].rsplit('#', 1)[-1]} {str(t[2])[:80]}")
    lines.append("    ) ] .")
    return {
        "candidate": candidate.rsplit("#", 1)[-1], "role": cls,
        "skills": skills, "skill_categories": categories,
        "years": years, "required_years": required_years,
        "education_rank": rank, "required_education_rank": required_rank,
        "facts": [
            f":hasSkill {'/'.join(sorted(categories.values())) or '(none)'}",
            f":yearsExperience {years} (门槛 {required_years})" if required_years is not None
            else f":yearsExperience {years} (门槛 未声明)",
            f":educationRank {rank} (下限 {required_rank})" if required_rank is not None
            else f":educationRank {rank} (下限 未声明)",
        ],
        "axiom": "\n".join(lines),
        "engine": payload["engine"],
    }


def reason_view(key: str, class_name: str, limit: int = 5,
                drop: str = "", candidate: str = "") -> dict:
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
    if drop:
        # FALSIFICATION on demand. A membership that survives the removal of its definition was never
        # reasoned — that is A7 of check_abox, and here the reader can press the button themselves.
        import sys

        backend = pathlib.Path(__file__).resolve().parents[1]
        if str(backend) not in sys.path:
            sys.path.insert(0, str(backend))
        from features.ontology.reasoning import reasoner as R

        abox, axioms, _settings = _files(key)
        graph = R.load_graph([axioms, abox])
        if drop == "definition":
            mutated, removed = R.mutate(graph, subject=iri.rsplit("#", 1)[-1],
                                        predicate="equivalentClass", namespace=ns)
        elif drop == "skills":
            mutated, removed = R.mutate(graph, subject=candidate.rsplit("#", 1)[-1],
                                        predicate="hasSkill", namespace=ns)
        else:
            raise Unavailable(f"unknown drop {drop!r} (known: definition, skills)")
        after = R.reason(mutated, watch_classes=[iri])
        left = after.members_of(iri)
        return {"class": iri.rsplit("#", 1)[-1], "drop": drop, "removed": removed,
                "before": len(members), "after": len(left),
                "rows": [m.rsplit("#", 1)[-1] for m in left[: max(1, limit)]],
                "engine": after.engine, "elapsed_ms": round(after.elapsed_ms, 1),
                "consistent": after.consistent}

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


def sparql(key: str, query: str, limit: int = 25) -> dict:
    """Run one SPARQL twice — over the ABox as written, then over it plus the entailed types.

    This is what makes a tutorial about REASONING honest: a chapter can print the query it used and both
    answers, so a reader sees the `0 → N` transition rather than being told about it. Read-only by
    construction — the graph is parsed into memory and nothing is written back.
    """
    payload = reasoned(key)
    ns = payload["ns"]
    import sys

    backend = pathlib.Path(__file__).resolve().parents[1]
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    from rdflib import Graph, URIRef
    from rdflib.namespace import RDF

    abox, axioms, _settings = _files(key)
    text = (query or "").replace("PREFIX : ", f"PREFIX : <{ns}> ")
    if "PREFIX" not in text.upper():
        text = f"PREFIX : <{ns}>\n" + text

    asserted_graph = Graph()
    for prefix, iri in [(p, n) for p, n in [("", ns)]]:
        asserted_graph.bind("", iri)
    asserted_graph.parse(str(abox), format="turtle")

    def rows_of(graph) -> list[list[str]]:
        try:
            result = graph.query(text)
        except Exception as exc:                                    # noqa: BLE001
            return [[f"QUERY ERROR: {type(exc).__name__}: {exc}"]]
        out = []
        for row in result:
            out.append([str(v).rsplit("#", 1)[-1] for v in row])
            if len(out) >= limit:
                break
        return out

    before = rows_of(asserted_graph)
    entailed_graph = Graph()
    for triple in asserted_graph:
        entailed_graph.add(triple)
    added = 0
    for cls in payload["classes"]:
        for member in payload["members"].get(cls) or []:
            triple = (URIRef(member), RDF.type, URIRef(cls))
            if triple not in entailed_graph:
                entailed_graph.add(triple)
                added += 1
    after = rows_of(entailed_graph)
    return {"asserted": len(before), "entailed": len(after), "added_types": added,
            "before": before, "after": after, "query": text,
            "ns": ns, "engine": payload["engine"], "elapsed_ms": payload["elapsed_ms"]}

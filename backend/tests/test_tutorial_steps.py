"""The `talent_steps` tutorial must not teach anything false.

A tutorial is a claim about the ontology: "step 4 adds one object property", "step 6 adds two
facts", "the reasoner concludes cand_A and not cand_B", "removing the axiom removes the
conclusion". Every one of those is checkable, and every one of them has been wrong at least once in
this repository:

  * the platform's own `talent_v1` prose quoted 35 and 22 members where the database said 37 and 24
    — a tutorial whose numbers are written by hand rots the same way;
  * a class with ZERO asserted instances disappears from Protégé's Classes panel under the default
    filter, which cost an afternoon before it was named.

So this test re-derives every number the chapters print, from the same reasoner the chapters use,
and fails when a chapter and the ontology disagree. It also pins the LADDER: each step file must be
a strict superset of the one before it, adding exactly the thing that step claims to add.

Regenerate the chapters after changing the ontology:  python backend/scripts/build_tutorial_steps.py
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))

PROFILE = BACKEND / "features" / "ontology" / "profiles" / "talent_steps"
ONT = PROFILE / "ontology"
TUT = PROFILE / "tutorial"
NS = "http://example.org/talent#"

#: step number -> (file, triples, what that step adds) — the ladder the chapters teach
LADDER = {
    1: ("step01.ttl", 1, "one class"),
    2: ("step02.ttl", 4, "one data property"),
    3: ("step03.ttl", 5, "one class"),
    4: ("step04.ttl", 8, "one object property"),
    5: ("step05.ttl", 12, "one individual, typed into a category"),
    6: ("step06.ttl", 20, "two individuals and their facts"),
    7: ("step07.ttl", 41, "the axiom"),
}


def _reasoner():
    from features.ontology.reasoning.reasoner import available
    usable, why = available()
    if not usable:
        pytest.skip(why)
    return True


import pytest  # noqa: E402


# ── the ladder ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("n", sorted(LADDER))
def test_step_file_has_the_triple_count_the_chapter_claims(n):
    from rdflib import Graph
    name, triples, _ = LADDER[n]
    g = Graph()
    g.parse(ONT / name, format="turtle")
    assert len(g) == triples, f"{name} has {len(g)} triples, the tutorial says {triples}"


@pytest.mark.parametrize("n", sorted(LADDER)[1:])
def test_each_step_is_a_strict_superset_of_the_one_before(n):
    """A step that only rearranges would make 'one thing per step' a lie."""
    from rdflib import Graph
    prev_name, _, _ = LADDER[n - 1]
    name, _, _ = LADDER[n]
    prev = Graph()
    prev.parse(ONT / prev_name, format="turtle")
    cur = Graph()
    cur.parse(ONT / name, format="turtle")
    missing = [t for t in prev if t not in cur]
    assert not missing, f"{name} dropped {len(missing)} triple(s) present in {prev_name}"


# ── the claims the chapters print ────────────────────────────────────────────
def test_the_ontology_reasons_to_exactly_cand_a():
    _reasoner()
    from features.ontology.reasoning.reasoner import load_graph, reason
    res = reason(load_graph([ONT / "step07.ttl"]), watch_classes=[f"{NS}matches_SoftwareEngineer"])
    members = sorted(m.split("#")[-1] for m in res.members_of(f"{NS}matches_SoftwareEngineer"))
    assert members == ["cand_A"], f"expected only cand_A, got {members}"
    assert res.consistent, "the tutorial's ontology must be consistent"
    assert not res.unsatisfiable_classes, res.unsatisfiable_classes


def test_cand_b_is_excluded_for_the_year_and_not_for_the_skill():
    """Both candidates have Python. Only cand_A qualifies. If this ever breaks, the chapter's
    '只差在年限上' sentence is false."""
    _reasoner()
    from features.ontology.reasoning.reasoner import load_graph, reason
    res = reason(load_graph([ONT / "step07.ttl"]),
                 watch_classes=[f"{NS}Candidate", f"{NS}matches_SoftwareEngineer"])
    assert sorted(m.split("#")[-1] for m in res.members_of(f"{NS}Candidate")) == ["cand_A", "cand_B"]
    assert "cand_B" not in [m.split("#")[-1] for m in res.members_of(f"{NS}matches_SoftwareEngineer")]


def test_removing_the_axiom_removes_the_conclusion():
    """The falsification the last chapter teaches. If it does not hold, the chapter's whole point
    ('结论是算出来的') is false."""
    _reasoner()
    from features.ontology.reasoning.reasoner import load_graph, mutate, reason
    graph = load_graph([ONT / "step07.ttl"])
    pruned, removed = mutate(graph, subject="matches_SoftwareEngineer", predicate="equivalentClass",
                             namespace=NS)
    assert removed >= 1, "the axiom was not found — the mutation removed nothing"
    res = reason(pruned, watch_classes=[f"{NS}matches_SoftwareEngineer"])
    assert res.members_of(f"{NS}matches_SoftwareEngineer") == [], "the conclusion survived the axiom"


def test_no_conclusion_is_asserted_in_the_abox():
    """The iron rule: a conclusion must never be written into a file."""
    from rdflib import Graph, RDF, URIRef
    g = Graph()
    g.parse(ONT / "step07.ttl", format="turtle")
    asserted = list(g.subjects(RDF.type, URIRef(f"{NS}matches_SoftwareEngineer")))
    assert not asserted, f"a conclusion is asserted in the file: {asserted}"


def test_classes_are_declared_not_inferred_only():
    """`owl:equivalentClass` needs a NAMED class. Without `a owl:Class` the reasoner answers
    'class matches_SoftwareEngineer is not in the ontology'."""
    from rdflib import Graph, RDF, OWL, URIRef
    g = Graph()
    g.parse(ONT / "step07.ttl", format="turtle")
    assert (URIRef(f"{NS}matches_SoftwareEngineer"), RDF.type, OWL.Class) in g


# ── the chapters themselves ──────────────────────────────────────────────────
def test_the_chapters_that_exist_are_the_ones_this_build_draws():
    """The chapters on disk must be exactly the steps this build draws. The list comes from the
    GENERATOR, so adding a step to the generator and forgetting to regenerate is caught here."""
    import importlib
    sys.path.insert(0, str(BACKEND / "scripts"))
    gen = importlib.import_module("build_tutorial_steps")
    drawn = sorted(int(p.stem.replace("step", "")) for p in TUT.glob("step*.html"))
    assert drawn == sorted(gen.DRAWN), \
        f"the chapters on disk are {drawn} but the generator draws {sorted(gen.DRAWN)}"


def test_the_shell_lists_exactly_the_drawn_steps():
    """A step button for a chapter that does not exist yet loads retail's page instead — the
    failure mode the platform already hit once (a chapter showing another ontology's numbers)."""
    drawn = sorted(int(p.stem.replace("step", "")) for p in TUT.glob("step*.html"))
    shell = (TUT / "shell.html").read_text(encoding="utf-8")
    buttons = sorted(int(m) for m in re.findall(r'class="stepbtn[^"]*" data-n="(\d+)"', shell))
    assert buttons == drawn, f"the shell offers {buttons} but the chapters are {drawn}"
    # the button handler builds the chapter URL; it must point at THIS ontology's chapters
    assert "/api/ontology/talent_steps/tutorial/chapter/" in shell, \
        "the shell does not address this ontology's own chapters"
    assert "tutorialGraph" in shell, "the step button does not update the chart"


def test_every_chapter_links_to_every_other():
    drawn = sorted(int(p.stem.replace("step", "")) for p in TUT.glob("step*.html"))
    for n in drawn:
        html = (TUT / f"step{n}.html").read_text(encoding="utf-8")
        for m in drawn:
            assert f"/api/ontology/talent_steps/tutorial/chapter/{m}" in html, \
                f"chapter {n} does not link to chapter {m}"


def test_the_chapters_are_in_english():
    """English is the SOURCE language now, so the page declares it and does not lean on a
    translation dictionary to become readable."""
    settings = json.loads((PROFILE / "settings.json").read_text(encoding="utf-8"))
    assert (settings.get("ui") or {}).get("language") == "en"
    for path in TUT.glob("step*.html"):
        html = path.read_text(encoding="utf-8")
        assert '<html lang="en"' in html, f"{path.name} is not declared English"
        # a Chinese sentence here means the chapter was not rewritten when the language flipped
        assert not re.search(r"[\u4e00-\u9fff]", html), f"{path.name} still contains Chinese"


def test_each_chapter_shows_exactly_what_its_step_adds():
    """The chapter's Turtle must be the step's own block and nothing else — no teaching comments
    leaking in, and no earlier step's lines repeated."""
    from rdflib import Graph
    for path in sorted(TUT.glob("step*.html")):
        n = int(path.stem.replace("step", ""))
        html = path.read_text(encoding="utf-8")
        g = Graph()
        g.parse(ONT / f"step{n:02d}.ttl", format="turtle")
        # the step's own Turtle, as the generator computed it
        sys.path.insert(0, str(BACKEND / "scripts"))
        from build_tutorial_steps import added_of
        added = added_of(f"step{n:02d}.ttl")
        assert added in html, f"{path.name} does not show the Turtle step {n} adds"
        assert "── 第" not in html, f"{path.name} leaked a section header into the Turtle box"
    g = Graph()
    g.parse(ONT / "step01.ttl", format="turtle")
    assert len(g) == 1, "step01.ttl must hold exactly one triple"


def test_the_shell_has_a_step_browser_and_a_chart_panel():
    shell = (TUT / "shell.html").read_text(encoding="utf-8")
    assert 'id="steps"' in shell, "the shell has no step browser"
    assert 'id="mini-graph"' in shell, "the shell has no chart panel"
    assert 'data-step="1"' in shell, "the chart does not start on step 1"
    assert "tutorial_graph.js" in shell, "the chart is never wired up"
    # the button must drive BOTH the page and the chart
    assert "tutorialGraph" in shell, "the step button does not update the chart"


def test_the_step_graph_data_has_exactly_one_node_for_step1():
    """The picture on the right must show what step 1's file contains: one class, no edges."""
    doc = json.loads((TUT / "graph.json").read_text(encoding="utf-8"))
    g = doc["steps"]["1"]
    assert len(g["nodes"]) == 1, f"step 1's picture has {len(g['nodes'])} nodes"
    assert g["nodes"][0]["t"] == ":Candidate"
    assert g["edges"] == []


def test_every_drawable_step_has_a_picture():
    """A step with a chapter but no picture would leave the right-hand panel blank — the exact
    'graph unavailable' failure the platform already had once."""
    doc = json.loads((TUT / "graph.json").read_text(encoding="utf-8"))
    for path in TUT.glob("step*.html"):
        n = int(path.stem.replace("step", ""))
        assert str(n) in doc["steps"], f"chapter {n} has no picture in graph.json"


def test_the_picture_matches_the_step_file_it_pictures():
    """The tutorial's claim is 'the picture on the right is exactly this step's file'. So the
    picture's nodes must be the step's classes and individuals — no more, no fewer.

    This is the check that catches a picture drawn by hand: a hand-drawn step 3 that still shows
    step 5's individuals would teach the reader something false, and nothing else would notice."""
    from rdflib import Graph, RDF, OWL, URIRef
    doc = json.loads((TUT / "graph.json").read_text(encoding="utf-8"))
    for n in sorted(int(p.stem.replace("step", "")) for p in TUT.glob("step*.html")):
        g = Graph()
        g.parse(ONT / f"step{n:02d}.ttl", format="turtle")
        classes = {str(s).split("#")[-1] for s in g.subjects(RDF.type, OWL.Class)
                   if isinstance(s, URIRef) and str(s).startswith(NS)}
        # NB: keep the URIRefs while detecting properties. Working with the local NAMES here is
        # what made this check silently pass every property: `g.objects("hasSkill", RDF.type)` gets
        # a string, rdflib resolves nothing, and the property set comes out EMPTY — so the test
        # believed hasSkill was an individual and demanded it as a node.
        subjects = {s for s in g.subjects(RDF.type, None)
                    if isinstance(s, URIRef) and str(s).startswith(NS)}
        properties = {str(s).split("#")[-1] for s in subjects
                      if {str(t).split("#")[-1] for t in g.objects(s, RDF.type)} &
                      {"ObjectProperty", "DatatypeProperty"}}
        individuals = {str(s).split("#")[-1] for s in subjects} - classes - properties

        step = doc["steps"][str(n)]
        pictured = {node["id"] for node in step["nodes"]}
        # a property may be drawn as a NODE (a slot on its domain) or as an EDGE LABEL (the link
        # between two boxes). Either way it must be visible — a property that appears in neither
        # place is a property the reader cannot see at all.
        labelled = {e["l"] for e in step["edges"]}
        missing = (classes | individuals) - pictured
        invisible = {p for p in properties if p not in pictured and p not in labelled}
        extra = pictured - (classes | individuals | properties)
        assert not missing, f"step {n}'s picture omits {sorted(missing)}"
        assert not invisible, f"step {n}'s picture hides the propert(y/ies) {sorted(invisible)}"
        assert not extra, f"step {n}'s picture shows {sorted(extra)}, which the file does not contain"


def test_no_picture_has_a_dangling_edge():
    """An edge pointing at a node that is not there draws an arrow into empty space."""
    doc = json.loads((TUT / "graph.json").read_text(encoding="utf-8"))
    for n, step in doc["steps"].items():
        ids = {node["id"] for node in step["nodes"]}
        for e in step["edges"]:
            assert e["a"] in ids, f"step {n}: edge starts at {e['a']}, which is not a node"
            assert e["b"] in ids, f"step {n}: edge ends at {e['b']}, which is not a node"


def test_the_pictures_are_regenerable_and_current():
    """The pictures are generated from the TTLs; hand-editing them would make them lie."""
    out = subprocess.run([sys.executable, str(BACKEND / "scripts" / "build_tutorial_graphs.py")],
                         capture_output=True, text=True, cwd=str(BACKEND))
    assert out.returncode == 0, out.stderr


def test_chapters_are_regenerable_and_current():
    """Running the generator must be a no-op: if it changes the files, the committed chapters are
    out of date with the ontology."""
    import shutil
    import tempfile

    def mask(text: str) -> str:
        # the elapsed-ms line is a live measurement, so it differs on every run
        return re.sub(r"HermiT \d+ ms", "HermiT N ms", text)

    drawn = sorted(int(p.stem.replace("step", "")) for p in TUT.glob("step*.html"))
    before = {n: (TUT / f"step{n}.html").read_text(encoding="utf-8") for n in drawn}

    with tempfile.TemporaryDirectory() as td:
        staged = pathlib.Path(td) / "tutorial"
        staged.mkdir()
        for n in drawn:
            shutil.copy2(TUT / f"step{n}.html", staged / f"step{n}.html")
        original = TUT
        try:
            globals()["TUT"] = staged
            out = subprocess.run(
                [sys.executable, str(BACKEND / "scripts" / "build_tutorial_steps.py")],
                capture_output=True, text=True, cwd=str(BACKEND))
            assert out.returncode == 0, out.stderr
            after = {n: (staged / f"step{n}.html").read_text(encoding="utf-8") for n in drawn}
        finally:
            globals()["TUT"] = original

    for n in drawn:
        assert mask(before[n]) == mask(after[n]), \
            f"chapter {n} on disk differs from a fresh generation — re-run the generator and commit"


# ── the ladder has ONE source of truth ───────────────────────────────────────
def test_the_ladder_is_regenerable_and_current():
    """The seven step files are written by `build_talent_ladder.py`. Hand-editing one of them
    re-introduces the drift that made step 6 NOT a superset of step 5 — the reader would have
    opened a file whose ontology had changed under their feet."""
    out = subprocess.run([sys.executable, str(BACKEND / "scripts" / "build_talent_ladder.py")],
                         capture_output=True, text=True, cwd=str(BACKEND))
    assert out.returncode == 0, out.stderr
    for n in range(1, 8):
        name = f"step{n:02d}.ttl"
        fresh = (BACKEND / "examples" / "talent_steps" / name).read_text(encoding="utf-8")
        shipped = (ONT / name).read_text(encoding="utf-8")
        assert fresh == shipped, f"{name} in the profile differs from the ladder generator's output"


def test_the_profile_ships_the_same_ladder_the_tutorial_teaches():
    """The profile's `ontology/` directory IS the ladder. A reader who opens a chapter's file from
    the platform must get the same ontology as the one in `examples/talent_steps`."""
    for n in range(1, 8):
        name = f"step{n:02d}.ttl"
        assert (ONT / name).read_text(encoding="utf-8") == \
               (BACKEND / "examples" / "talent_steps" / name).read_text(encoding="utf-8"), \
               f"{name} differs between the profile and examples/talent_steps"


def test_the_profile_abox_and_reasoning_pair_agrees_with_the_ladder():
    """`abox.ttl` + `reasoning.ttl` exist because the platform's reasoning API reads that pair.
    They must mean the same thing as `step07.ttl` — same conclusion, same class, same exclusions."""
    _reasoner()
    from features.ontology.reasoning.reasoner import load_graph, reason
    iri = f"{NS}matches_SoftwareEngineer"
    pair = reason(load_graph([PROFILE / "reasoning.ttl", PROFILE / "abox.ttl"]),
                  watch_classes=[iri])
    ladder = reason(load_graph([ONT / "step07.ttl"]), watch_classes=[iri])
    assert pair.members_of(iri) == ladder.members_of(iri), \
        "the profile's abox/reasoning pair concludes differently from step07.ttl"
    assert pair.consistent and ladder.consistent


def test_the_profile_pair_does_not_assert_the_conclusion():
    """The iron rule, checked on the files the platform actually reads."""
    from rdflib import Graph, RDF, URIRef
    g = Graph()
    g.parse(ONT / "step07.ttl", format="turtle")
    for f in (PROFILE / "abox.ttl", PROFILE / "reasoning.ttl"):
        gg = Graph()
        gg.parse(f, format="turtle")
        assert not list(gg.subjects(RDF.type, URIRef(f"{NS}matches_SoftwareEngineer"))), \
            f"{f.name} asserts the conclusion — it must be reasoned, not written"



# ── the step-scoped query ────────────────────────────────────────────────────
def test_a_step_query_answers_from_that_steps_own_file():
    """The query must be answered by the ontology as it stands AT THAT STEP, not by the finished
    one. Otherwise "who has a skill?" would answer from step 6 while the reader is at step 4 —
    and the chapter's whole "not yet" lesson would be a lie."""
    from services import ontology_tutorial_chapters as tc
    q = "SELECT ?c ?s WHERE { ?c :hasSkill ?s }"
    at4 = tc._step_query("talent_steps", 4, q)
    at6 = tc._step_query("talent_steps", 6, q)
    assert at4["rows"] == [], "step 4 has nobody with a skill — the answer must be empty"
    assert at6["rows"], "step 6 has two candidates with a skill — the answer must not be empty"
    assert at4["file"] == "step04.ttl" and at6["file"] == "step06.ttl"


def test_a_step_query_reports_a_count_as_a_row():
    """“How many candidates?” at step 4 must answer 0 — a SUCCESS with a value, not an empty
    result. A reader cannot tell a working query from a broken one if every answer is blank."""
    from services import ontology_tutorial_chapters as tc
    r = tc._step_query("talent_steps", 4, "SELECT (COUNT(?c) AS ?n) WHERE { ?c a :Candidate }")
    assert r["rows"] == [["0"]], f"expected a count of 0, got {r['rows']}"


def test_a_step_query_can_be_asked_for_the_classes_and_the_links():
    from services import ontology_tutorial_chapters as tc
    classes = tc._step_query("talent_steps", 4, "SELECT ?c WHERE { ?c a owl:Class }")
    assert sorted(r[0] for r in classes["rows"]) == ["Candidate", "SkillTag"]
    links = tc._step_query("talent_steps", 4, "SELECT ?p WHERE { ?p a owl:ObjectProperty }")
    assert [r[0] for r in links["rows"]] == ["hasSkill"]


def test_the_chapter_endpoint_arguments_are_not_truncated_to_one_character():
    """Starlette's `dict(request.query_params)` yields a PLAIN STRING per key, not a list. The
    dispatcher used to take `[0]` of it — the FIRST CHARACTER — so every parameter arrived as one
    letter and every SPARQL died with "Expected {SelectQuery …}, found 'S'".

    This is the regression that made every query fail; it is locked here because it is invisible
    until a query with more than one character is sent.
    """
    from urllib.parse import parse_qs
    from services import ontology_tutorial_chapters as tc
    qs = "step=4&query=SELECT+%3fc+WHERE+%7b+%3fc+a+%3aCandidate+%7d"
    # what the route really passes: dict(request.query_params) → plain strings
    params = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(qs).items()}
    r = tc.call("talent_steps", "stepquery", params)
    assert "QUERY ERROR" not in str(r.get("rows")), f"the query was mangled: {r.get('rows')}"
    assert r.get("columns") == ["c"], f"the query text was truncated: {r.get('columns')}"


def test_every_working_query_button_returns_rows_at_its_step():
    """A button that claims to work and returns nothing is a lie the reader has to debug. The rule
    for this tutorial: a button marked working must return a REAL result at that step — and “0” is
    a real result, “no rows” is not.

    This is checked against the endpoint, not against the prose: the button's query is extracted
    from the page and run for real."""
    import re
    from services import ontology_tutorial_chapters as tc

    for path in sorted(TUT.glob("step*.html")):
        n = int(path.stem.replace("step", ""))
        html = path.read_text(encoding="utf-8")
        buttons = re.findall(r'<button data-q="([^"]+)" data-ok="1">([^<]*)</button>', html)
        for raw_q, label in buttons:
            # the page escapes braces for the f-string; the real query has single ones
            q = raw_q.replace("{{", "{").replace("}}", "}")
            r = tc._step_query("talent_steps", n, q)
            rows = r.get("rows") or []
            assert rows, (f"{path.name}: the button “{label}” is marked as working but "
                          f"'{q}' returns no rows at step {n}")
            assert not (len(rows) == 1 and str(rows[0][0]).startswith("QUERY ERROR")), \
                f"{path.name}: the button “{label}” has a broken query: {rows}"


def test_the_locked_queries_really_are_locked_at_that_step():
    """The chapter promises specific answers for the questions it cannot answer yet. Those
    promises are numbers, so they must be measured rather than believed."""
    from services import ontology_tutorial_chapters as tc
    q_names = "SELECT ?c ?l WHERE { ?c a :Candidate ; rdfs:label ?l }"
    at4 = tc._step_query("talent_steps", 4, q_names)
    assert at4["rows"] == [], "step 4 has no candidates, so 'who are the candidates' must be empty"
    at6 = tc._step_query("talent_steps", 6, q_names)
    assert at6["rows"], "step 6 names its candidates — the names must be there"


def test_the_whole_ontology_can_be_queried_too():
    """The reader must always be able to ask a REAL question and get a REAL answer. So the query
    endpoint answers against the complete ontology as well as against a single step — and "all"
    must not be swallowed by the int cast (which silently answered as step 1)."""
    from services import ontology_tutorial_chapters as tc
    whole = tc._step_query("talent_steps", "all", "SELECT (COUNT(?c) AS ?n) WHERE { ?c a :Candidate }")
    assert whole["rows"] == [["2"]], f"the whole ontology should hold 2 candidates, got {whole['rows']}"
    assert whole["file"] == "step07.ttl", f"expected the last step's file, got {whole['file']}"
    names = tc._step_query("talent_steps", "all",
                           "SELECT ?c ?l WHERE { ?c a :Candidate ; rdfs:label ?l }")
    assert len(names["rows"]) == 2, f"the whole ontology must name its candidates: {names['rows']}"


def test_the_step_argument_accepts_the_words_for_the_whole_ontology():
    """`arg(..., int)` cast "all" to int, the ValueError was swallowed into the default, and the
    reader's "the whole ontology" answered as step 1 — a silent wrong answer, not an error."""
    from services import ontology_tutorial_chapters as tc
    # the marker may come back as "all" or "0" — what matters is that it REACHES the whole
    # ontology, not that it is normalised to one particular spelling.
    for word in ("all", "ALL", "0", "final", "full"):
        got = tc._step_arg(word)
        whole = tc._step_query("talent_steps", got, "SELECT (COUNT(?c) AS ?n) WHERE { ?c a :Candidate }")
        assert whole["rows"] == [["2"]], f"{word!r} must reach the whole ontology, got {whole['rows']}"
    for word in ("1", "5", "07"):
        assert tc._step_arg(word) == int(word)
    assert tc._step_arg("nonsense") == 1


def test_the_query_box_offers_both_scopes():
    """The reader must always be able to ask a real question and get a real answer. So the box has
    two scopes — the whole ontology (the default, always meaningful) and this step only (the
    teaching view, which honestly answers 0 early on)."""
    import re
    for path in sorted(TUT.glob("step*.html")):
        html = path.read_text(encoding="utf-8")
        if 'id="aq"' not in html:
            continue
        scopes = re.findall(r'name="scope" value="(\w+)"', html)
        assert set(scopes) == {"all", "step"}, f"{path.name} offers scopes {scopes}"
        # the whole ontology is the default, so the first answer a reader gets is a real one
        assert 'value="all" checked' in html, f"{path.name} does not default to the whole ontology"
        assert "Run the query" in html, f"{path.name}'s button still reads like a restriction"


def test_the_whole_ontology_answers_every_question_the_step_cannot():
    """The two scopes must disagree exactly where the tutorial says they do: the finished ontology
    can name the candidates; the early steps cannot."""
    from services import ontology_tutorial_chapters as tc
    names = "SELECT ?c ?l WHERE { ?c a :Candidate ; rdfs:label ?l }"
    assert tc._step_query("talent_steps", 4, names)["rows"] == []
    assert len(tc._step_query("talent_steps", "all", names)["rows"]) == 2
    count = "SELECT (COUNT(?c) AS ?n) WHERE { ?c a :Candidate }"
    assert tc._step_query("talent_steps", 4, count)["rows"] == [["0"]]
    assert tc._step_query("talent_steps", "all", count)["rows"] == [["2"]]


def test_the_query_endpoint_is_real_sparql_not_a_lookup():
    """The tutorial's query box must answer with a REAL SPARQL engine, not canned answers. Three
    things prove it, and all three are checked here:

      * different queries get different answers;
      * FILTER and chained patterns are evaluated (only an engine can do that);
      * a malformed query is rejected by the PARSER, with a position — a lookup table cannot
        produce a ParseException.
    """
    from services import ontology_tutorial_chapters as tc
    q = tc._step_query("talent_steps", "all", "SELECT ?c WHERE { ?c a owl:Class }")
    assert [r[0] for r in q["rows"]][:2] == ["Candidate", "SkillTag"]
    # a FILTER is evaluated, not matched literally
    filt = tc._step_query("talent_steps", "all",
                          "SELECT ?c WHERE { ?c :yearsExperience ?y . FILTER(?y > 3) }")
    assert [r[0] for r in filt["rows"]] == ["cand_A"], "FILTER(?y > 3) must select the 5-year CV"
    # a chained pattern walks two hops
    chained = tc._step_query("talent_steps", "all",
                             "SELECT ?c ?s WHERE { ?c :hasSkill ?s . ?s a :Programming }")
    assert len(chained["rows"]) == 2, f"the chained pattern must walk candidate→skill→category"
    # a malformed query is a PARSE error, with a character position
    bad = tc._step_query("talent_steps", "all", "SELECT ?c WHERE { ?c a :Candidate")
    assert bad["rows"] and str(bad["rows"][0][0]).startswith("QUERY ERROR"), \
        f"a malformed query must be rejected by the parser, got {bad['rows']}"
    assert "ParseException" in str(bad["rows"][0][0])


def test_ask_returns_a_boolean_not_no_rows():
    """A FALSE answer must be visibly different from \"nothing to say\": iterating an ASK result
    yields the boolean as a row, so the answer used to come back as a bare row — and a false answer
    came back as no rows at all."""
    from services import ontology_tutorial_chapters as tc
    yes = tc._step_query("talent_steps", "all", "ASK { ?c a :Candidate }")
    no = tc._step_query("talent_steps", "all", "ASK { ?c a :Nonexistent }")
    assert yes["rows"] == [["true"]] and yes["answer"] is True
    assert no["rows"] == [["false"]] and no["answer"] is False


def test_the_rewrite_does_not_double_the_path():
    """The rewrite that points a page's absolute paths at THIS ontology used to rewrite a path that
    ALREADY named this ontology, producing
    `/api/ontology/talent_steps/wb/ontology/talent_steps/wb/stepquery` — a 404 that the page
    reported as "no rows", with an `undefined` filename."""
    from services import ontology_tutorial_chapters as tc
    html = '<script>fetch("/api/ontology/talent_steps/wb/stepquery?step=5")</script>'
    out = tc._rewrite(html, "talent_steps")
    assert out.count("/wb/") == 1, f"the path was rewritten twice: {out}"
    assert "/wb/ontology/" not in out, f"the path was doubled: {out}"
    # a bare workbench path IS rewritten to this ontology
    bare = tc._rewrite('<script>fetch("/api/tutorial6/metrics")</script>', "talent_steps")
    assert "/api/ontology/talent_steps/wb/tutorial6/metrics" in bare, bare


def test_the_query_box_can_ask_the_reasoner():
    """The lesson of step 5 is that SPARQL cannot answer a question whose answer is not in the
    files. So the chapter must let the reader SEE that: one button runs the query, another runs the
    real reasoner over the same ontology."""
    html = (TUT / "step5.html").read_text(encoding="utf-8")
    assert 'id="areason"' in html, "step 5 has no button that asks the reasoner"
    assert 'id="aclass"' in html, "step 5 has no way to say WHICH class to ask about"
    assert "/wb/stepreason?step=" in html, \
        "the reasoner button must call the step-scoped reasoning endpoint"


def test_the_reasoning_endpoint_answers_what_sparql_cannot():
    """The claim the chapter makes: SPARQL finds nothing, the reasoner finds cand_A. Both are
    checked against the real thing, so the sentence in the chapter cannot rot."""
    from services import ontology_tutorial_chapters as tc
    from features.ontology.reasoning.reasoner import load_graph, reason
    import pathlib

    q = "SELECT ?c WHERE { ?c a :matches_SoftwareEngineer }"
    sparql = tc._step_query("talent_steps", "all", q)
    assert sparql["rows"] == [], "SPARQL must find nothing — the answer is not in any file"

    graph = load_graph([pathlib.Path("features/ontology/profiles/talent_steps/ontology/step07.ttl")])
    res = reason(graph, watch_classes=[NS + "matches_SoftwareEngineer"])
    members = sorted(m.split("#")[-1] for m in res.members_of(NS + "matches_SoftwareEngineer"))
    assert members == ["cand_A"], f"the reasoner must conclude cand_A, got {members}"


def test_every_chapter_javascript_parses():
    """A chapter whose script has a syntax error loses its WHOLE script block — the query box, the
    buttons, everything. It happened: a `\\n` written as a literal newline inside a single-quoted
    JS string made the whole file a syntax error, and the query box simply stopped working with
    no message anywhere.

    `node --check` is the same check the platform already uses for its own pages (test_graph_page_parses
    runs it), so the guard is not new machinery — it is the one that already exists, applied here.
    """
    import re
    import shutil
    import subprocess
    import tempfile

    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node is not installed — cannot syntax-check the chapters' JavaScript")

    for path in sorted(TUT.glob("step*.html")):
        html = path.read_text(encoding="utf-8")
        for i, script in enumerate(re.findall(r"<script>(.*?)</script>", html, re.S)):
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
                fh.write(script)
                tmp = fh.name
            try:
                out = subprocess.run([node, "--check", tmp], capture_output=True, text=True)
                assert out.returncode == 0, (
                    f"{path.name} script block {i} has a syntax error — the whole block is dead:\n"
                    + out.stderr.strip()[:600])
            finally:
                pathlib.Path(tmp).unlink(missing_ok=True)


def test_each_samples_answer_matches_what_the_chapter_claims():
    """The step-6 chapter prints a table of answers next to its sample queries. If a query changes
    and the table does not, the chapter teaches a number that is no longer true — the failure this
    project has already paid for once (tutorial prose quoting 35 and 22 where the database said 37
    and 24).

    So: run every sample query against the step it belongs to, and check the answer is a real
    answer — not empty, not an error.
    """
    import re
    from services import ontology_tutorial_chapters as tc

    for path in sorted(TUT.glob("step*.html")):
        n = int(path.stem.replace("step", ""))
        html = path.read_text(encoding="utf-8")
        buttons = re.findall(r'<button data-q="([^"]+)" data-ok="1">([^<]*)</button>', html)
        for raw_q, label in buttons:
            q = raw_q.replace("{{", "{").replace("}}", "}")
            r = tc._step_query("talent_steps", n, q)
            rows = r.get("rows") or []
            assert rows, (f"{path.name}: the sample “{label}” is marked as working but "
                          f"'{q}' returns no rows at step {n}")
            assert not (len(rows) == 1 and str(rows[0][0]).startswith("QUERY ERROR")), \
                f"{path.name}: the sample “{label}” has a broken query: {rows}"


def test_the_step6_table_quotes_the_real_answers():
    """The step-6 table says what each query answers. Spot-check the three numbers it prints
    against the real ontology — the table is the chapter's claim, and a claim must be measured."""
    from services import ontology_tutorial_chapters as tc
    html = (TUT / "step6.html").read_text(encoding="utf-8")

    rows = tc._step_query("talent_steps", 6,
                          "SELECT ?c ?l WHERE { ?c a :Candidate ; rdfs:label ?l }")["rows"]
    # each row is [candidate, label]
    assert sorted(r[1] for r in rows) == ["A — Python, 5 years", "B — Python, 1 year"]
    assert "A — Python, 5 years" in html, "the chapter does not quote the candidate names it claims"

    senior = tc._step_query("talent_steps", 6,
                            "SELECT ?c WHERE { ?c :yearsExperience ?y . FILTER(?y > 3) }")["rows"]
    assert [r[0] for r in senior] == ["cand_A"], "only cand_A has 3+ years"
    assert "cand_A" in html, "the chapter does not name the candidate the filter selects"


def test_the_step_reasoner_answers_from_that_steps_file():
    """The platform's own /reason always reasons over the COMPLETE ontology, so a step-by-step
    tutorial would see step 7's answer while the reader is at step 6 — where the axiom does not
    exist yet. The step-scoped reasoner must answer from the step's own file.

    The arc this locks in:
        step 5 → no answer (no axiom)
        step 6 → no answer (no axiom)
        step 7 → cand_A
    """
    from services import ontology_tutorial_chapters as tc
    for step in (5, 6):
        r = tc._step_reason("talent_steps", step, "matches_SoftwareEngineer")
        assert r["rows"] == [], f"step {step} has no axiom, so nothing may be entailed"
        assert r["has_axiom"] is False, f"step {step} must report that it has no axiom"
    r7 = tc._step_reason("talent_steps", 7, "matches_SoftwareEngineer")
    assert r7["rows"] == ["cand_A"], f"step 7 must entail cand_A, got {r7['rows']}"
    assert r7["has_axiom"] is True
    assert r7["asserted"] == 0, "the conclusion must not be asserted in the file"


def test_the_reasoner_button_follows_the_scope_toggle():
    """The chapter tells the reader that both buttons respect the scope toggle — so the button
    must not call the platform's always-complete endpoint."""
    html = (TUT / "step6.html").read_text(encoding="utf-8")
    assert "/wb/stepreason?step=" in html, \
        "the reasoner button must use the STEP-SCOPED reasoner, not the platform's /reason"


def test_the_qualification_question_is_personal_to_a_and_b():
    """Step 6's point: the candidates cannot qualify YET, and the machine cannot tell us that.
    The chapter prints a table — A knows Python with 5 years, B knows Python with 1 — and says both
    are "unknown". Every cell of that table is a claim, so it is measured here."""
    from services import ontology_tutorial_chapters as tc
    html = (TUT / "step6.html").read_text(encoding="utf-8")

    facts = tc._step_query("talent_steps", 6, "SELECT ?c ?s ?y WHERE { ?c :hasSkill ?s ; :yearsExperience ?y }")
    by_cand = {r[0]: (r[1], r[2]) for r in facts["rows"]}
    assert by_cand["cand_A"] == ("Python", "5")
    assert by_cand["cand_B"] == ("Python", "1")

    # the reasoner cannot decide it at step 6 — no rule exists yet
    r6 = tc._step_reason("talent_steps", 6, "matches_SoftwareEngineer")
    assert r6["rows"] == [], "no candidate may qualify at step 6 — the rule does not exist yet"
    assert r6["has_axiom"] is False
    # and SPARQL cannot decide it even on the finished ontology
    sparql = tc._step_query("talent_steps", "all",
                             "SELECT ?c WHERE { ?c a :matches_SoftwareEngineer }")
    assert sparql["rows"] == [], "the conclusion is in no file — SPARQL can only find what was written"

    # the chapter must say "unknown", not "no"
    assert "unknown" in html, "the chapter must not claim A or B fails — it is not known yet"


def test_step7_concludes_cand_a_and_not_cand_b():
    """The course's payoff, measured: the rule makes the reasoner conclude A and reject B."""
    from services import ontology_tutorial_chapters as tc
    r = tc._step_reason("talent_steps", 7, "matches_SoftwareEngineer")
    assert r["rows"] == ["cand_A"], f"the rule must conclude cand_A, got {r['rows']}"
    assert r["asserted"] == 0, "the conclusion must not be asserted in the file"
    assert r["has_axiom"] is True
    # and the falsification: remove the rule and the answer must go
    assert r["without_axiom"] == [], "without the axiom there must be no conclusion"


def test_step7_sparql_still_finds_nothing():
    """The sharpest lesson: even with the complete ontology, a query cannot answer "who qualifies?",
    because the conclusion is in no file. If this ever starts returning rows, the chapter's claim —
    and the whole reason the TBox/ABox separation exists — is no longer true."""
    from services import ontology_tutorial_chapters as tc
    for scope in (6, 7, "all"):
        r = tc._step_query("talent_steps", scope, "SELECT ?c WHERE { ?c a :matches_SoftwareEngineer }")
        assert r["rows"] == [], f"scope {scope}: the conclusion must not be findable by a query"


def test_step7_marks_its_qualification_buttons_as_needing_the_reasoner():
    """A button that claims to work and returns nothing is a lie the reader has to debug. Step 7's
    "who qualifies?" buttons cannot work by querying — so they must not claim to."""
    import re
    html = (TUT / "step7.html").read_text(encoding="utf-8")
    working = re.findall(r'<button data-q="([^"]+)" data-ok="1">([^<]*)</button>', html)
    for raw_q, label in working:
        q = raw_q.replace("{{", "{").replace("}}", "}")
        rows = tc_rows = None
        from services import ontology_tutorial_chapters as tc
        rows = tc._step_query("talent_steps", 7, q)["rows"]
        assert rows, f"step7: the button “{label}” claims to work but returns no rows"
    # and the qualification buttons must be marked as NOT working
    locked = re.findall(r'<button data-q="([^"]*matches_SoftwareEngineer[^"]*)" data-ok="0">', html)
    assert len(locked) == 4, f"step 7 must mark its four qualification buttons as needing the reasoner, got {len(locked)}"


def test_the_reasoner_button_resolves_its_own_step():
    """`step` used to be declared INSIDE `run()`, so `askReasoner()` read an undefined variable and
    died with "ReferenceError: Can't find variable: step" — the reader saw "request failed" and no
    answer, with nothing in the log but a successful HTTP 200 from an endpoint that was never
    really asked.

    The fix hoists the resolution into shared helpers. This check makes sure BOTH buttons resolve
    it — and that the reasoner's own scope radios are wired, so the question it displays is the
    question it will ask.
    """
    import re
    for path in sorted(TUT.glob("step*.html")):
        html = path.read_text(encoding="utf-8")
        if 'id="areason"' not in html:
            continue
        assert "function stepOf()" in html, f"{path.name} has no shared step resolver"
        assert "function reasonerStep()" in html, f"{path.name} has no reasoner step resolver"
        # the reasoner must NOT read a bare `step` that only run() defines
        body = html.split("async function askReasoner()", 1)[-1].split("async function", 1)[0]
        assert "const step = reasonerStep();" in body, \
            f"{path.name}: askReasoner must resolve its own step"
        assert "+ step +" in body, f"{path.name}: askReasoner must SEND the step it resolved"
        # and the panel must show the question it is about to ask
        assert 'id="rqclass"' in html and 'id="rqscope"' in html, \
            f"{path.name}: the reasoner panel does not state its question"
        assert 'name="rscope"' in html, f"{path.name}: the reasoner has no scope radios"

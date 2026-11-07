#!/usr/bin/env python3
"""check_clinic.py — every gate the clinic ontology must pass, in one script.

The ontology was produced by a DeepAgent, not by hand, so "it looks right" is not evidence.
Three families of gates, and each one is written so it can go **red**:

  C — ontology     the declarations hold up: structure, compile-or-refuse by NAME, the
                   numbers match an independently written SQL route, mutations bite,
                   no class carries both an axiom and a declared predicate
  R — reasoning    the definitions mean what the business said: every axiom compiles and
                   entails exactly the rows an independent column-level query selects,
                   every sample question answers or refuses BY NAME, and the reasoner lane
                   reports NOT RUN when it cannot run (never green by absence)
  G — guardrails   the SQL guard actually bites: page cap, time bound / refuse, plan budget,
                   statement timeout, declared metrics are never windowed, an empty window
                   is reported instead of silently returning 0

Run it against a profile (default: the archived clinic workbench profile):

    /Users/weiping/dev/Learn/cube/tutorial/.venv/bin/python check_clinic.py \
        --profile ../ontologies/clinic/clinic_settings.json

Exit 0 only when every gate passes. A NOT RUN gate prints its reason and keeps the exit
non-zero, because an unrun gate is not a passed gate.
"""
from __future__ import annotations

import argparse
import copy
import json
import pathlib
import sys
import time

import psycopg2
from rdflib import Literal, OWL, RDF, RDFS

HERE = pathlib.Path(__file__).resolve().parent
# The COMPILER lives one directory up (features/ontology/compiler) and its modules import each
# other by bare name, so its directory goes on sys.path — a path that never depends on where this
# repository happens to live.
import pathlib as _pathlib
import sys as _sys
sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[1] / "compiler"))

import guard  # noqa: E402
import sqlgen  # noqa: E402

OK = True
NOT_RUN: list[str] = []


def check(label: str, got, want) -> None:
    global OK
    good = got == want
    OK = OK and good
    print(f"  [{'PASS' if good else 'FAIL'}] {label}: got {got!r}, want {want!r}")


def check_true(label: str, cond: bool, detail: str = "") -> None:
    global OK
    OK = OK and bool(cond)
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + ("" if cond else f" — {detail}"))


def not_run(gate: str, reason: str) -> None:
    NOT_RUN.append(f"{gate}: {reason}")
    print(f"  [NOT RUN] {gate} — {reason}")


def refused(fn, *a, **kw) -> str | None:
    """Run fn; return the refusal message when it refuses (a result), else None."""
    try:
        fn(*a, **kw)
        return None
    except Exception as exc:                                   # noqa: BLE001
        return str(exc)


# ────────────────────────────────────────────────────────────────── setup
def load(profile_path: pathlib.Path):
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    base = profile_path.parent

    def rel(key: str) -> pathlib.Path:
        raw = profile.get(key) or ""
        p = pathlib.Path(raw)
        return p if p.is_absolute() else (base / p).resolve()

    sqlgen.reconfigure(ns=profile.get("ns"),
                       ontology_dir=str(rel("ontology_dir")),
                       overlay=str(rel("overlay")) if profile.get("overlay") else "",
                       drop_overlay=not profile.get("overlay"))
    g = sqlgen.load()
    import dsn as _dsn

    dsn = _dsn.resolved(profile)
    profile["_dsn"] = " ".join(f"{k}={v}" for k, v in dsn.items() if k != "password") + (
        f" password={dsn['password']}" if dsn.get("password") else "")
    return profile, g


def definition_table(g, cls: str, metrics: dict | None = None, depth: int = 4) -> str | None:
    """The physical table a definition class resolves to, or None.

    Three shapes exist and all three must resolve, or a metric on that class would face a
    predicate over a table nobody can name:
      · `owl:intersectionOf` on the object itself      → `concept_base_class`
      · `owl:unionOf (A B)`                            → both members must share one table
      · `:physicalPredicate "…"` (the one escape hatch) → the table comes from the metric
        that uses it as `:where`, i.e. its `:universe`
    """
    metrics = metrics or {}
    base = refused(sqlgen.concept_base_class, g, cls)
    if not base:
        b = sqlgen.concept_base_class(g, cls)
        if b:
            return b
    for axiom in g.objects(_p(cls), OWL.equivalentClass):
        members = []
        for lst in g.objects(axiom, OWL.unionOf):
            members = [str(m).split("#")[-1] for m in g.items(lst)]
        if members and depth > 0:
            bases = {definition_table(g, m, metrics, depth - 1) for m in members}
            bases.discard(None)
            if len(bases) == 1:
                return bases.pop()
    if list(g.objects(_p(cls), sqlgen.P("physicalPredicate"))):
        users = [m for m in metrics.values() if m.where == cls and m.universe]
        universes = {m.universe for m in users}
        if len(universes) == 1:
            return universes.pop()
    return None


def _p(local: str):
    from rdflib import URIRef
    return URIRef(f"{sqlgen.NS}{local}")


# ══════════════════════════════════════════════════════════ C — ontology gates
def ontology_gates(profile: dict, g, cur) -> None:
    print("\nC — ontology")
    classes = sorted({str(s).split("#")[-1] for s in g.subjects(RDF.type, OWL.Class)
                      if str(s).startswith(sqlgen.NS)})
    check_true("C0 the graph declares classes", len(classes) >= 5, f"{len(classes)} classes")
    print(f"       classes: {classes}")

    # A class is either an OBJECT (a table: :physicalTable + :primaryKey) or a DEFINITION
    # (an axiom that selects a subset of some object). A definition has no table of its own
    # — it inherits its base class's — so requiring one would be wrong, and requiring
    # nothing would let a metric be declared on a class that resolves to no table at all.
    objects, definitions = [], []
    for cls in classes:
        if list(g.objects(_p(cls), OWL.equivalentClass)) or \
                list(g.objects(_p(cls), sqlgen.P("physicalPredicate"))):
            definitions.append(cls)
        else:
            objects.append(cls)
    bad = []
    for cls in objects:
        if not list(g.objects(_p(cls), sqlgen.P("physicalTable"))):
            bad.append(f"{cls} (no :physicalTable)")
        if not list(g.objects(_p(cls), sqlgen.P("primaryKey"))):
            bad.append(f"{cls} (no :primaryKey)")
    check_true("C1a every object class names its physical table and primary key",
               not bad, f"missing: {bad}")
    metrics_now = sqlgen.metrics(g)
    orphans = []
    for cls in definitions:
        table = definition_table(g, cls, metrics_now)
        if not table or table not in objects:
            orphans.append(f"{cls} (table={table!r})")
    check_true("C1c every definition class resolves to a declared object",
               not orphans, str(orphans))
    print(f"       objects: {objects} · definitions: {len(definitions)}")

    links = []
    for prop in g.subjects(RDF.type, OWL.ObjectProperty):
        local = str(prop).split("#")[-1]
        col = next(iter(g.objects(prop, sqlgen.P("physicalColumn"))), None)
        ref = next(iter(g.objects(prop, sqlgen.P("references"))), None)
        links.append((local, str(col) if col else None, str(ref).split("#")[-1] if ref else None))
    check_true("C1b every link has a physical column and a declared target",
               all(col and ref and ref in classes for _, col, ref in links),
               f"incomplete: {[l for l in links if not (l[1] and l[2] in classes)]}")
    print(f"       links: {len(links)}")

    compiled, refusals = [], []
    for name in sqlgen.metrics(g):
        msg = refused(sqlgen.compile_metric, g, name)
        (refusals if msg else compiled).append((name, msg))
    check_true("C2a some metrics compile", bool(compiled),
               f"nothing compiled — {[r[0] for r in refusals]}")
    print(f"       compiled: {len(compiled)} · refused by name: {len(refusals)}")
    for name, why in refusals:
        print(f"         REFUSED {name}: {why.splitlines()[0]}")
    check_true("C2b every refusal names a reason (not a traceback)",
               all(why and len(why) > 10 for _, why in refusals), f"{refusals}")

    # ── C3 truth: an independently written SQL route per metric ────────────────
    def scalar(sql):
        cur.execute(sql)
        row = cur.fetchone()
        return row[0] if row else None

    truth = {
        # the compiled route sums a per-row formula; this one multiplies out first
        "lineRevenue": "select round(sum(qty*unit_price) - sum(qty*unit_price*discount), 2) "
                       "from treatment_lines",
        "invoiceRevenue": "select round(sum(total), 2) from invoices",
        "appointments": "select count(*)::numeric from appointments",
        "completedAppointments": "select count(*)::numeric from appointments "
                                 "where status = 'completed'",
        "noShowAppointments": "select count(*)::numeric from appointments "
                              "where status = 'no_show'",
        "collectionRate": "select round(100.0 * (select sum(amount) from payments) / "
                          "(select sum(total) from invoices), 2)",
    }
    metrics = sqlgen.metrics(g)
    compared = 0
    for name, sql in truth.items():
        if name not in metrics:
            not_run(f"C3 {name}", "the profiled ontology does not declare this metric")
            continue
        msg = refused(sqlgen.compile_metric, g, name)
        if msg:
            not_run(f"C3 {name}", f"refused: {msg.splitlines()[0]}")
            continue
        compiled_sql = sqlgen.compile_metric(g, name).sql
        # declared metrics report the unbounded scan; the guard must not change the number
        guarded = guard.apply(compiled_sql, profile["guard"], mode="declared")
        got = scalar(guarded["sql"].rstrip().rstrip(";"))
        want = scalar(sql)
        same = got is not None and want is not None and abs(float(got) - float(want)) <= 0.01
        compared += 1
        check_true(f"C3 {name} == independent route", same, f"compiled {got!r} vs truth {want!r}")
    check_true("C3 the truth gate actually compared metrics", compared >= 4, f"{compared} compared")

    # ── C4 mutations: each one must turn the machine red ───────────────────────
    def graph_after(mutate) -> tuple[object, str]:
        g2 = sqlgen.load()
        return g2, mutate(g2)

    # 4a delete :grain from a metric
    name = next(n for n, m in metrics.items() if m.aggregate and m.grain)
    def drop_grain(g2):
        g2.remove((_p(name), sqlgen.P("grain"), None))
    g2, _ = graph_after(drop_grain)
    msg = refused(sqlgen.compile_metric, g2, name)
    check_true(f"C4a deleting :grain on :{name} refuses", bool(msg), "it still compiled")
    print(f"         {msg and msg.splitlines()[0]}")

    # 4b drop :references on a link some metric depends on
    def drop_ref(g2):
        for prop in g2.subjects(RDF.type, OWL.ObjectProperty):
            g2.remove((prop, sqlgen.P("references"), None))
            return
    g2, _ = graph_after(drop_ref)
    still = sum(1 for n in metrics if not refused(sqlgen.compile_metric, g2, n))
    check_true("C4b removing a link's :references changes the set of answerable metrics",
               still < len(compiled), f"{still} still compile — the link was not load-bearing")

    # 4c misspell a formula column
    name = next((n for n, m in metrics.items() if m.formula), None)
    def misspell(g2):
        g2.remove((_p(name), sqlgen.P("formula"), None))
        g2.add((_p(name), sqlgen.P("formula"), Literal("no_such_column_xyz")))
    g2, _ = graph_after(misspell)
    msg = refused(sqlgen.compile_metric, g2, name)
    check_true(f"C4c a misspelled formula column on :{name} refuses", bool(msg),
               "it compiled with a column that does not exist")
    print(f"         {msg and msg.splitlines()[0]}")

    # 4d duplicate a column onto a second class (ambiguity must refuse)
    def duplicate(g2):
        prop = _p("city")
        g2.remove((prop, RDFS.domain, None))
        g2.add((prop, RDFS.domain, _p(classes[0])))
        g2.add((prop, RDFS.domain, _p(classes[-1])))
    g2, _ = graph_after(duplicate)
    ambiguous = [n for n in metrics if refused(sqlgen.compile_metric, g2, n)]
    check_true("C4d an ambiguous column (two domains) refuses somewhere",
               bool(ambiguous), "nothing noticed the duplication")

    # 4e delete a :where axiom → the metric either refuses or its number MOVES
    whys = [(n, m.where) for n, m in metrics.items() if m.where]
    if not whys:
        not_run("C4e", "no metric declares :where, so there is no axiom to delete")
    else:
        name, where = whys[0]
        before = None
        if not refused(sqlgen.compile_metric, g, name):
            before = scalar(sqlgen.compile_metric(g, name).sql.rstrip().rstrip(";"))
        def drop_axiom(g2):
            g2.remove((_p(where), OWL.equivalentClass, None))
            for o in list(g2.objects(_p(where), sqlgen.P("physicalPredicate"))):
                g2.remove((_p(where), sqlgen.P("physicalPredicate"), o))
        g2, _ = graph_after(drop_axiom)
        msg = refused(sqlgen.compile_metric, g2, name)
        after = None if msg else scalar(sqlgen.compile_metric(g2, name).sql.rstrip().rstrip(";"))
        check_true(f"C4e removing :{where}'s definition makes :{name} refuse or move",
                   bool(msg) or (before is not None and after != before),
                   f"before {before!r}, after {after!r} — a deleted axiom changed nothing")
        print(f"         {msg.splitlines()[0] if msg else f'number moved {before} -> {after}'}")

    # ── C5 affordance conflict ────────────────────────────────────────────────
    both = []
    for cls in classes:
        if list(g.objects(_p(cls), OWL.equivalentClass)) and \
                list(g.objects(_p(cls), sqlgen.P("physicalPredicate"))):
            both.append(cls)
    check_true("C5 no class carries both an axiom and a :physicalPredicate", not both, str(both))


# ══════════════════════════════════════════════════════════ R — reasoning gates
def reasoning_gates(profile: dict, g, cur) -> None:
    print("\nR — reasoning (definitions mean what the business said)")
    classes = sorted({str(s).split("#")[-1] for s in g.subjects(RDF.type, OWL.Class)
                      if str(s).startswith(sqlgen.NS)})
    axioms = [c for c in classes
              if list(g.objects(_p(c), OWL.equivalentClass))
              or list(g.objects(_p(c), sqlgen.P("physicalPredicate")))]
    check_true("R1 the ontology declares at least one definition", bool(axioms), "no axioms")
    print(f"       definitions: {axioms}")

    def scalar(sql):
        cur.execute(sql)
        row = cur.fetchone()
        return int(row[0]) if row else 0

    empty = []
    for cls in axioms:
        msg = refused(sqlgen.concept_sql, g, cls)
        if msg:
            empty.append(f"{cls} (refused: {msg.splitlines()[0]})")
            continue
        table = definition_table(g, cls, sqlgen.metrics(g))
        if not table:
            empty.append(f"{cls} (no table resolved)")
            continue
        n = scalar(f"select count(*) from {sqlgen.table_of(g, table)} "
                   f"where {sqlgen.concept_sql(g, cls)}")
        if n == 0:
            empty.append(f"{cls} (selects 0 rows)")
    check_true("R2a every definition compiles and selects at least one row", not empty, str(empty))

    # R2b entailment: the compiled definition == an independent, column-level statement of
    # the same meaning. Thresholds are read from the graph, never retyped.
    entail = {
        "NoShowAppointment": ("appointments", "status = 'no_show'"),
        "CancelledAppointment": ("appointments", "status = 'cancelled'"),
        "CompletedAppointment": ("appointments", "status = 'completed'"),
    }
    compared = 0
    for cls, (table, pred) in entail.items():
        if cls not in classes:
            not_run(f"R2b {cls}", "not declared in this ontology")
            continue
        msg = refused(sqlgen.concept_sql, g, cls)
        if msg:
            not_run(f"R2b {cls}", f"refused: {msg.splitlines()[0]}")
            continue
        got = scalar(f"select count(*) from {table} where {sqlgen.concept_sql(g, cls)}")
        want = scalar(f"select count(*) from {table} where {pred}")
        compared += 1
        check_true(f"R2b :{cls} entails exactly `{pred}`", got == want, f"{got} vs {want}")
    check_true("R2b the entailment gate compared definitions", compared >= 2, f"{compared} compared")

    # R3 samples: every question answers or refuses BY NAME (deterministic rules only)
    samples = profile.get("samples") or []
    check_true("R3a the profile carries samples", len(samples) >= 8, f"{len(samples)} samples")
    if not samples:
        return
    os_env = dict(sys.modules.get("os").environ) if "os" in sys.modules else {}
    import os
    os.environ.setdefault("APP_SETTINGS", str(profile["_path"]))
    try:
        import nl
    except Exception as exc:                                   # noqa: BLE001
        not_run("R3 samples", f"nl.py is not importable here: {type(exc).__name__}: {exc}")
        return
    menu = nl.menu(g)
    answered, refused_by_name, unexplained = 0, 0, []
    for q in samples:
        try:
            nl.interpret(q, menu)
            answered += 1
        except nl.NlRefusal as exc:
            refused_by_name += 1
            if not str(exc).strip():
                unexplained.append(q)
        except Exception as exc:                               # noqa: BLE001
            unexplained.append(f"{q} ({type(exc).__name__})")
    check_true("R3b every sample answers or refuses by name",
               not unexplained, f"unexplained: {unexplained[:3]}")
    check_true("R3c the sample set includes a refusal (a sample that always answers is not a test)",
               refused_by_name >= 1, f"{answered} answered, {refused_by_name} refused")
    print(f"       samples: {answered} answered · {refused_by_name} refused by name · {len(samples)} total")

    # R4 an OWL reasoner must ENTAIL the definitions — not just parse them. A DL reasoner
    # that loads the file and says "consistent" has proven nothing (an empty ontology is
    # also consistent), so this gate asserts a subclass is *inferred* for an individual
    # whose only asserted facts are "it is an Appointment" and "its status is no_show".
    # Runs under the repo venv (owlready2 + Java/HermiT); skipped BY NAME when unavailable.
    reasoner_probe(profile, g)

    # R5 the SPARQL lane (Ontop) needs an R2RML mapping; without one there is nothing to
    # serve, and saying so IS the gate.
    rdf_mapping = (profile["_base"] / "mapping.ttl").exists() if profile.get("_base") else False
    if not rdf_mapping:
        not_run("R5 SPARQL lane (Ontop over R2RML)",
                "no R2RML mapping for this dataset, so lane B has nothing to serve — "
                "a green here would be a lie")
    else:
        not_run("R5 SPARQL lane", "mapping present but the lane-B runner is not wired here")


def reasoner_probe(profile: dict, g) -> None:
    """R4: HermiT must infer membership from the axiom, on a synthetic individual."""
    import subprocess
    import tempfile

    dl_python = HERE.parent / ".venv" / "bin" / "python"
    if not dl_python.exists():
        not_run("R4 OWL reasoner entailment", f"no interpreter with owlready2 at {dl_python}")
        return
    base = profile.get("_base") or HERE
    onto_dir = base / (profile.get("ontology_dir") or "ontology")
    overlay = base / profile["overlay"] if profile.get("overlay") else None
    files = sorted(onto_dir.glob("*.ttl")) + ([overlay] if overlay and overlay.exists() else [])
    probe = pathlib.Path(tempfile.mkdtemp(prefix="clinic-reasoner-")) / "probe.py"
    probe.write_text(f"""
import pathlib, rdflib, owlready2

src = {[str(f) for f in files]!r}
MUTATE = False


def run(mutate: bool):
    g = rdflib.Graph()
    for p in src:
        g.parse(p, format="turtle")
    if mutate:
        # cut the definition this gate exists to check
        from rdflib import OWL, URIRef
        cls = next(s for s in g.subjects(None, None)
                   if str(s).endswith("#NoShowAppointment"))
        for axiom in list(g.objects(cls, OWL.equivalentClass)):
            g.remove((cls, OWL.equivalentClass, axiom))
    out = pathlib.Path(tempfile_dir) / ("c_mut.owl" if mutate else "c.owl")
    g.serialize(destination=str(out), format="xml")
    onto = owlready2.get_ontology(f"file://{{out}}").load()
    Appt = onto.search_one(iri="*#Appointment")
    Status = onto.search_one(iri="*#appointmentStatus")
    with onto:
        a = Appt("probe_no_show")
        b = Appt("probe_completed")
    a.appointmentStatus = ["no_show"]
    b.appointmentStatus = ["completed"]
    with onto:
        owlready2.sync_reasoner_hermit(debug=0)
    inferred_a = [x.name for x in onto["probe_no_show"].is_a]
    inferred_b = [x.name for x in onto["probe_completed"].is_a]
    unsat = [c.name for c in onto.inconsistent_classes()]
    return inferred_a, inferred_b, unsat


tempfile_dir = {str(base)!r}
a1, b1, u1 = run(MUTATE)
print("PROBE", "no_show:", a1, "completed:", b1, "unsat:", u1, "mutated:", MUTATE)
""", encoding="utf-8")
    def run_probe() -> str:
        try:
            res = subprocess.run([str(dl_python), str(probe)], capture_output=True, text=True,
                                 timeout=300)
        except Exception as exc:                               # noqa: BLE001
            return f"ERROR {type(exc).__name__}: {exc}"
        line = next((ln for ln in (res.stdout or "").splitlines() if ln.startswith("PROBE")), "")
        return line or f"ERROR {(res.stderr or '')[-300:]}"

    line = run_probe()
    if line.startswith("ERROR"):
        not_run("R4 OWL reasoner entailment", f"the reasoner did not run: {line[6:]}")
        return
    print(f"       {line.replace('PROBE ', '')}")
    check_true("R4a HermiT infers :NoShowAppointment for a no_show appointment",
               "no_show: ['NoShowAppointment']" in line, line)
    check_true("R4b HermiT infers :CompletedAppointment for a completed appointment",
               "completed: ['CompletedAppointment']" in line, line)
    check_true("R4c no class is unsatisfiable (the axioms contradict nothing)",
               "unsat: []" in line, line)

    # R4d the gate must be able to go red: remove the axiom, rerun, the inference must vanish
    s_text = probe.read_text()
    probe.write_text(s_text.replace("MUTATE = False", "MUTATE = 'true'"))
    mutated = run_probe()
    probe.write_text(s_text)
    if mutated.startswith("ERROR"):
        not_run("R4d R4 mutation", mutated[6:])
    else:
        lost = "no_show: []" in mutated or "NoShowAppointment" not in mutated
        check_true("R4d removing the axiom loses the inference (the gate bites)", lost, mutated)


# ══════════════════════════════════════════════════════════ G — guardrail gates
def guard_gates(profile: dict, g, cur) -> None:
    print("\nG — SQL guardrails")
    cfg = copy.deepcopy(profile["guard"])
    check_true("G0 the guard is enabled in this profile", bool(cfg.get("enabled")), str(cfg))
    big = list((cfg.get("big_tables") or {}).items())
    check_true("G1a the profile names its big tables", bool(big), "no big_tables — nothing to bound")
    print(f"       big tables: {big}")

    table, col = big[0]
    listing = f"select * from {table}"

    # G1 page cap
    guarded = guard.apply(listing, cfg, mode="rows")
    check_true("G1b an unpaged listing gets a LIMIT at max_rows",
               f"LIMIT {int(cfg['max_rows'])}" in guarded["sql"], guarded["sql"][-80:])

    # G2 time bound vs refuse, whichever the profile's data calls for
    days = int(cfg.get("default_window_days") or 0)
    if days > 0:
        check_true(f"G2 a now()-relative window of {days}d is injected",
                   guarded.get("window") is not None, str(guarded.get("notes")))
    else:
        msg = refused(guard.apply, listing, cfg, mode="rows")
        check_true("G2 default_window_days = 0 REFUSES an unbounded scan", bool(msg),
                   "the guard narrowed instead of refusing a historical dataset")
        print(f"         {msg}")

    # G3a the budget measures the PLAN, not the scan: a cartesian join's cost lives on its
    # join node (measured: 2,493 scan rows vs 7,569,004 on the Nested Loop — the first
    # version of plan_rows() admitted a 15.9M-row answer because it only read scans).
    cart = "select count(*) from invoices i, payments p"
    est = None
    try:
        est = guard.plan_rows(cur, cart, cfg=cfg)
    except Exception as exc:                                   # noqa: BLE001
        not_run("G3a", f"EXPLAIN failed: {exc}")
    if est is not None:
        scan_est = guard.plan_rows(cur, "select count(*) from treatment_lines", cfg=cfg)
        check_true("G3a a fan-out plan is budgeted by its join, not its scan",
                   est > scan_est, f"cartesian {est} vs single-table {scan_est}")
        msg = refused(guard.run, cur, cart, cfg=cfg, mode="declared")
        check_true("G3a a 7.5M-row cartesian plan is refused by the budget", bool(msg), str(msg))
        print(f"         {est:,} rows estimated -> {str(msg).splitlines()[0] if msg else 'ALLOWED'}")

    # G3 plan budget bites when the budget is small
    tight = copy.deepcopy(cfg)
    tight["max_plan_rows"] = 1
    msg = refused(guard.run, cur, f"select * from {table}", cfg=tight, mode="declared")
    check_true("G3 a plan over max_plan_rows is refused", bool(msg) and "budget" in str(msg),
               str(msg))
    print(f"         {str(msg).splitlines()[0] if msg else '(no refusal)'}")

    # G4 a declared metric is NEVER windowed by the guard
    metric = next((n for n, m in sqlgen.metrics(g).items()
                   if m.aggregate and not refused(sqlgen.compile_metric, g, n)), None)
    if metric is None:
        not_run("G4", "no compiled metric to test")
    else:
        sql = sqlgen.compile_metric(g, metric).sql
        res = guard.apply(sql, cfg, mode="declared")
        check_true(f"G4a :{metric} is not windowed (its definition has no window)",
                   res.get("window") is None and "now() -" not in res["sql"],
                   res["sql"][:120])
        check_true("G4b the unbounded scan is REPORTED instead of silently rewritten",
                   any("unbounded scan" in n for n in res.get("notes") or []),
                   str(res.get("notes")))

    # G5 the statement timeout bites
    short = copy.deepcopy(cfg)
    short["statement_timeout_ms"] = 400
    short["max_plan_rows"] = 10 ** 9
    t0 = time.perf_counter()
    msg = refused(guard.run, cur, "select pg_sleep(3)", cfg=short, mode="declared")
    took = time.perf_counter() - t0
    check_true("G5 a query over statement_timeout is aborted",
               bool(msg) and took < 2.5, f"took {took:.2f}s, refusal={msg}")
    print(f"         aborted after {took * 1000:.0f} ms")

    # G6 an empty window is reported as such (not a silent 0). This dataset is
    # now-relative, so a real table always has recent rows — the case is provoked with a
    # session-local temp table whose only row is years old. Creating it is honest: the
    # thing under test is the guard's reporting, not the clinic data.
    g6 = copy.deepcopy(cfg)
    g6["default_window_days"] = 30
    g6["big_tables"] = {"guard_probe_old": "ts"}
    g6["max_plan_rows"] = 10 ** 9
    cur.execute("create temp table guard_probe_old (ts timestamptz, v int)")
    cur.execute("insert into guard_probe_old values (timestamptz '2020-01-01', 1)")
    try:
        res = guard.run(cur, "select * from guard_probe_old", cfg=g6, mode="rows")
        notes = res.get("notes") or []
        check_true("G6 a window that matches nothing is reported, not silently 0",
                   any("matched 0 rows" in n for n in notes) and len(res.get("rows") or []) == 0,
                   str(notes))
        print(f"         {[n for n in notes if 'matched 0' in n]}")
    except guard.Refusal as exc:
        not_run("G6 empty window", f"the guard refused instead of narrowing: {exc}")


# ══════════════════════════════════════════════════════════════════ main
def main() -> int:
    ap = argparse.ArgumentParser()
    # the default is the feature's own clinic profile (features/ontology/profiles/clinic/…)
    ap.add_argument("--profile", default=str(HERE.parent / "profiles" / "clinic"
                                             / "clinic_settings.json"))
    args = ap.parse_args()
    profile_path = pathlib.Path(args.profile).expanduser().resolve()
    if not profile_path.exists():
        print(f"no profile at {profile_path}")
        return 2
    profile, g = load(profile_path)
    profile["_path"] = profile_path
    profile["_base"] = profile_path.parent
    print(f"profile: {profile_path}")
    print(f"ns:      {sqlgen.NS}")
    print(f"dsn:     {profile['_dsn']}")

    conn = psycopg2.connect(profile["_dsn"])
    conn.autocommit = True
    cur = conn.cursor()
    try:
        ontology_gates(profile, g, cur)
        reasoning_gates(profile, g, cur)
        guard_gates(profile, g, cur)
    finally:
        conn.close()

    print()
    if NOT_RUN:
        print("NOT RUN (an unrun gate is not a passed gate):")
        for item in NOT_RUN:
            print(f"  · {item}")
    print("ALL GATES PASS" if OK and not NOT_RUN else
          ("GATES PASS (with NOT RUN items)" if OK else "SOME GATES FAILED"))
    return 0 if (OK and not NOT_RUN) else 1


if __name__ == "__main__":
    sys.exit(main())

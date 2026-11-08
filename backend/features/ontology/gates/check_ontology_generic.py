#!/usr/bin/env python3
"""check_ontology_generic.py — the gates that any profile must pass, dataset-independent.

`check_clinic.py` hard-codes one dataset's truth queries; this one runs the gates that can be
derived from any profile, so a newly built ontology (a DeepAgent's output, say) can be judged
before anybody builds a dashboard on it:

  C  structure/config   objects name a table + key; definitions resolve to an object; every
                        metric compiles or refuses BY NAME; two mutations must go red
  R  reasoning          every definition compiles and selects rows; a definition's compiled
                        predicate matches an independent column-level statement (from
                        `--truth-def`, or the profile's own `truth.json`)
  G  guardrails         page cap, window-or-refuse, plan budget (incl. fan-out), statement
                        timeout, a declared metric is never windowed, an empty window is reported
  T  tutorial           `tutorial.json` names only declared things, a metric step runs, and the
                        set teaches at least one refusal
  X  portability        no declaration names a machine path (/Users/…, C:\…): the profile has to
                        compile and answer on the machine that serves it, not only on the laptop it
                        was written on — and the scanner proves it can fail (X1b)

`--truth` is `{metric: number}` with numbers produced by a SECOND, hand-written route. Without
it the metric-vs-truth gate is reported NOT RUN — never silently green.

    python check_ontology_generic.py --profile ../ontologies/logistics/logistics_settings.json
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import pathlib
import re
import sys
import tempfile
import time

HERE = pathlib.Path(__file__).resolve().parent
# The COMPILER lives one directory up (features/ontology/compiler) and its modules import each
# other by bare name, so its directory goes on sys.path — a path that never depends on where this
# repository happens to live.
import pathlib as _pathlib
import sys as _sys
sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[1] / "compiler"))

import psycopg2  # noqa: E402
import guard  # noqa: E402
import sqlgen  # noqa: E402
from rdflib import OWL, RDF, RDFS, URIRef  # noqa: E402

OK = True
NOT_RUN: list[str] = []

#: An absolute path that belongs to ONE machine (`/Users/x`, `/home/u`, `/root/…`, `C:\Users\…`).
#: A DERIVED path (`schema/actions.yml`), an env-substituted dsn (`${ONTOLOGY_DB_HOST:-…}`) and an
#: origin-relative URL (`/api/…`) are none of these: they mean the same thing on every install.
MACHINE_PATH = re.compile(r"(?<![\w/.])/(?:Users|home|root|opt|srv|var)/[\w.@+-]+"
                          r"|(?<![\w/])[A-Za-z]:\\")


def check(label: str, got, want) -> None:
    global OK
    good = got == want
    OK = OK and good
    print(f"  [{'PASS' if good else 'FAIL'}] {label}: got {got!r}, want {want!r}")


def check_true(label: str, cond: bool, detail: str = "") -> None:
    global OK
    OK = OK and bool(cond)
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + ("" if cond else f" — {detail}"))


def not_run(gate: str, why: str) -> None:
    NOT_RUN.append(f"{gate}: {why}")
    print(f"  [NOT RUN] {gate} — {why}")


def refused(fn, *a, **kw) -> str | None:
    try:
        fn(*a, **kw)
        return None
    except Exception as exc:                                   # noqa: BLE001
        return str(exc)


def load(profile_path: pathlib.Path):
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile["_base"] = profile_path.parent
    profile["_path"] = str(profile_path)

    def rel(key: str) -> pathlib.Path:
        p = pathlib.Path(profile.get(key) or "")
        return p if p.is_absolute() else (profile["_base"] / p).resolve()

    sqlgen.reconfigure(ns=profile.get("ns"),
                       ontology_dir=str(rel("ontology_dir")),
                       overlay=str(rel("overlay")) if profile.get("overlay") else "",
                       drop_overlay=not profile.get("overlay"))
    g = sqlgen.load()
    import dsn as _dsn

    dsn = " ".join(f"{k}={v}" for k, v in _dsn.resolved(profile).items()
                   if v not in (None, ""))
    return profile, g, dsn


def P(local: str):
    return URIRef(f"{sqlgen.NS}{local}")


def definition_table(g, cls: str, metrics: dict | None = None, depth: int = 4) -> str | None:
    metrics = metrics or {}
    base = sqlgen.concept_base_class(g, cls)
    if base:
        return base
    for axiom in g.objects(P(cls), OWL.equivalentClass):
        members = []
        for lst in g.objects(axiom, OWL.unionOf):
            members = [str(m).split("#")[-1] for m in g.items(lst)]
        if members and depth > 0:
            bases = {definition_table(g, m, metrics, depth - 1) for m in members}
            bases.discard(None)
            if len(bases) == 1:
                return bases.pop()
    if list(g.objects(P(cls), sqlgen.P("physicalPredicate"))):
        users = [m for m in metrics.values() if m.where == cls and m.universe]
        universes = {u.universe for u in users}
        if len(universes) == 1:
            return universes.pop()
    return None


# ═══════════════════════════════════════════════════════════ C
def structure_gates(profile, g, cur) -> None:
    print("\nC — structure")
    classes = sorted({str(s).split("#")[-1] for s in g.subjects(RDF.type, OWL.Class)
                      if str(s).startswith(sqlgen.NS)})
    # Three shapes are legitimate, and nothing else is:
    #   object     — a table with a primary key
    #   definition — an axiom, or the one :physicalPredicate escape hatch
    #   deferred   — neither, but carrying a :refusalReason that says what is missing.
    # A class with none of the three is an unannotated term: nobody can tell whether it is a
    # half-written object or a forgotten definition. Measured on the logistic build: two
    # deferred classes (AtRiskDriver, PlannedStopVisited) were correctly refused by the
    # compiler *because* they were declared with their reasons — that is the deliverable, not
    # a defect, so the gate must recognise it instead of demanding a table.
    objects, definitions, deferred = [], [], []
    for cls in classes:
        has_axiom = bool(list(g.objects(P(cls), OWL.equivalentClass))) or \
            bool(list(g.objects(P(cls), P("physicalPredicate"))))
        has_table = bool(g.value(P(cls), P("physicalTable")))
        if has_axiom:
            definitions.append(cls)
        elif has_table:
            objects.append(cls)
        else:
            deferred.append(cls)
    print(f"       {len(objects)} objects · {len(definitions)} definitions · {len(deferred)} deferred")
    check_true("C0 the graph declares objects", len(objects) >= 3, f"{objects}")

    bad = [c for c in objects
           if not g.value(P(c), P("physicalTable")) or not g.value(P(c), P("primaryKey"))]
    check_true("C1a every object names a table and a primary key", not bad, str(bad))

    no_reason = [c for c in deferred
                 if not (g.value(P(c), P("refusalReason")) or g.value(P(c), P("businessDescription")))]
    check_true("C1d a deferred class says why it is undefined (:refusalReason)",
               not no_reason, f"{no_reason} — declare the axiom or write the reason")

    metrics_now = sqlgen.metrics(g)
    orphans = [c for c in definitions if not definition_table(g, c, metrics_now)]
    check_true("C1b every definition resolves to a declared object", not orphans, str(orphans))

    links = [(str(p).split("#")[-1],
              g.value(p, P("physicalColumn")), g.value(p, P("references")))
             for p in g.subjects(RDF.type, OWL.ObjectProperty)]

    def inverse_backed(prop_node) -> bool:
        """A link may carry NO column when its INVERSE carries it — and then the inverse must.

        The FK lives on one side only: `dispatch_decisions.trip_id` is declared on :decidedTripOf
        (DispatchDecision -> Trip), so the Trip-side link (:decisionsOf) legitimately declares
        `owl:inverseOf` and no column. Reading and writing resolve the same declaration either way;
        what the gate must never accept is a link whose join exists on NEITHER side.
        """
        inv = next(iter(g.objects(prop_node, OWL.inverseOf)), None)
        if inv is None:
            return False
        return bool(g.value(inv, P("physicalColumn")) and g.value(inv, P("references")))

    props = list(g.subjects(RDF.type, OWL.ObjectProperty))
    broken = [l for l, node in zip(links, props)
              if (not l[1] or not l[2] or str(l[2]).split("#")[-1] not in objects)
              and not inverse_backed(node)]
    check_true("C1c every link has a column and a declared target (or an inverse that has both)",
               not broken, str(broken))
    print(f"       {len(links)} links")

    compiled, refusals = [], []
    for name in metrics_now:
        msg = refused(sqlgen.compile_metric, g, name)
        (refusals if msg else compiled).append((name, msg))
    check_true("C2a some metrics compile", bool(compiled), f"nothing compiled: {[r[0] for r in refusals]}")
    print(f"       compiled {len(compiled)} · refused by name {len(refusals)}")
    for n, why in refusals:
        print(f"         REFUSED {n}: {why.splitlines()[0]}")
    check_true("C2b every refusal names a reason", all(w and len(w) > 10 for _, w in refusals), str(refusals))

    # ── C5: the MENU and the SOURCE — two rules that were prose-only, and got skipped
    # Measured on a v6 build: 43 metrics, 0 of them carrying :askedAs, and 11 with no source sentence,
    # while every gate stayed green. A metric nobody can ask for does not exist for a user, and a number
    # with no source is a guess that compiled. Both are now checks, not advice.
    no_ask = [n for n in metrics_now if not g.value(P(n), P("askedAs"))]
    check_true("C5a every metric declares an :askedAs (the menu is a declaration)",
               not no_ask, f"{len(no_ask)} without one: {sorted(no_ask)[:6]}")

    SOURCE_MARKERS = ("answers:", "docx", "doc#", "refused:", "measured:", "table:")
    no_src = []
    for n in metrics_now:
        # ALL descriptions on the predicate, not `g.value`: a metric that shares its name with a
        # column carries two of them (the column's, from 01-structure, and the metric's, from the
        # overlay) and `g.value` returns whichever it likes — measured as a false FAIL on
        # :tripRevenue, whose overlay description does say 口径来自 answers:Q1.
        descs = [str(v) for v in g.objects(P(n), P("businessDescription"))]
        if not any(any(m in d for m in SOURCE_MARKERS) for d in descs):
            no_src.append(n)
    check_true("C5b every metric's :businessDescription names its source (a metric with no source is "
               "not a declaration — it goes on the refusal list)",
               not no_src, f"{len(no_src)} without a source: {sorted(no_src)[:6]}")

    # mutations must go red
    name = next((n for n, m in metrics_now.items() if m.grain), None)
    if name is None:
        not_run("C4 mutations", "no metric declares a :grain to remove")
        return
    g2 = sqlgen.load()
    g2.remove((P(name), P("grain"), None))
    check_true(f"C4a deleting :grain on :{name} refuses", bool(refused(sqlgen.compile_metric, g2, name)))

    fname = next((n for n, m in metrics_now.items() if m.formula), None)
    if fname is None:
        not_run("C4b", "no metric declares a :formula to misspell")
    else:
        g3 = sqlgen.load()
        g3.remove((P(fname), P("formula"), None))
        from rdflib import Literal
        g3.add((P(fname), P("formula"), Literal("no_such_column_xyz")))
        check_true(f"C4b a misspelled formula column on :{fname} refuses",
                   bool(refused(sqlgen.compile_metric, g3, fname)))

    # C5c: a gate that cannot fail is decoration — remove one :askedAs and C5a must go red
    asked = next((n for n in metrics_now if g.value(P(n), P("askedAs"))), None)
    if asked is None:
        not_run("C5c mutation", "no metric declares an :askedAs to remove (C5a is already red)")
    else:
        g4 = sqlgen.load()
        g4.remove((P(asked), P("askedAs"), None))
        still = [n for n in sqlgen.metrics(g4) if not g4.value(P(n), P("askedAs"))]
        check_true(f"C5c removing :askedAs from :{asked} turns C5a red", bool(still), True)


# ═══════════════════════════════════════════════════════════ R
def reasoning_gates(profile, g, cur, truth: dict | None) -> None:
    print("\nR — reasoning")
    classes = sorted({str(s).split("#")[-1] for s in g.subjects(RDF.type, OWL.Class)
                      if str(s).startswith(sqlgen.NS)})
    definitions = [c for c in classes
                   if list(g.objects(P(c), OWL.equivalentClass))
                   or list(g.objects(P(c), P("physicalPredicate")))]
    empty = []
    for cls in definitions:
        msg = refused(sqlgen.concept_sql, g, cls)
        if msg:
            empty.append(f"{cls} (refused: {msg.splitlines()[0]})")
            continue
        table = definition_table(g, cls, sqlgen.metrics(g))
        if not table:
            # A definition whose table comes from a METRIC (`:where :X` + `:universe`) cannot be checked
            # before those metrics exist. Measured while building new_coldchain: the meaning layer is
            # written before the computation layer, so a predicate-only concept legitimately has no table
            # yet. Calling that a FAILURE would force a build to write metrics before definitions — the
            # opposite of the order that keeps definitions honest. Name it as NOT RUN instead.
            NOT_RUN.append(f"R1 {cls}: no metric declares it as :where yet, so it has no table to count over")
            continue
        pred = sqlgen.concept_sql(g, cls)
        outer = sqlgen.table_of(g, table)
        try:
            cur.execute(f"SELECT count(*) FROM {outer} WHERE {pred}")
            n = cur.fetchone()[0]
        except Exception as exc:                               # noqa: BLE001 — a broken predicate is a FAIL
            # The most common shape: a :physicalPredicate that names a table alias ("c.amount IS NULL").
            # The compiler emits the FROM itself, so declared predicates are UNQUALIFIED columns (abc's
            # "liability IS NULL" is the reference). Say that instead of a raw psycopg2 error.
            empty.append(f"{cls} (predicate does not run over {outer}: {type(exc).__name__}: "
                         f"{str(exc).splitlines()[0][:120]} — declared predicates use UNQUALIFIED columns)")
            continue
        if not n:
            # A predicate that exists over an EMPTY relation cannot be disproved by counting: 0 rows is
            # the correct answer, not a broken axiom. Name the unrun case instead of failing it — and
            # keep FAILING when the table has rows and the axiom still selects none, because that is
            # the broken-predicate case this gate exists for.
            import re as _re
            touched = {t for t in _re.findall(r"\b(?:FROM|JOIN)\s+([a-z_][a-z0-9_]*)",
                                              pred, _re.I)}
            empty_tables = []
            for tname in sorted(touched):
                try:
                    cur.execute(f"SELECT count(*) FROM {tname}")
                    if cur.fetchone()[0] == 0:
                        empty_tables.append(tname)
                except Exception:                                  # noqa: BLE001  (not a table)
                    continue
            if empty_tables:
                not_run("R1", f":{cls} — {', '.join(empty_tables)} is empty, so a selective "
                               f"predicate over it cannot be tested (the 0 is correct)")
                continue
            empty.append(f"{cls} (0 rows)")
    check_true("R1 every definition compiles and selects rows (empty relations NOT RUN, by name)",
               not empty, str(empty))

    # a definition's compiled predicate vs an independent column-level statement
    truth_def = (truth or {}).get("_definitions") or {}
    if not truth_def:
        not_run("R2 definition == hand SQL",
                "no truth.json `_definitions` map in this profile; the gate is declared, not run")
        return
    compared = 0
    for cls, (table, pred) in truth_def.items():
        if cls not in classes:
            not_run(f"R2 {cls}", "not declared")
            continue
        cur.execute(f"SELECT count(*) FROM {table} WHERE {pred}")
        want = cur.fetchone()[0]
        cur.execute(f"SELECT count(*) FROM {sqlgen.table_of(g, definition_table(g, cls, sqlgen.metrics(g)))} "
                    f"WHERE {sqlgen.concept_sql(g, cls)}")
        got = cur.fetchone()[0]
        compared += 1
        check_true(f"R2 :{cls} entails `{pred}`", got == want, f"{got} vs {want}")
    check_true("R2 the entailment gate compared definitions", compared >= 1, f"{compared}")


# ═══════════════════════════════════════════════════════════ G
def guard_gates(profile, g, cur) -> None:
    print("\nG — guardrails")
    cfg = copy.deepcopy(profile.get("guard") or {})
    check_true("G0 the guard is enabled", bool(cfg.get("enabled")), str(cfg))
    big = list((cfg.get("big_tables") or {}).items())
    check_true("G1a the profile names its big tables", bool(big), "no big_tables")

    # G1c: the window the guard injects goes on a column the profile names — so that column must EXIST.
    # Measured on abc: `big_tables: {"stops": "trip_date"}` when `stops` has no `trip_date` (its date is
    # trips.trip_date, one join away). Every read of stops then died with
    # `column stops.trip_date does not exist`, including the training page's own table. logistics had
    # the same table declared the same way and documented the rule in its settings; ABC never got it.
    def column_exists(table: str, column: str) -> bool:
        cur.execute("select 1 from information_schema.columns "
                    "where table_name = %s and column_name = %s", (table, column))
        return cur.fetchone() is not None

    missing = [f"{t}.{c}" for t, c in big if not column_exists(t, c)]
    check_true("G1c every big_table's window column exists", not missing,
               f"{', '.join(missing)} — the guard would inject a window on a column that is not there")
    if missing:
        print(f"         missing: {', '.join(missing)}")
    large = list(cfg.get("large_tables") or [])
    if large:
        def table_exists(t: str) -> bool:
            cur.execute("select 1 from information_schema.tables where table_name = %s", (t,))
            return cur.fetchone() is not None

        gone = [t for t in large if not table_exists(t)]
        check_true("G1d every large_table exists", not gone, ", ".join(gone))
        overlap = sorted(set(large) & {t for t, _ in big})
        check_true("G1e a table is not both big and large", not overlap,
                   f"{overlap} — big_tables windows it, large_tables only budgets it")

    if not big:
        return
    table, col = big[0]
    window_relative = int(cfg.get("default_window_days") or 0) > 0

    # A profile whose data sits in a FIXED historical window is told to refuse an unbounded scan rather than
    # narrow it — and `guard.apply` then RAISES. The old first line called apply() unguarded, so those
    # profiles crashed the gate instead of failing a check (measured on new_coldchain, default_window_days=0,
    # which is what its own documentation requires). Ask for the refusal first, and only when a relative
    # window is meaningful demand a windowed query.
    refusal = refused(guard.apply, f"select * from {table}", cfg, mode="rows")
    if window_relative:
        g1 = guard.apply(f"select * from {table}", cfg, mode="rows")
        check_true("G1b an unpaged listing gets a LIMIT", f"LIMIT {int(cfg['max_rows'])}" in g1["sql"],
                   g1["sql"][-60:])
        check_true("G2 a now()-relative window is injected", g1.get("window") is not None, str(g1.get("notes")))
    else:
        check_true(f"G1b an unbounded scan of {table} is REFUSED by name", bool(refusal) and col in str(refusal),
                   str(refusal))
        # the page cap still applies once the query carries its own explicit bound
        g1 = guard.apply(f"select * from {table} where {col} >= date '2026-08-01'", cfg, mode="rows")
        check_true("G1c a bounded listing is still capped, not windowed",
                   f"LIMIT {int(cfg['max_rows'])}" in g1["sql"] and g1.get("window") is None, g1["sql"][-60:])
        check_true("G2 default_window_days = 0 refuses an unbounded scan", bool(refusal), "it narrowed instead")

    cart = f"select count(*) from {table} a, {table} b"
    est = guard.plan_rows(cur, cart, cfg=cfg)
    check_true("G3a a fan-out plan is budgeted", est > 0, f"plan_rows={est}")
    print(f"         cartesian estimate: {est:,} rows")

    tight = copy.deepcopy(cfg)
    tight["max_plan_rows"] = 1
    msg = refused(guard.run, cur, f"select * from {table}", cfg=tight, mode="declared")
    check_true("G3b a plan over max_plan_rows is refused", bool(msg) and "budget" in str(msg), str(msg))

    metric = next((n for n, m in sqlgen.metrics(g).items()
                   if m.aggregate and not refused(sqlgen.compile_metric, g, n)), None)
    if metric is None:
        not_run("G4", "no compiled metric")
    else:
        sql = sqlgen.compile_metric(g, metric).sql
        res = guard.apply(sql, cfg, mode="declared")
        check_true(f"G4a :{metric} is not windowed", res.get("window") is None and "now() -" not in res["sql"])
        check_true("G4b the unbounded scan is reported", any("unbounded scan" in n for n in (res.get("notes") or [])),
                   str(res.get("notes")))

    short = copy.deepcopy(cfg)
    short["statement_timeout_ms"] = 400
    short["max_plan_rows"] = 10 ** 9
    t0 = time.perf_counter()
    msg = refused(guard.run, cur, "select pg_sleep(3)", cfg=short, mode="declared")
    took = time.perf_counter() - t0
    check_true("G5 a query over statement_timeout is aborted", bool(msg) and took < 2.5, f"{took:.2f}s {msg}")
    print(f"         aborted after {took * 1000:.0f} ms")

    g6 = copy.deepcopy(cfg)
    g6["default_window_days"] = 30
    g6["max_plan_rows"] = 10 ** 9
    g6["big_tables"] = {"guard_probe_old": "ts"}
    cur.execute("create temp table guard_probe_old (ts timestamptz, v int)")
    cur.execute("insert into guard_probe_old values (timestamptz '2020-01-01', 1)")
    try:
        res = guard.run(cur, "select * from guard_probe_old", cfg=g6, mode="rows")
        notes = res.get("notes") or []
        check_true("G6 an empty window is reported, not silently 0",
                   any("matched 0 rows" in n for n in notes) and not (res.get("rows") or []), str(notes))
    except guard.Refusal as exc:
        not_run("G6 empty window", f"the guard refused instead of narrowing: {exc}")


# ═══════════════════════════════════════════════════════════ T
def page_gates(profile, g, cur) -> None:
    """P — the overview page the workbench serves is THIS profile's page.

    Why this exists: `app_html` used to resolve through `prof_path`, which falls back to the app's
    directory when the profile has no file — so logistics (no page of its own) resolved to
    `retail_graph/ontology.html`, and the workbench served RETAIL'S GRAPH as logistics' overview. Nothing
    failed: the file existed, so regeneration was skipped. The same resolver let a missing `title` inherit
    "Retail ontology". Both are the "wrong ontology answered" failure, and both are countable here.
    """
    print("\nP — the overview page belongs to this profile")
    base = pathlib.Path(profile["_base"])
    rel = pathlib.Path(profile.get("app_html") or "ontology.html")
    page = rel if rel.is_absolute() else (base / rel)
    inside = str(page.resolve()).startswith(str(base.resolve()) + "/") or page.resolve().parent == base.resolve()
    check_true("P1 the page path is inside the profile (no fallback to the app's page)", inside, str(page))
    if not page.exists():
        check_true("P2 the profile has its own generated page", False,
                   f"{page} is missing — one request to the workbench regenerates it "
                   f"(serve_ui.graph_view via POST /api/settings, or restart the workbench); without it the "
                   f"workbench serves whatever this path falls back to")
        return
    html = page.read_text(encoding="utf-8", errors="ignore")
    title = (re.search(r"<title>(.*?)</title>", html, re.S) or [None, ""])[1].strip()
    want = (profile.get("title") or "").strip()
    check_true("P2 the page's title is this profile's title", bool(want) and want in title,
               f"page title {title!r} vs profile {want!r}")
    classes = sorted({str(c).split("#")[-1] for c in g.subjects(RDF.type, OWL.Class)
                      if str(c).startswith(sqlgen.NS)})
    hit = [c for c in classes if c in html]
    check_true("P3 the page documents this graph's classes (not another ontology's)", bool(hit),
               f"{len(hit)}/{len(classes)} declared classes appear in the page — a page generated for a "
               f"different ontology mentions none of them")
    if hit:
        print(f"       {len(hit)}/{len(classes)} declared classes on the page: "
              f"{', '.join(hit[:8])}{' …' if len(hit) > 8 else ''}")


def tutorial_gates(profile, g, cur) -> None:
    print("\nT — tutorial")
    path = profile["_base"] / "tutorial.json"
    if not path.exists():
        not_run("T1 tutorial.json", "this profile ships no authored tutorial (the workbench derives one)")
        return
    doc = json.loads(path.read_text(encoding="utf-8"))
    steps = doc.get("steps") or []
    check_true("T1 the tutorial has steps", len(steps) >= 5, f"{len(steps)} steps")
    metrics = sqlgen.metrics(g)
    classes = {str(s).split("#")[-1] for s in g.subjects(RDF.type, OWL.Class)
               if str(s).startswith(sqlgen.NS)}
    unknown = []
    for st in steps:
        for item in st.get("items") or []:
            if item not in classes and item not in metrics:
                unknown.append(f"{st.get('kind')}:{item}")
    check_true("T2 every tutorial item is declared", not unknown, str(unknown[:6]))
    kinds = {st.get("kind") for st in steps}
    check_true("T3 the tutorial teaches a refusal", "refusals" in kinds, str(kinds))
    metric_steps = [i for st in steps if st.get("kind") == "metrics" for i in (st.get("items") or [])]
    runs = []
    for name in metric_steps[:3]:
        msg = refused(sqlgen.compile_metric, g, name)
        if msg:
            runs.append(f"{name}: refused")
            continue
        sql = sqlgen.compile_metric(g, name).sql
        try:
            res = guard.run(cur, sql, cfg=profile.get("guard") or None, mode="declared")
            runs.append(f"{name}={res['rows'][0][0] if res.get('rows') else None}")
        except Exception as exc:                               # noqa: BLE001
            runs.append(f"{name}: {type(exc).__name__}")
    check_true("T4 the tutorial's metric steps run", bool(runs) and all("refused" not in r for r in runs),
               str(runs))

    # T5: every step must PROVE its point with live data, not assert it. Measured regression: a publish
    # rewrote two step bodies into assertions (605 -> 246 chars, losing the compiler's own refusal
    # sentences and the guard's own limits) and added a step with `items: []` — whose pane renders empty,
    # so the page showed a heading and nothing to click. A step is either a list of declared things (its
    # pane fetches their SQL/predicate), or the guard step (whose pane IS the profile's table).
    empty_steps = []
    for st in steps:
        kind = st.get("kind")
        if kind == "guard":
            # a guard step's pane IS a table: the step's own `guard` when it carries one, otherwise the
            # profile's (the page falls back to the payload's guard). What it may not be is empty — and
            # "empty" here means the PROFILE declares no guardrails at all.
            if not (st.get("guard") or profile.get("guard")):
                empty_steps.append(f"guard step {st.get('title')!r} has no guardrails to show")
            continue
        if not (st.get("items") or []):
            empty_steps.append(f"{kind} step {st.get('title')!r} has no items — its pane renders empty")
    check_true("T5 every step proves its point with live data", not empty_steps, str(empty_steps[:4]))
    if runs:
        print(f"         {' · '.join(runs)}")


def nl_gates(profile, g, cur) -> None:
    """N1 a declaration's OWN label is final: the question that quotes it must reach it.

    Measured on a logistics copy: 「每千公里破损箱数是多少」 was refused even though
    `:damagePer1kKm` carries exactly that label — the alias token 破损→damaged had no counterpart
    in the metric's own words {damage, per1k, km}, so the salient-noun check vetoed a literal
    label. A label is the phrase the ontology's author says people type; nothing may override it.

    N2 a SUPERLATIVE asks for a ranking, i.e. a number. Answered by a class it becomes "here is the
    list of damaged stops", which is not an answer. Either a metric takes it or it is refused by
    name — never a class listing.
    """
    import os

    import nl

    # nl.menu() reads the profile's `features` from APP_SETTINGS (a read-only profile has no
    # actions to compile). Without it the menu tried to compile the RETAIL action declarations
    # against this ontology and died with "PromoteCustomer: :Customer has no :physicalTable" —
    # a gate crashing instead of measuring.
    # Point nl at THE PROFILE BEING CHECKED. Later code used to take `sorted(base.glob("*_settings.json"))[0]`
    # — which, for retail (base = retail_graph/), is abc_settings.json: nl then compiled ABC's action
    # declarations against the retail graph and the gate CRASHED with "AssignTrip: :Trip has no
    # :physicalTable" instead of measuring anything. A profile under test is a known file; use it.
    if profile.get("_path"):
        os.environ["APP_SETTINGS"] = str(profile["_path"])
    elif profile.get("_base") is not None:
        base = pathlib.Path(profile["_base"])
        settings = sorted(base.glob("*_settings.json")) or sorted(base.glob("settings.json"))
        if settings:
            os.environ["APP_SETTINGS"] = str(settings[0])
    menu = nl.menu(g)
    for entry in menu["metrics"]:
        label = (entry.get("label") or "").strip()
        if len(label) < 2 or not any("\u4e00" <= ch <= "\u9fff" for ch in label):
            continue                      # CJK labels only: the ASCII path already had its gate
        question = f"{label}是多少"
        try:
            got = nl._rule_intent(question, menu)
        except nl.NlRefusal:
            got = None
        name = (got or {}).get("name")
        check(f"N1 {label!r} reaches its own declaration ({entry['name']})", name, entry["name"])

    # Three outcomes are all honest: a metric answer, a refusal that NAMES the class, or "unsure"
    # (None — the model gets asked; without one the caller refuses by listing the menu). Only a
    # CLASS listing for a superlative is wrong, so that is the single thing this fails on.
    for question in ("哪台车最多", "哪个门店最少", "哪条线路最高", "破损最多的门店"):
        try:
            got = nl._rule_intent(question, menu)
            kind = (got or {}).get("kind")
            check(f"N2 {question!r} is not answered with a class", kind in (None, "metric"), True)
        except nl.NlRefusal as exc:
            check(f"N2 {question!r} refused by name", "CLASS :" in str(exc) or "no metric" in str(exc), True)


def samples_gates(profile, g, cur) -> None:
    """A sample a user clicks must ANSWER, or refuse BY NAME.

    The profile's `samples` are the ontology's front door; a rotted sample is worse than none. The check
    lives in `check_samples.py` next to its `samples.json` (the numbers there come from a second route),
    so this gate runs it as a subprocess and reports its verdict — including NOT RUN when the ontology has
    no `samples.json` yet, because "no gate" must never look like "passed".
    """
    import subprocess

    base = pathlib.Path(profile.get("_base") or ".")
    spec = base / "samples.json"
    if not spec.is_file():
        NOT_RUN.append("samples: no samples.json next to the profile — the offered questions are "
                       "not gated yet (write the questions' expected values from a second route)")
        return
    script = pathlib.Path(__file__).with_name("check_samples.py")
    proc = subprocess.run([sys.executable, str(script), "--profile",
                           profile.get("_path") or str(base)], capture_output=True, text=True)
    for line in (proc.stdout or "").strip().splitlines():
        if line.strip().startswith("[FAIL]") or line.strip().startswith("[WARN]"):
            print("  " + line.strip())
    if proc.returncode == 0:
        count = sum(1 for line in (proc.stdout or "").splitlines() if line.strip().startswith("[PASS]"))
        check(f"S samples.json: {count} assertion(s) hold", True, True)
    elif proc.returncode == 2:
        NOT_RUN.append("samples: samples.json declares nothing to check")
    else:
        tail = (proc.stdout or "").strip().splitlines()[-1:] or ["see check_samples.py"]
        check("S samples.json: every sample answers or refuses by name", tail[0][:120], "ALL SAMPLES PASS")


def window_gates(profile, g, cur) -> None:
    """W1/W2: a declared TimeWindow must be PUSHABLE, and pushing it must change the query.

    Two failures this catches, both measured:

    * a metric declares `:supportsSlot :TimeWindow` but its grain declares no `:timeColumn` — the
      window then has nowhere to go. (The first version of the slot mechanism hard-coded `placed_at`,
      the retail column, so declaring the slot in logistics produced `column "placed_at" does not
      exist` for every metric.)
    * the window silently does not reach the SQL, so "last 90 days" answers the all-time total — the
      failure the whole slot mechanism exists to prevent.

    The comparison is `windowed <= unwindowed`, not an equality against a constant: a now()-relative
    number changes as the demo data ages, so a constant would rot (see check_metrics' history).
    """
    import nl
    import sqlgen

    menu = nl.menu(g)
    windowed = []
    for entry in menu["metrics"]:
        if "TimeWindow" not in (entry.get("label") or "") and not entry.get("refusal"):
            pass
    # which metrics DECLARE the slot (by the graph, not by the menu's shape)
    declared = []
    for name in sorted(sqlgen.metrics(g)):
        slots = [sqlgen._local(o) for o in g.objects(sqlgen.P(name), sqlgen.P("supportsSlot"))
                 if sqlgen._local(o)]
        if "TimeWindow" in slots:
            declared.append(name)
    if not declared:
        NOT_RUN.append("window gate: no metric declares :supportsSlot :TimeWindow in this profile")
        return

    for name in declared:
        grain = sqlgen._local(sqlgen._one(g, sqlgen.P(name), sqlgen.P("grain")))
        col, how = sqlgen.time_column(g, grain)
        check(f"W1 :{name} declares a window AND its grain owns a time column", bool(col), True)
        if not col:
            print(f"        ({how})")

    # W2 on the gate's OWN connection: nl.ask() connects through actions.DSN, which is bound at import
    # time to whatever profile the process started with — asking through it made this gate run `trips`
    # against retail_db ("relation trips does not exist"). Compile here, run on `cur`.
    sample_name = declared[0]
    plain = sqlgen.compile_metric(g, sample_name)
    cur.execute(plain.sql)
    plain_value = cur.fetchone()[0]
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc)
    since = (now - _dt.timedelta(days=90)).isoformat()
    windowed = sqlgen.compile_metric(g, sample_name, since=since)
    grain = sqlgen._local(sqlgen._one(g, sqlgen.P(sample_name), sqlgen.P("grain")))
    col, _how = sqlgen.time_column(g, grain)
    check(f"W2 the window reached the SQL ({sample_name}): {col} in the WHERE",
          bool(col) and f"{col} >= %(since)s" in windowed.sql, True)
    cur.execute(windowed.sql, {"since": since})
    windowed_value = cur.fetchone()[0]
    # A SUBSET RULE ONLY HOLDS FOR ADDITIVE NUMBERS. `windowed <= all-time` is true for a count or a
    # sum; it is false for an average, which a window may legitimately raise (measured on retail:
    # averageOrderValue 242.38 all-time, 283.17 in the last 90 days — the gate reported a correct
    # answer as a failure). For a non-additive metric the honest check is the one that still bites:
    # the window REACHED the SQL (asserted above) and the number CHANGED — a window that does not
    # move an average is a window that was dropped.
    additive = (sqlgen.metrics(g).get(sample_name).aggregate or "") in ("count", "sum") \
        or bool(sqlgen.metrics(g).get(sample_name).formula) and \
        (sqlgen.metrics(g).get(sample_name).aggregate or "") in ("count", "sum")
    if additive:
        ok = (windowed_value is not None and plain_value is not None
              and float(windowed_value) <= float(plain_value))
        check(f"W2 the windowed number is a subset of the all-time one "
              f"({windowed_value} <= {plain_value}, {sample_name})", ok, True)
    else:
        changed = (windowed_value is not None and plain_value is not None
                   and float(windowed_value) != float(plain_value))
        check(f"W2 the window moved a non-additive number (it reached the rows) "
              f"({plain_value} -> {windowed_value}, {sample_name}; an average is not monotone, so "
              f"the subset rule does not apply)", changed, True)


def _load_deployment_env() -> None:
    """Give a CLI gate the environment the SERVICE has (the same rule `scripts/ontology_gates.py` uses).

    Measured on the ECS deploy: retail's profile defaults its dsn to port 15432 (the local Docker port),
    and the service's `/root/langconfig/.env` sets ONTOLOGY_DB_PORT=5432 — so `--family X` here died with
    "port 15432 refused" while the served ontology answered. A gate that measures a different environment
    than the app is measuring the wrong machine.
    """
    # this file is features/ontology/gates/check_ontology_generic.py: parents[3] = backend, parents[4] = repo
    here = pathlib.Path(__file__).resolve()
    env = next((p / ".env" for p in (here.parents[4], here.parents[3]) if (p / ".env").is_file()), None)
    if env is None:
        return
    try:
        for raw in env.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key and key not in os.environ:
                os.environ[key] = value.strip().strip('"').strip("'")
    except Exception:                                            # noqa: BLE001
        pass


def portability_gates(profile, g, cur) -> None:
    """X1/X1b: a declaration may not name a machine path.

    The failure this exists for, measured on the ECS deployment: the Query page worked on the laptop
    it was written on and refused on the server with

        nl.py failed: [Errno 2] No such file or directory:
        '/Users/weiping/dev/Learn/ontology/.venv/bin/python'

    A declaration (or a runtime command it drives) that says WHERE THIS MACHINE keeps its files is
    not a declaration: the same profile has to compile and answer on the machine that serves it. The
    scan reads the files that travel with a profile — settings, TTL, dashboard/samples/tutorial/truth
    and the declared actions — and names every absolute machine path it finds. X1b proves the scanner
    can fail: a synthetic settings file that names `/Users/someone/...` must be caught, so a green X1
    means "the scan ran and found nothing", not "the scan looked at nothing".

    Paths that are DERIVED from the install root are not hits (`schema/actions.yml`, `ontology/`, the
    `${ONTOLOGY_DB_HOST:-...}` form in a dsn); so is an origin-relative URL (`/api/...`), which is the
    page's own address, not a file.
    """
    root = pathlib.Path(profile["_path"]).parent

    def scan(base: pathlib.Path) -> list[str]:
        hits: list[str] = []
        for pattern in ("*_settings.json", "dashboard.json", "samples.json", "tutorial.json",
                        "truth.json", "*.ttl", "ontology/*.ttl", "schema/*.yml", "schema/*.yaml"):
            for path in sorted(base.glob(pattern)):
                if not path.is_file():
                    continue
                try:
                    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
                except OSError:                                  # noqa: BLE001
                    continue
                for n, line in enumerate(lines, 1):
                    for hit in MACHINE_PATH.finditer(line):
                        where = path.relative_to(base) if base in path.parents else path.name
                        hits.append(f"{where}:{n} names {hit.group(0)!r}")
        return hits

    hits = scan(root)
    check_true("X1 no declaration names a machine path (a profile has to answer where it is installed)",
               not hits, "; ".join(hits[:6]) + (" …" if len(hits) > 6 else ""))
    with tempfile.TemporaryDirectory() as tmp:
        probe = pathlib.Path(tmp, "probe_settings.json")
        probe.write_text('{"actions_file": "/Users/someone/repo/schema/actions.yml"}',
                         encoding="utf-8")
        caught = scan(pathlib.Path(tmp))
    check_true("X1b the scanner fails on a machine path (synthetic: /Users/someone/…)",
               bool(caught), "the scanner found nothing in a file that names /Users/someone/... — "
               "then a green X1 would be decoration")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument("--truth", default="", help="optional {metric: number} written by a second route")
    # A build is green step by step, not in one leap: each family is one step's gate, so a step can be
    # declared done (or not) by running exactly its own family.
    ap.add_argument("--family", action="append", default=None,
                    help="only these gate families (C structure · R reasoning · G guard · P page · "
                         "T tutorial · N nl · S samples · W window · X portability); repeatable. "
                         "Default: every family")
    args = ap.parse_args()
    _load_deployment_env()          # before load(): the dsn is resolved against it
    path = pathlib.Path(args.profile).expanduser().resolve()
    if not path.exists():
        print(f"no profile at {path}")
        return 2
    profile, g, dsn = load(path)
    # `--truth` used to be parsed and then thrown away: `reasoning_gates(..., None)` was hard-coded,
    # so R2 ("definition == hand SQL") was NOT RUN on EVERY profile, forever. Measured on a v6 build:
    # the builder wrote a truth.json with a hand-written predicate per definition, then found the
    # runner never passed it. A declaration that is never executed is not evidence — resolve it here,
    # from the flag, else the profile's own truth.json, else leave it None (R2 then says NOT RUN).
    truth_path = pathlib.Path(args.truth).expanduser() if args.truth else (path.parent / "truth.json")
    truth = None
    if truth_path.is_file():
        try:
            truth = json.loads(truth_path.read_text(encoding="utf-8"))
            print(f"truth:   {truth_path}")
        except Exception as exc:                                 # noqa: BLE001
            print(f"truth:   {truth_path} is not readable JSON ({exc}) — R2 stays NOT RUN")
    elif args.truth:
        print(f"truth:   {truth_path} does not exist — R2 stays NOT RUN")
    print(f"profile: {path}")
    print(f"ns:      {sqlgen.NS}")
    print(f"dsn:     {dsn}")
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    cur = conn.cursor()
    try:
        wanted = {f.upper() for f in (args.family or ["C", "R", "G", "P", "T", "N", "S", "W", "X"])}
        unknown = wanted - {"C", "R", "G", "P", "T", "N", "S", "W", "X"}
        if unknown:
            print(f"unknown gate family/families: {sorted(unknown)}")
            return 2
        if "C" in wanted:
            structure_gates(profile, g, cur)
        if "R" in wanted:
            reasoning_gates(profile, g, cur, truth)
        if "G" in wanted:
            guard_gates(profile, g, cur)
        if "P" in wanted:
            page_gates(profile, g, cur)
        if "T" in wanted:
            tutorial_gates(profile, g, cur)
        if "N" in wanted:
            nl_gates(profile, g, cur)
        if "S" in wanted:
            samples_gates(profile, g, cur)
        if "W" in wanted:
            window_gates(profile, g, cur)
        if "X" in wanted:
            portability_gates(profile, g, cur)
    finally:
        conn.close()
    print()
    if NOT_RUN:
        print("NOT RUN (an unrun gate is not a passed gate):")
        for item in NOT_RUN:
            print(f"  · {item}")
    print("ALL GATES PASS" if OK and not NOT_RUN else ("GATES PASS (with NOT RUN items)" if OK else "SOME GATES FAILED"))
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())

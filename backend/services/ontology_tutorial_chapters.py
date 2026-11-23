"""The eight authored tutorial chapters and ABC's training pages, served by the app.

`ontology_pages.py` removed the workbench as the source of the app's three JSON documents and of the
generated graph page. What was left on those five ports was the teaching material: retail's eight
hand-written chapters (`tutorial1.html` … `tutorial8.html`) and ABC's eight training steps, each chapter
an HTML page plus the small JSON endpoints its JavaScript calls while the reader clicks.

Those endpoints are the SAME functions the workbench calls, in the SAME file (`workbench/serve_ui.py`).
Rewriting them here would have meant two copies of the reasoning that made chapter 5's gate and chapter
6's compile explain themselves — so this module imports `serve_ui` and calls its functions, with the
profile pointed at this ontology first. One implementation, one origin, no second server.

Two rewrites make the pages work on this origin, both tested by the gate (`W4`-style path check):

  /api/…            → /api/ontology/{key}/wb/…      (chapter JavaScript's own absolute paths)
  /abctutorial/…    → /api/ontology/{key}/abct/…     (ABC's step iframes)

The chapters are RETAIL'S (and ABC's), not every ontology's: a profile without them gets a 404 whose
message names that fact, because a chapter that silently shows another ontology's numbers is worse than
no chapter.
"""
from __future__ import annotations

import json
import logging
import pathlib
import sys
from urllib.parse import parse_qs

from services import ontology_pages, ontology_runtime

logger = logging.getLogger(__name__)

FEATURE = ontology_pages.FEATURE
WORKBENCH = ontology_pages.WORKBENCH

#: chapter number → the page that carries it
CHAPTER_PAGES = {n: f"tutorial{n}.html" for n in range(1, 9)}
#: where ABC's training shell + steps lived; now read from each profile's own dir (`_abct_dir`)
ABCT_DIR = FEATURE / "profiles" / "abc" / "tutorial"


#: endpoints the app's own Query / Actions pages call — available for EVERY ontology
PAGE_ENDPOINTS = {
    "/nl", "/nl/config", "/nl/backlog", "/ask", "/samples", "/lanes",
    "/actions", "/actions/audit", "/actions/run", "/guard",
}


class ChapterError(Exception):
    """This ontology has no such chapter."""


def _serve_ui():
    """The workbench module, imported once. It is a script with a `__main__` guard, so this is free."""
    for path in (str(WORKBENCH), str(FEATURE / "compiler")):
        if path not in sys.path:
            sys.path.insert(0, path)
    import serve_ui  # noqa: PLC0415

    return serve_ui


def _menu(key: str) -> dict:
    """`{samples, declared_count}` — the whole menu plus how many of it the profile wrote by hand.

    The dashboard chat wants both kinds (a few authored examples first, then a few that exist purely
    because a metric was declared); the Query page shows the whole list.
    """
    import serve_ui  # noqa: PLC0415
    declared = [s for s in (serve_ui.load_settings().get("samples") or [])
                if isinstance(s, str) and s.strip()]
    return {"samples": _menu_samples(key), "declared_count": len(declared)}


def _menu_samples(key: str) -> list[str]:
    """The questions this ontology offers — DECLARED samples first, then one per metric.

    A metric that is declared but never offered is a metric nobody asks for: `:askedAs` is mandatory
    (C5a), so the question already exists in the declaration — there is no reason for a hand-kept list
    to be the only way a user can discover it. This used to return `settings.samples` alone, which
    meant adding a metric did NOT add a question anywhere: the Query page and the dashboard chat both
    offered the same stale list until someone remembered to edit it (measured: 46 metrics declared,
    28 questions offered, and the dashboard's own hardcoded four included one the ontology refused).

    Order matters: the profile's own samples are the ones with a gate behind them, so they come first.
    """
    import serve_ui  # noqa: PLC0415
    declared = [s for s in (ui_load_samples() or []) if isinstance(s, str) and s.strip()]
    seen = set(declared)
    extra: list[str] = []
    try:
        import sqlgen  # noqa: PLC0415
        graph = sqlgen.load()
        for name in sorted(sqlgen.metrics(graph)):
            asked = sqlgen._one(graph, sqlgen.P(name), sqlgen.P("askedAs"))
            asked = str(asked).strip() if asked else ""
            if asked and asked not in seen:
                seen.add(asked)
                extra.append(asked)
    except Exception:                                          # noqa: BLE001 — the menu still works
        extra = []
    return declared + extra


def ui_load_samples() -> list:
    """The profile's declared sample questions (whatever the workbench loaded last)."""
    import serve_ui  # noqa: PLC0415
    return serve_ui.load_settings().get("samples") or []


def _activate(key: str):
    """Point every compiler module AND the workbench's own settings at this ontology.

    The workbench process did this once, in `main()`, because it served one ontology. In-process it has
    to happen per call — and under the runtime's lock, for the same reason compile() needs it: these
    modules keep their profile in module globals (`sqlgen.NS`, `guard.SETTINGS`, `actions.SCHEMA`).
    """
    profile = ontology_pages._profile(key)
    with ontology_runtime._LOCK:
        ontology_pages._compiler().use(profile)
        ui = _serve_ui()
        ui.SETTINGS = profile
        try:
            import i18n  # noqa: PLC0415

            i18n.SETTINGS = profile
        except ModuleNotFoundError:  # pragma: no cover — the app always ships the compiler
            pass
        ui.apply_profile(ui.load_settings())
    return ui, profile


# ── the pages ───────────────────────────────────────────────────────────────
def _rewrite(html: str, key: str) -> str:
    """Make a page's absolute paths belong to THIS ontology on the app's own origin.

    The rewrite must be IDEMPOTENT. It used to replace every `"/api/` with
    `"/api/ontology/{key}/wb/"` — so a page that already addressed this ontology's own endpoint
    (`/api/ontology/talent_steps/wb/stepquery`) came back as
    `/api/ontology/talent_steps/wb/ontology/talent_steps/wb/stepquery`, which 404s. The reader
    saw "no rows" and an `undefined` filename, because the fetch had failed silently.
    """
    own = f"/api/ontology/{key}/"
    # 1) a path that already points at THIS ontology is left alone
    # 2) a path that points at ANOTHER ontology is left alone too — rewriting it would silently
    #    answer a question from the wrong ontology, which is worse than a 404
    # 3) the bare `/api/...` workbench paths are rewritten to this ontology's own
    import re

    def fix(match: "re.Match[str]") -> str:
        quote, path = match.group(1), match.group(2)
        if "/api/ontology/" in path:
            return match.group(0)          # already an ontology-scoped path — leave it
        return f"{quote}/api/ontology/{key}/wb/{path}"

    html = re.sub(r'(["\'])/api/(?!ontology/)([^"\']*)', fix, html)
    html = html.replace('"/abctutorial/', f'"/api/ontology/{key}/abct/')
    html = html.replace("'/abctutorial/", f"'/api/ontology/{key}/abct/")
    # …and say it in the language the profile declares, when it declares a translation.
    return ontology_pages.translate_page(key, html)


def _step_graph(key: str, step: int) -> dict:
    """One step's picture — the profile's own `tutorial/graph.json` first, retail's table as fallback.

    Retail's eight pictures are hand-placed coordinates in `serve_ui.TUTORIAL_GRAPHS`, which is fine for
    one ontology and wrong for the second: a cold-chain chapter about trip-vs-stop grain has nothing to
    do with retail's Product. A profile that ships authored chapters ships its pictures as DATA:
    `{"steps": {"1": {"nodes": [...], "edges": [...]}}}` — same shape the page already draws.
    """
    try:
        path = ontology_pages._profile(key).parent / "tutorial" / "graph.json"
        if path.is_file():
            doc = json.loads(path.read_text(encoding="utf-8"))
            g = ((doc.get("steps") or {}).get(str(step))
                 or (doc.get("steps") or {}).get(step))
            if g:
                return {"ok": True, "step": step, "nodes": g.get("nodes") or [],
                        "edges": g.get("edges") or [], "source": "profile"}
    except (OSError, ValueError, ontology_pages.PageError):
        pass
    ui, _ = _activate(key)
    return ui.tutorial_graph(step)


def _step_arg(raw) -> int | str:
    """A step number, or the words that mean "the complete ontology".

    `arg(..., int)` cannot be used here: casting "all" to int raises ValueError, and `arg` swallows
    it into the DEFAULT (1) — so "the whole ontology" silently answered as step 1 and looked broken.
    """
    text = str(raw).strip().lower()
    if text in ("all", "0", "final", "full"):
        return text
    try:
        return int(text)
    except (TypeError, ValueError):
        return 1


def _step_query(key: str, step: int, query: str, limit: int = 25) -> dict:
    """Run a SPARQL query against ONE STEP's ontology file — the file that step teaches.

    Why this exists: the platform's own `/sparql` answers against the profile's `abox.ttl`, which
    holds the FINAL ontology (step 7). A step-by-step tutorial needs the opposite: the query must
    be answered by the ontology as it stands at that step, so a reader who asks "who has Python?"
    at step 4 gets the honest empty answer — and can see that the answer appears at step 6.

    The file is read as-is; nothing is entailed and nothing is written back. That is the point:
    "not yet answerable" must be shown, not asserted.
    """
    import pathlib as _pathlib

    try:
        base = ontology_pages._profile(key).parent
    except ontology_pages.PageError as exc:
        raise ChapterError(str(exc)) from exc
    settings_path = next(iter(sorted(base.glob("*_settings.json"))), None) or base / "settings.json"
    settings = {}
    if settings_path.is_file():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except ValueError:
            settings = {}
    ns = (settings.get("ns") or "").rstrip("#") + "#"
    if not ns or ns == "#":
        ns = "http://example.org/talent#"

    ont_dir = base / (settings.get("ontology_dir") or "ontology")
    # step=0 (or "all") means THE COMPLETE ONTOLOGY — the last step's file. The tutorial offers both:
    # "this step" shows where the ontology is NOW, "all steps" shows what the finished ontology can
    # answer. A reader must be able to ask a real question and get a real answer, not be told which
    # question they are allowed to ask.
    if str(step).lower() in ("all", "0", "final", "full"):
        step = max([int(p.stem.replace("step", "")) for p in ont_dir.glob("step*.ttl")] or [0])
    path = ont_dir / f"step{step:02d}.ttl"
    if not path.is_file():
        raise ChapterError(f"this ontology has no step {step} file ({path.name} is not installed)")

    from rdflib import Graph

    text = (query or "").replace("PREFIX : ", f"PREFIX : <{ns}> ")
    if "PREFIX" not in text.upper():
        text = f"PREFIX : <{ns}>\n" + text

    graph = Graph()
    graph.bind("", ns)
    graph.parse(str(path), format="turtle")
    try:
        result = graph.query(text)
    except Exception as exc:                                    # noqa: BLE001
        return {"ok": True, "step": step, "rows": [[f"QUERY ERROR: {type(exc).__name__}: {exc}"]],
                "columns": [], "file": path.name, "triples": len(graph)}
    # ASK returns a BOOLEAN, not rows. Handled FIRST: iterating an ASK result yields the boolean
    # itself as a "row", so the row loop consumed it and the answer came back as a bare row —
    # and a FALSE answer came back as no rows at all, so the reader could not tell "false" from
    # "nothing to say".
    answer = None
    if str(getattr(result, "type", "") or "").upper() == "ASK":
        answer = bool(result.askAnswer)
        return {"ok": True, "step": step, "rows": [["true" if answer else "false"]],
                "columns": ["?"], "file": path.name, "triples": len(graph), "answer": answer}

    columns = [str(v) for v in (result.vars or [])]
    rows = []
    for row in result:
        rows.append([str(v).rsplit("#", 1)[-1] for v in row])
        if len(rows) >= limit:
            break
    return {"ok": True, "step": step, "rows": rows, "columns": columns,
            "file": path.name, "triples": len(graph), "answer": None}


def _step_reason(key: str, step: int, class_name: str, limit: int = 25) -> dict:
    """Run the REASONER over ONE STEP's file — the file that step teaches.

    Why this exists: the platform's own `/reason` endpoint always reasons over the profile's
    COMPLETE ontology (`abox.ttl` + `reasoning.ttl`, which is step 7). A step-by-step tutorial
    needs the opposite: at step 6 there is no axiom yet, so the reasoner has nothing to conclude
    from — and saying so is the honest answer, not "cand_A" from a later step's rule.

    The step's own file is loaded and reasoned over as it stands. Nothing is written back.
    """
    from features.ontology.reasoning.reasoner import load_graph, reason, mutate

    try:
        base = ontology_pages._profile(key).parent
    except ontology_pages.PageError as exc:
        raise ChapterError(str(exc)) from exc
    settings_path = next(iter(sorted(base.glob("*_settings.json"))), None) or base / "settings.json"
    settings = {}
    if settings_path.is_file():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except ValueError:
            settings = {}
    ns = (settings.get("ns") or "").rstrip("#") + "#"
    if not ns or ns == "#":
        ns = "http://example.org/talent#"

    ont_dir = base / (settings.get("ontology_dir") or "ontology")
    if str(step).lower() in ("all", "0", "final", "full"):
        step = max([int(p.stem.replace("step", "")) for p in ont_dir.glob("step*.ttl")] or [0])
    path = ont_dir / f"step{step:02d}.ttl"
    if not path.is_file():
        raise ChapterError(f"this ontology has no step {step} file ({path.name} is not installed)")

    iri = ns + (class_name or "")
    graph = load_graph([path])
    res = reason(graph, watch_classes=[iri])
    members = res.members_of(iri)

    # the falsification check, on this step's file: without the axiom the answer must vanish
    pruned, removed = mutate(graph, subject=(class_name or ""), predicate="equivalentClass",
                             namespace=ns)
    after = reason(pruned, watch_classes=[iri]).members_of(iri)

    from rdflib import RDF, URIRef
    asserted = len(list(graph.subjects(RDF.type, URIRef(iri))))

    return {
        "ok": True, "step": step, "file": path.name,
        "class": class_name,
        "asserted": asserted,
        "entailed": len(members),
        "added": len(members),
        "rows": [m.rsplit("#", 1)[-1] for m in members[:limit]],
        "engine": res.engine,
        "elapsed_ms": res.elapsed_ms,
        "consistent": res.consistent,
        "has_axiom": removed > 0,
        "without_axiom": [m.rsplit("#", 1)[-1] for m in after],
    }


def _guard_config(key: str) -> dict:
    """The profile's guardrails, read-only: the numbers the chapter prints plus why each is there."""
    settings = ontology_pages._settings(key) or {}
    g = dict(settings.get("guard") or {})
    big = g.get("big_tables") or {}
    return {
        "ok": True,
        "guard": g,
        "big_tables": [{"table": t, "time_column": c} for t, c in big.items()],
        "limits": {
            "max_rows": g.get("max_rows"),
            "statement_timeout_ms": g.get("statement_timeout_ms"),
            "max_plan_rows": g.get("max_plan_rows"),
            "default_window_days": g.get("default_window_days"),
        },
        "note": g.get("_big_tables_note"),
    }


def chapter(key: str, number: int) -> str:
    """One authored chapter's HTML, rewritten for this origin."""
    name = CHAPTER_PAGES.get(number)
    if name is None:
        raise ChapterError(f"no tutorial chapter {number} (known: {sorted(CHAPTER_PAGES)})")
    if not chapters_available(key):
        # the eight chapters are RETAIL's, written about retail's concepts and numbers. Serving them
        # for clinic would print retail's tiers under clinic's title — the same class of failure as a
        # missing graph page resolving to another ontology's. This profile gets the generated tutorial.
        raise ChapterError(f"{key} has no authored tutorial chapters (tutorial_style is not 'authored')")
    _activate(key)
    # The profile's own chapters first (`profiles/<key>/tutorial/stepN.html`), then retail's shared ones.
    own = ontology_pages._profile(key).parent / "tutorial" / f"step{number}.html"
    asset = own if own.is_file() else WORKBENCH / name
    if not asset.is_file():
        raise ChapterError(f"this ontology has no tutorial chapter {number} ({asset.name} is not installed)")
    html = _rewrite(asset.read_text(encoding="utf-8"), key)
    # 声明过的翻译在这里生效:页面是手写 HTML,不可能按语言重新 author,
    # 所以翻译放在 profiles/<key>/tutorial/i18n.json,由**全局语言设置**选一份。
    # 只替换声明过的串,没声明的保持原样 —— 半翻译是诚实的,静默空白不是。
    try:
        html = ontology_pages.translate_page(key, html)
    except Exception:                                            # noqa: BLE001
        pass
    # 正文没翻译时,把"这一页是哪种语言"写在页顶 —— 静默地给一半语言,读者会以为是坏了
    try:
        notice = ontology_pages.language_notice(key)
        if notice and "<main>" in html:
            html = html.replace("<main>", "<main>" + notice, 1)
    except Exception:                                            # noqa: BLE001
        pass
    return html


def _abct_dir(key: str) -> pathlib.Path:
    """The training pages belong to the PROFILE that ships them (ABC), never to the workbench."""
    try:
        return ontology_pages._profile(key).parent / "tutorial"
    except ontology_pages.PageError as exc:
        raise ChapterError(str(exc)) from exc


def has_training(key: str) -> bool:
    try:
        return (_abct_dir(key) / "shell.html").is_file()
    except ChapterError:
        return False


def abct(key: str, number: int | None = None, embed: bool = False) -> str:
    """ABC's training shell (number None) or one of its eight steps."""
    if not has_training(key):
        raise ChapterError(f"{key} has no training pages (no tutorial/shell.html in its profile)")
    _activate(key)
    asset = _abct_dir(key) / ("shell.html" if number is None else f"step{number}.html")
    if not asset.is_file():
        raise ChapterError(f"{key} has no training page {number if number else 'shell'}")
    html = asset.read_text(encoding="utf-8")
    if embed and number is not None:
        html = html.replace("</head>", "<style>body{padding-left:0!important}</style></head>", 1)
    return _rewrite(html, key)


# ── the JSON the chapters call ──────────────────────────────────────────────
def call(key: str, rest: str, query: dict[str, list[str]], payload: dict | None = None) -> dict:
    """Dispatch one chapter endpoint by its workbench path (`tutorial1/table`, `abct/vehicles`, …)."""
    path = "/" + rest.strip("/")
    if path.startswith("/abct/"):
        # ABC's endpoints read ABC's tables; answering them for another profile would report
        # another ontology's numbers under this one's name.
        if not has_training(key):
            raise ChapterError(f"{key} has no training pages, so {path} is not its endpoint")
    elif not chapters_available(key) and path not in PAGE_ENDPOINTS:
        # the Query and Actions pages are every ontology's, not retail's: their endpoints are the
        # compiler's own (`nl.py`, `actions.py`), and they read whatever profile is active
        raise ChapterError(f"{key} serves no authored chapters (tutorial_style is not 'authored')")
    # A profile with its OWN chapters (profiles/<key>/tutorial/stepN.html) does not carry the workbench's
    # tutorial1..8 endpoints. Serving them anyway RAN RETAIL'S handlers against this ontology: measured on
    # talent_v1, `/wb/tutorial6/metrics` answered HTTP 500 (not 404) because the handler expects retail's
    # lane-B graph, so a page this ontology never had looked like a broken one.
    own_chapters = False
    try:
        own_chapters = (ontology_pages._profile(key).parent / "tutorial" / "step1.html").is_file()
    except ontology_pages.PageError:
        own_chapters = False
    if own_chapters and path.startswith("/tutorial"):
        raise ChapterError(
            f"{key} ships its own tutorial chapters; {path} is the workbench's page and this ontology "
            "has no such endpoint")

    ui, _ = _activate(key)
    method = "POST" if payload is not None else "GET"
    payload = payload or {}

    def arg(name: str, default=None, cast=None):
        # The caller passes `dict(request.query_params)`, and Starlette's QueryParams yields a
        # PLAIN STRING per key — not a list. The old `(query.get(name) or [None])[0]` therefore took
        # the FIRST CHARACTER of the value: every parameter that carried a query or a path came in
        # as one letter, and every SPARQL failed with "Expected {SelectQuery …}, found 'S'".
        # Accept both shapes; the list form is what the older callers pass.
        raw = query.get(name)
        if isinstance(raw, (list, tuple)):
            raw = raw[0] if raw else None
        if raw in (None, ""):
            return default
        try:
            return cast(raw) if cast else raw
        except (TypeError, ValueError):
            return default

    if method == "GET":
        table = {
            # The tutorial's own graph (`tutorial_graph.js`) asks for `/api/graph?step=N` and draws
            # whatever it gets back. That endpoint lived on the workbench server; when the pages moved
            # onto this app the route was never carried over, so the graph rendered as the literal text
            # "graph unavailable" while the eight authored step pictures sat unused in `TUTORIAL_GRAPHS`.
            "/graph": lambda: _step_graph(key, arg("step", 1, int)),
            # A step's own SPARQL: answered by that step's OWN file, so a question a reader asks
            # early gets the honest "not yet" answer — and "all" answers against the COMPLETE
            # ontology, so the reader can always ask a real question and get a real answer.
            "/stepquery": lambda: _step_query(
                key, arg("step", 1, _step_arg), arg("query", "", str), arg("limit", 25, int)),
            # THE REASONER over ONE STEP's file. The platform's own /reason always reads the
            # COMPLETE ontology, so a step-by-step tutorial would otherwise see step 7's answer
            # while the reader is at step 6 — where the axiom does not exist yet.
            "/stepreason": lambda: _step_reason(
                key, arg("step", 1, _step_arg), arg("class", "", str), arg("limit", 25, int)),
            # The guardrails AS DECLARED. Retail's chapter 4 has always asked for this and got a 404
            # ("no chapter endpoint /guard (GET)") because only the POST form — dry-run a write verb —
            # existed. A tutorial that teaches limits must be able to show the limits.
            "/guard": lambda: _guard_config(key),
            "/tutorial1/table": ui.tutorial1_table,
            "/tutorial2/table": ui.tutorial2_table,
            "/tutorial3/table": ui.tutorial3_table,
            "/tutorial4/table": ui.tutorial3_table,   # ch.4 writes to the same live table ch.3 reads
            "/tutorial3/objects": ui.tutorial3_objects,
            "/tutorial5/compile": lambda: ui.tutorial5_compile(arg("gate", None, float)),
            "/tutorial6/metrics": lambda: ui.tutorial6_metrics(arg("days", 30, int)),
            "/tutorial7/tables": ui.tutorial7_tables,
            "/tutorial7/metrics": ui.tutorial7_metrics,
            "/tutorial8/tables": ui.tutorial8_tables,
            "/tutorial8/metrics": ui.tutorial8_metrics,
            "/abct/vehicles": ui.abct_vehicles,
            "/abct/trips": ui.abct_trips,
            "/abct/stops": ui.abct_stops,
            "/abct/objects": ui.abct_objects,
            "/abct/metrics": ui.abct_metrics,
            "/abct/overload": ui.abct_overload,
            "/abct/overload/compile": lambda: ui.abct_overload_compile(arg("pct", 100.0, float)),
            "/abct/versions": ui.abct_versions,
            "/abct/audit": ui.abct_audit,
            # chapter 4 shows the declared verb and the audit trail: the app's own runtime answers
            # both, in the shapes the chapter renders (`applies_to`, `preconditions`, `effect`;
            # `id`, `action`, `actor`, `before_row`, `after_row`, `ts`)
            "/actions": lambda: _actions(key),
            "/actions/audit": lambda: _audit(key),
            # the Query page's own endpoints: the question box, its policy/backlog side panels
            "/nl/config": ui.nl_config,
            "/nl/backlog": ui.nl_backlog,
            "/samples": lambda: {"ok": True, **_menu(key)},
            "/lanes": lambda: ui.run_lane_b(ui.load_settings()),
        }
        fn = table.get(path)
        if fn is None:
            raise ChapterError(f"no chapter endpoint {path} (GET)")
        return fn()

    # POST — on the app, the write verbs are the runtime's (one audit table, one guard path)
    if path == "/tutorial1":
        return ui.run_tutorial1((payload.get("question") or "").strip())
    if path == "/tutorial2":
        return ui.run_tutorial2((payload.get("question") or "").strip())
    if path == "/tutorial3":
        return ui.run_tutorial3((payload.get("question") or "").strip())
    if path == "/tutorial6/ask":
        return ui.tutorial6_ask((payload.get("question") or "").strip(),
                                arg("days", 30, int))
    if path in ("/tutorial7/ask", "/tutorial8/ask"):
        return ui.tutorial6_ask((payload.get("question") or "").strip(), None)
    if path == "/tutorial6/compile":
        return ui.tutorial6_compile(
            (payload.get("metric") or "").strip(), (payload.get("formula") or "").strip(),
            (payload.get("aggregate") or "").strip(), (payload.get("where") or "").strip() or None,
        )
    if path == "/abct/query":
        return ui.abct_named_sql((payload.get("name") or "").strip())
    if path == "/abct/ask":
        return ui.abct_ask((payload.get("question") or "").strip())
    if path.startswith("/abct/action/"):
        return ui.abct_action(path.rsplit("/", 1)[1], (payload.get("name") or "").strip(),
                             payload.get("params") or {}, (payload.get("actor") or "tutorial").strip())
    if path == "/nl":
        question = (payload.get("question") or "").strip()
        if not question:
            return {"ok": False, "refused": "empty question"}
        code, data = ui.nl_cli(question, confirm=bool(payload.get("confirm")))
        if not isinstance(data, dict):
            return {"ok": False, "refused": f"nl.py gave no result (exit {code})"}
        return data
    if path == "/ask":
        question = (payload.get("question") or "").strip()
        if not question:
            return {"ok": False, "error": "empty query"}
        return ui.run_sparql(ui.load_settings(), question)
    if path == "/guard":
        return _guard(key, payload)
    if path == "/actions/run":
        return _run(key, payload)
    raise ChapterError(f"no chapter endpoint {path} (POST)")


def _actions(key: str) -> dict:
    """The verbs this ontology declares. No verbs is a fact about the ontology, not an error."""
    out = ontology_runtime.declared_actions(key)
    if not out.get("ok"):
        return {"ok": True, "actions": [], "note": out.get("error") or "no write verbs declared"}
    return {"ok": True, "actions": out.get("actions") or []}


def _audit(key: str, limit: int = 50) -> dict:
    out = ontology_runtime.audit(key, limit=limit)
    return {"ok": bool(out.get("ok")), "rows": out.get("events") or [],
            **({"error": out["error"]} if out.get("error") else {})}


def _guard(key: str, payload: dict) -> dict:
    """Dry-run a write verb. Chapter 4 renders `j.admitted`, `j.effect_bound` and `j.checks[].sql_bound`,
    which is exactly what the runtime's dry run returns — so this only lifts `result` to the top level."""
    name = (payload.get("name") or "").strip()
    if not name:
        return {"ok": False, "error": "name is required"}
    out = ontology_runtime.invoke(key, name, payload.get("params") or {}, dry_run=True,
                                  actor=(payload.get("actor") or "tutorial"))
    result = out.get("result") if isinstance(out.get("result"), dict) else {}
    merged = {**result}
    merged["ok"] = bool(result.get("ok", out.get("ok")))
    if out.get("error"):
        merged.setdefault("error", out["error"])
    return merged


def _run(key: str, payload: dict) -> dict:
    """Run a declared write for real (chapter 4's promote/demote buttons)."""
    name = (payload.get("name") or "").strip()
    if not name:
        return {"ok": False, "error": "name is required"}
    out = ontology_runtime.invoke(key, name, payload.get("params") or {}, dry_run=False,
                                  actor=(payload.get("actor") or "tutorial"))
    result = out.get("result") if isinstance(out.get("result"), dict) else {}
    merged = {**result}
    merged["ok"] = bool(result.get("ok", out.get("ok")))
    if out.get("error"):
        merged.setdefault("error", out["error"])
    return merged


def chapters_available(key: str) -> bool:
    """Whether this ontology ships authored chapters at all (its tutorial_style says so)."""
    try:
        feats = ontology_pages._settings(key).get("features") or {}
    except ontology_pages.PageError:
        return False
    return str(feats.get("tutorial_style") or "").lower() == "authored"

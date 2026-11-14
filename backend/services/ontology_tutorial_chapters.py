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
    """Make a page's absolute paths belong to THIS ontology on the app's own origin."""
    html = (
        html.replace('"/api/', f'"/api/ontology/{key}/wb/')
        .replace("'/api/", f"'/api/ontology/{key}/wb/")
        .replace('"/abctutorial/', f'"/api/ontology/{key}/abct/')
        .replace("'/abctutorial/", f"'/api/ontology/{key}/abct/")
    )
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
    return _rewrite(asset.read_text(encoding="utf-8"), key)


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
        raw = (query.get(name) or [None])[0]
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

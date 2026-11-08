"""The pages and JSON the app used to fetch from a per-ontology workbench server.

Five workbench processes (one per ontology, one port each) existed to serve three JSON documents and a
handful of HTML pages. After M1/M2 the compiler runs inside the app, so three of those five servers no
longer compute anything the app cannot compute in the same process — they were only a URL.

This module is that URL, removed:

  document(key)            objects, definitions, links, metrics        (compiler/ontology_api.build)
  cards(key)               every metric card: declaration · SQL · value (compiler/tutorial_api)
  sections(key)            which sections this profile serves           (its `features`)
  steps(key)               the tutorial's steps, authored or derived    (compiler/tutorial_api)
  tutorial_run / _definition(key, …)   one metric / one definition, run live
  page(key, name)          the profile's own HTML (the generated graph page, the tutorial shell)

Everything returns the SAME shapes the workbench returned, because the app's components were written
against them — the point of the move is one origin, not a new API.

The tutorial page's JavaScript calls `/api/tutorial/{steps,run,definition}` with ABSOLUTE paths; served
from this origin those would hit the app, so `page()` rewrites them to the per-ontology routes. That
rewrite is the whole compatibility layer, and it is testable: a page served here must not contain a
single bare `/api/tutorial/` path.
"""
from __future__ import annotations

import json
import logging
import pathlib

from services import ontology_runtime

logger = logging.getLogger(__name__)

FEATURE = pathlib.Path(__file__).resolve().parents[1] / "features" / "ontology"
WORKBENCH = FEATURE / "workbench"


class PageError(Exception):
    """The page or declaration asked for does not exist for this ontology."""


def _profile(key: str) -> pathlib.Path:
    profile = ontology_runtime.profile_for(key)
    if profile is None:
        # A key that a BUILDER declares is being built, not missing: the page cannot load yet because
        # nothing is installed, and "no ontology 'x'" reads like a typo. Say which agent owns it and
        # what turns it into an ontology, so the panel can point at the build instead of failing.
        try:
            from services import ontology_build as _ob
            from db.database import SessionLocal
            db = SessionLocal()
            try:
                who = [b for b in _ob.builders(db) if b.get("ontology_key") == key]
            finally:
                db.close()
        except Exception:                                        # noqa: BLE001
            who = []
        if who:
            b = who[0]
            raise PageError(
                f"{key!r} is being built, not installed yet: builder agent {b['agent_id']} "
                f"({b['agent_name']}) owns it. Its declarations only become pages after a staged "
                f"publish is applied — open the build (对话式构建) for this key, or apply its pending "
                f"publish in Settings → Ontology.")
        raise PageError(f"no ontology {key!r}")
    return profile


def _compiler():
    for path in (str(FEATURE / "compiler"), str(FEATURE)):
        import sys

        if path not in sys.path:
            sys.path.insert(0, path)
    import ontology_profile  # noqa: PLC0415

    return ontology_profile


def _settings(key: str) -> dict:
    return json.loads(_profile(key).read_text(encoding="utf-8"))


# ── JSON: the three documents ───────────────────────────────────────────────
def document(key: str) -> dict:
    """Objects, definitions, links and metrics of one ontology (the browser page's whole input)."""
    profile = _profile(key)
    with ontology_runtime._LOCK:
        _compiler().use(profile)
        import ontology_api  # noqa: PLC0415

        return ontology_api.build(profile)


def cards(key: str) -> list[dict]:
    """Every metric as a card: declaration, compiled SQL, value under the guard, or the refusal."""
    profile = _profile(key)
    with ontology_runtime._LOCK:
        prof = _compiler()
        prof.use(profile)
        import sqlgen  # noqa: PLC0415
        import tutorial_api  # noqa: PLC0415

        return tutorial_api.metric_cards(_settings(key), sqlgen.load())


def _has_dashboard(key: str) -> bool:
    """Does this ontology DECLARE a board? `dashboard.json` next to the profile is the whole test.

    The Dashboard section used to be injected by the UI for every ontology, so opening retail's
    dashboard offered "these ontologies have a board, open them" — i.e. it showed ANOTHER ontology's
    page for a configuration the user never chose. A section a profile does not serve is not offered.
    """
    try:
        return (_profile(key).parent / "dashboard.json").is_file()
    except Exception:                                            # noqa: BLE001
        return False


def sections(key: str) -> list[dict]:
    """Which sections this profile serves. Switched-off sections are named, not omitted silently."""
    feats = _settings(key).get("features") or {}
    rows = [
        {"key": "home", "label": "Graph view", "path": "/", "enabled": True,
         "hint": "the graph and the documentation generated from this TTL"},
        {"key": "query", "label": "Query", "path": "/query", "enabled": True,
         "hint": "ask in your own words; rules first, model only when unsure"},
        # the dashboard is an APP page, and it exists only when the profile DECLARES one
        {"key": "dashboard", "label": "Dashboard", "path": "/ontology/dashboard",
         "kind": "app", "enabled": _has_dashboard(key),
         "hint": "the board: declared metrics, an opening assessment, cross-filter"},
        {"key": "actions", "label": "Actions", "path": "/actions",
         "enabled": bool(feats.get("actions", False)),
         "hint": "declared writes: compiled preconditions, dry-run, audit"},
        {"key": "design", "label": "Design", "path": "/design", "enabled": True,
         "hint": "the architecture of this ontology"},
        {"key": "tutorial", "label": "Tutorial", "path": "/tutorial",
         "enabled": bool(feats.get("tutorial", True)),
         "hint": "a guided walk through the axioms and their numbers"},
    ]
    return rows


# ── the tutorial, live ──────────────────────────────────────────────────────
def steps(key: str) -> dict:
    profile = _profile(key)
    with ontology_runtime._LOCK:
        prof = _compiler()
        prof.use(profile)
        import sqlgen  # noqa: PLC0415
        import tutorial_api  # noqa: PLC0415

        doc = tutorial_api.authored(profile)
        if doc is not None:
            return doc
        return {"ok": True, "source": "derived", "profile": profile.name,
                "title": _settings(key).get("title"),
                "guard": _settings(key).get("guard") or {},
                "features": _settings(key).get("features") or {},
                "steps": tutorial_api.derive(_settings(key), sqlgen.load())}


def tutorial_run(key: str, metric: str) -> dict:
    profile = _profile(key)
    with ontology_runtime._LOCK:
        prof = _compiler()
        prof.use(profile)
        import sqlgen  # noqa: PLC0415
        import tutorial_api  # noqa: PLC0415

        return tutorial_api.run_metric(_settings(key), sqlgen.load(), metric)


def tutorial_definition(key: str, cls: str) -> dict:
    profile = _profile(key)
    with ontology_runtime._LOCK:
        prof = _compiler()
        prof.use(profile)
        import sqlgen  # noqa: PLC0415
        import tutorial_api  # noqa: PLC0415

        return tutorial_api.definition(_settings(key), sqlgen.load(), cls)


# ── the HTML pages ──────────────────────────────────────────────────────────
#: page name → (asset file, whether it needs the tutorial API rewrite)
PAGES = {
    "graph": ("ontology.html", False),
    "design": ("ontology.html", False),       # the same generated page carries the architecture view
    "tutorial": (None, True),                 # authored vs auto decided per profile
    "query": ("nl.html", False),              # the workbench's own ask page, same endpoints
    "actions": ("actions.html", False),       # the write-verb page: list, dry run, audit
}


#: files a page loads by an absolute path (`<script src="/tutorial_graph.js">`)
ASSETS = {"tutorial_graph.js", "architecture.svg"}


def asset(key: str, name: str) -> tuple[bytes, str]:
    """A page's own static file, from this origin. Whitelisted: a page names its assets, not a path."""
    if name not in ASSETS:
        raise PageError(f"no asset {name!r} (known: {sorted(ASSETS)})")
    path = WORKBENCH / name
    if not path.is_file():
        raise PageError(f"{key} has no asset {name}")
    ctype = ("image/svg+xml" if name.endswith(".svg")
             else "application/javascript; charset=utf-8")
    return path.read_bytes(), ctype


def page(key: str, name: str) -> tuple[str, str]:
    """(html, content_type) for one page of one ontology. Same-origin: no frame, no second port."""
    profile = _profile(key)
    feats = _settings(key).get("features") or {}
    authored = str(feats.get("tutorial_style") or "").lower() == "authored"
    if name == "tutorial":
        asset = WORKBENCH / ("tutorial.html" if authored else "tutorial_auto.html")
    else:
        entry = PAGES.get(name)
        if entry is None:
            raise PageError(f"no page {name!r} (known: {sorted(PAGES)})")
        filename = entry[0]
        # the generated graph page is the PROFILE's (it is built from that profile's TTL); a profile may
        # ship its own copy first, and otherwise the app's template is used. The Query/Actions pages are
        # the app's HTML — resolving those inside the profile asked a profile for a file it never owns.
        near = profile.parent / filename if filename else None
        asset = near if (near is not None and near.is_file()) else (WORKBENCH / filename if filename else None)
    if asset is None or not asset.is_file():
        raise PageError(f"{key} has no {name} page ({asset})")
    html = asset.read_text(encoding="utf-8")

    # the graph page is generated from the TTL: if the profile has none yet, generate it now (that is
    # what the workbench's `_app_page` did, and the reason logistics once served retail's page was that
    # a missing file resolved to another ontology's)
    if name in ("graph", "design") and not _is_own_graph_page(html, key):
        html = _regenerate_graph(key)
    if name == "tutorial":
        # absolute paths in the page's JS would hit the app root; point them at this ontology's routes.
        # The generated page asks for three things and only one of them is under `/api/tutorial/`: it also
        # reads the whole document (`/api/ontology`) and the card list (`/api/metrics/cards`).
        html = html.replace("/api/tutorial/", f"/api/ontology/{key}/tutorial/")
        html = (html.replace("'/api/ontology'", f"'/api/ontology/{key}/document'")
                    .replace('"/api/ontology"', f'"/api/ontology/{key}/document"')
                    .replace("'/api/ontology;", f"'/api/ontology/{key}/document;")
                    .replace("'/api/metrics/cards", f"'/api/ontology/{key}/metrics/cards")
                    .replace('"/api/metrics/cards', f'"/api/ontology/{key}/metrics/cards'))
        # the shell loads its own drawing script by an absolute path
        html = html.replace('"/tutorial_graph.js"', f'"/api/ontology/{key}/asset/tutorial_graph.js"')
        html = html.replace('"/architecture.svg"', f'"/api/ontology/{key}/asset/architecture.svg"')
        if authored:
            # the authored shell frames its own eight chapters (`/tutorial/1` … `/tutorial/8`); those pages
            # are served by the app under `/tutorial/chapter/{n}` now, so the iframe src must say so
            html = html.replace('"/tutorial/', f'"/api/ontology/{key}/tutorial/chapter/')
            html = html.replace("'/tutorial/", f"'/api/ontology/{key}/tutorial/chapter/")
    elif name in ("query", "actions"):
        # these three pages call the workbench's own JSON (`/api/nl`, `/api/actions`, `/api/samples`).
        # Every one of those has the same route on this origin under `/api/ontology/{key}/wb/…`, so the
        # rewrite is the whole port — the page and its endpoints travel together.
        html = html.replace('"/api/', f'"/api/ontology/{key}/wb/').replace("'/api/", f"'/api/ontology/{key}/wb/")
    return html, "text/html; charset=utf-8"


def _is_own_graph_page(html: str, key: str) -> bool:
    title = _settings(key).get("title") or key
    return title.split("（")[0].split("(")[0][:12] in html or key in html.lower()


def _regenerate_graph(key: str) -> str:
    """Generate the profile's graph page in-process (graph_view.py) and return it.

    The workbench generated this page on demand and served it. Doing the same here is what makes the
    page a same-origin asset of the app instead of an iframe into another server — and it is why the
    file's OWNER is the profile directory: the bug where logistics served retail's page was a missing
    file resolving to another ontology's.
    """
    import subprocess
    import sys

    profile = _profile(key)
    settings = _settings(key)
    out = profile.parent / "ontology.html"
    dsn = (settings.get("dsn") or {})
    args = [
        sys.executable, str(FEATURE / "compiler" / "graph_view.py"),
        "--ns", settings.get("ns") or "",
        "--out", str(out),
        "--title", settings.get("title") or key,
        "--sample", str(settings.get("sample") or 3),
    ]
    if settings.get("ontology_dir"):
        args += ["--ontology-dir", str((profile.parent / settings["ontology_dir"]).resolve())]
    if settings.get("overlay"):
        args += ["--overlay", str((profile.parent / settings["overlay"]).resolve())]
    if dsn:
        args += ["--dsn", " ".join(f"{k}={v}" for k, v in
                                   (("host", dsn.get("host")), ("port", dsn.get("port")),
                                    ("dbname", dsn.get("dbname")), ("user", dsn.get("user")),
                                    ("password", dsn.get("password") or "")) if v not in (None, ""))]
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=180,
                           cwd=str(FEATURE / "compiler"))
    except Exception as exc:                                    # noqa: BLE001
        raise PageError(f"could not generate {key}'s graph page ({type(exc).__name__}: {exc})") from exc
    if not out.is_file():
        tail = (p.stderr or p.stdout or "").strip().splitlines()
        raise PageError(f"the graph page was not generated for {key}"
                        + (f" ({tail[-1]})" if tail else ""))
    return out.read_text(encoding="utf-8")

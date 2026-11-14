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
import re
import threading
import time

from services import ontology_runtime

logger = logging.getLogger(__name__)

FEATURE = pathlib.Path(__file__).resolve().parents[1] / "features" / "ontology"
WORKBENCH = FEATURE / "workbench"


class PageError(Exception):
    """The page or declaration asked for does not exist for this ontology."""


# ── two caches, and what makes them safe ───────────────────────────────────
# Opening new_coldchain_v3 costs ~0.8 s to compile 91 metrics and ~0.9 s to run them, on every
# request, for every reader — the browser page asks for the document AND the cards, so a click
# cost ~1.7 s of work that had not changed since the last click. Parsing the TTL is not the cost
# (measured: 47 ms); the compile and the queries are.
#
# Both caches are keyed by a SIGNATURE of the declaration files (path, mtime, size), so a publish
# that rewrites a TTL invalidates them with no invalidation call to forget — the files are the
# state. `refresh=true` ignores the cache and recomputes, which is what the page's reload button
# sends: "I changed something outside your knowledge, look again".
_CACHE_LOCK = threading.Lock()
_DOC_CACHE: dict[str, tuple[tuple, dict]] = {}
_CARDS_CACHE: dict[str, tuple[float, tuple, list]] = {}
# How long a metric VALUE may be reused. Same 30 s the dashboard's panel cache uses: long enough to
# make clicking around one ontology free, short enough that a number is still "now".
CARDS_TTL_SECONDS = 30.0


def _signature(profile: pathlib.Path) -> tuple:
    """(path, mtime_ns, size) of every file this profile compiles from.

    The declaration files ARE the cache key: point the profile at different TTL, or let a publish
    rewrite one, and the signature changes by itself. No `invalidate(key)` anyone can forget to call.
    """
    try:
        settings = json.loads(profile.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        settings = {}
    base = profile.parent
    files = [profile]
    ontology_dir = base / str(settings.get("ontology_dir") or "ontology")
    if ontology_dir.is_dir():
        files += sorted(ontology_dir.glob("*.ttl"))
    overlay = base / str(settings.get("overlay") or "")
    if str(settings.get("overlay") or "") and overlay.is_file():
        files.append(overlay)
    out = []
    for f in files:
        try:
            st = f.stat()
        except OSError:
            continue
        out.append((str(f), st.st_mtime_ns, st.st_size))
    return tuple(out)


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
def tutorial_i18n(key: str) -> dict[str, str]:
    """The profile's declared translation for its own pages, in the language it declares.

    An authored page is hand-written HTML, so `ui.language: "zh"` used to change nothing at all —
    measured: 13 Chinese characters across retail's nine pages, and the `lang` the app appends to the
    frame was read by nobody. The pages cannot be re-authored per language, so the translation is
    DECLARED beside them:

        profiles/<key>/tutorial/i18n.json
        {"zh": {"Step 1 — one object, plain SQL": "第 1 步 —— 一个对象，纯 SQL"}}

    Only declared strings are replaced; anything missing stays as the page wrote it. A half-translated
    page is honest — a silently blank one is not.
    """
    try:
        base = _profile(key).parent
        lang = str((_settings(key).get("ui") or {}).get("language") or "").lower()
    except PageError:
        return {}
    path = base / "tutorial" / "i18n.json"
    if not lang or not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    table = doc.get(lang) or {}
    return {str(k): str(v) for k, v in table.items() if k and v}


def translate_page(key: str, html: str) -> str:
    """Apply the declared translation, longest source string first, IGNORING whitespace differences.

    A dictionary key is written as one line of prose; the page has the same prose broken across lines
    with indentation. Exact matching therefore missed a lot of it — measured: 52 of 310 retail entries
    never fired because the source had a newline where the key had a space, and the page stayed English
    while the dictionary looked complete. Runs of whitespace in the key match runs in the HTML, which is
    what "the same sentence" means in HTML.
    """
    table = tutorial_i18n(key)
    if not table:
        return html
    for source in sorted(table, key=len, reverse=True):
        parts = [re.escape(part) for part in source.split()]
        if not parts:
            continue
        pattern = re.compile(r"\s+".join(parts))
        if pattern.search(html):
            html = pattern.sub(lambda _m, text=table[source]: text, html)
    return html


def document(key: str, refresh: bool = False) -> dict:
    """Objects, definitions, links and metrics of one ontology (the browser page's whole input).

    Cached on the declaration signature (see `_signature`): the compiled document only changes when
    a TTL does, and compiling 91 metrics for a reader who read them a minute ago is wasted work.
    The dict is returned as-is and must not be mutated by callers.
    """
    profile = _profile(key)
    sig = _signature(profile)
    if not refresh:
        with _CACHE_LOCK:
            hit = _DOC_CACHE.get(key)
        if hit is not None and hit[0] == sig:
            return hit[1]
    with ontology_runtime._LOCK:
        _compiler().use(profile)
        import ontology_api  # noqa: PLC0415

        doc = ontology_api.build(profile)
    with _CACHE_LOCK:
        _DOC_CACHE[key] = (sig, doc)
    return doc


def cards(key: str, refresh: bool = False) -> list[dict]:
    """Every metric as a card: declaration, compiled SQL, value under the guard, or the refusal.

    This is the expensive read — one SQL query per metric, run live. Cached for `CARDS_TTL_SECONDS`
    on the declaration signature, so the values are at most half a minute old and `refresh=true`
    always tells the truth immediately.
    """
    profile = _profile(key)
    sig = _signature(profile)
    if not refresh:
        with _CACHE_LOCK:
            hit = _CARDS_CACHE.get(key)
        if hit is not None and hit[1] == sig and (time.time() - hit[0]) < CARDS_TTL_SECONDS:
            return hit[2]
    with ontology_runtime._LOCK:
        prof = _compiler()
        prof.use(profile)
        import sqlgen  # noqa: PLC0415
        import tutorial_api  # noqa: PLC0415

        out = tutorial_api.metric_cards(_settings(key), sqlgen.load())
    with _CACHE_LOCK:
        _CARDS_CACHE[key] = (time.time(), sig, out)
    return out


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
    body = path.read_bytes()
    if name.endswith(".js"):
        # A page's JavaScript is served from THIS origin, but it still calls the absolute paths the
        # workbench answered (`/api/graph?step=…`). `page()` already rewrites those inside HTML; an
        # asset was handed over byte for byte, so the graph fetched the app's own `/api/graph` — a
        # 404 — and printed "graph unavailable". Same rewrite, applied where the calls actually live.
        text = body.decode("utf-8")
        # One rewrite, applied to BOTH quote styles: `/api/graph` starts with `/api/`, so naming it
        # separately and then rewriting `/api/` again produced `/api/ontology/{key}/wb/ontology/…`.
        text = (text.replace('"/api/', f'"/api/ontology/{key}/wb/')
                    .replace("'/api/", f"'/api/ontology/{key}/wb/"))
        body = text.encode("utf-8")
    return body, ctype


def page(key: str, name: str) -> tuple[str, str]:
    """(html, content_type) for one page of one ontology. Same-origin: no frame, no second port."""
    profile = _profile(key)
    feats = _settings(key).get("features") or {}
    authored = str(feats.get("tutorial_style") or "").lower() == "authored"
    if name == "tutorial":
        # A profile that ships its OWN tutorial owns its shell too: `profiles/<key>/tutorial/shell.html`.
        # Retail's eight chapters live in the workbench because retail was the only authored one; a
        # second authored tutorial (cold chain) must not have to overwrite retail's shell to exist.
        own_shell = profile.parent / "tutorial" / "shell.html"
        if authored and own_shell.is_file():
            asset = own_shell
        else:
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
    if name in ("graph", "design") and (not _is_own_graph_page(html, key)
                                       or _graph_page_is_stale(key, asset)):
        # A page that predates its own declarations is WRONG, not merely old: measured on talent_v1
        # (2026-11-14) the shipped page still showed 9 metrics while the profile declared 11 and the
        # generator now emits 13 structure nodes — the browser drew a graph of a previous ontology and
        # the reader had no way to tell. Regenerating on mtime keeps the page a projection of the TTL.
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
        # …and say it in the language the profile declares (see `tutorial_i18n`).
        html = translate_page(key, html)
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



def _graph_page_is_stale(key: str, asset: pathlib.Path | None) -> bool:
    """True when the graph page is older than any declaration it claims to describe."""
    if asset is None or not asset.is_file():
        return False
    page_mtime = asset.stat().st_mtime
    try:
        profile = _profile(key)
    except PageError:
        return False
    settings = _settings(key)
    candidates = []
    onto_dir = profile.parent / (settings.get("ontology_dir") or "ontology")
    if onto_dir.is_dir():
        candidates += list(onto_dir.rglob("*.ttl"))
    overlay = settings.get("overlay")
    if overlay and (profile.parent / overlay).is_file():
        candidates.append(profile.parent / overlay)
    newest = max((c.stat().st_mtime for c in candidates), default=0)
    return newest > page_mtime

def _is_own_graph_page(html: str, key: str) -> bool:
    title = _settings(key).get("title") or key
    return title.split("（")[0].split("(")[0][:12] in html or key in html.lower()



def _resolved_dsn(settings: dict) -> dict:
    """The profile's dsn with ${VAR:-default} substituted.

    A profile stores placeholders (`${ONTOLOGY_DB_PASSWORD}`), because a password must not live in the
    file. graph_view runs in a subprocess and needs real values, so they are resolved here: the live
    environment first, then the repo's own `.env` (a subprocess does not inherit the service's dotenv),
    then the declared default. Measured on talent_v1: passing the placeholder through produced a page
    with no live numbers at all.
    """
    import os
    import re

    raw = settings.get("dsn") or {}
    env_file = pathlib.Path(__file__).resolve().parents[2] / ".env"
    file_values: dict[str, str] = {}
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, _, v = line.partition("=")
                file_values[k.strip()] = v.strip()

    out: dict[str, str] = {}
    for key, value in raw.items():
        text = str(value).strip()
        m = re.fullmatch(r"\$\{([A-Z0-9_]+)(?::-(.*))?\}", text)
        if m:
            var, default = m.group(1), (m.group(2) or "")
            text = os.environ.get(var) or file_values.get(var) or default
        if text:
            out[key] = text
    out.setdefault("host", os.environ.get("PGHOST") or file_values.get("POSTGRES_HOST") or "127.0.0.1")
    out.setdefault("port", os.environ.get("PGPORT") or file_values.get("POSTGRES_PORT") or "5432")
    out.setdefault("user", os.environ.get("PGUSER") or file_values.get("POSTGRES_USER") or "langconfig")
    out.setdefault("password", os.environ.get("PGPASSWORD") or file_values.get("POSTGRES_PASSWORD") or "")
    return out

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
    dsn = _resolved_dsn(settings)
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

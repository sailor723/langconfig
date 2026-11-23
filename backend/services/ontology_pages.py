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

import html
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
def global_language() -> str:
    """The app's UI language (**Settings → General → Language**), lower-cased, '' when unreadable.

    这一层以前只看 profile 自己的 `ui.language`，结果两件事悄悄分叉：
    界面切成中文，教程页还是英文；反过来也一样。用户在设置里选的语言是**一个**，
    所以这里读同一个数。读不到时返回空串，调用方退回 profile 的声明。
    """
    try:
        from core import settings as core_settings
        from db.database import SessionLocal
        db = SessionLocal()
        try:
            value = core_settings.resolve_value(db, "general") or {}
        finally:
            db.close()
        return str(value.get("language") or "").lower()
    except Exception:                                            # noqa: BLE001
        return ""


def configured_language(key: str) -> str:
    """Which language these pages should be rendered in.

    优先级：**全局设置**（Settings → General → Language）> profile 的 `ui.language`。
    全局设置是用户在界面上真正改的那一个，所以它说话最算数；profile 里那句话保留为
    "这个本体自己偏好什么"，只在全局读不到时兜底。
    """
    lang = global_language()
    if lang:
        return lang
    try:
        return str((_settings(key).get("ui") or {}).get("language") or "").lower()
    except PageError:
        return ""


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
        lang = configured_language(key)
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


def authored_language(key: str) -> str:
    """页面正文是用哪种语言手写的(声明在 i18n.json 的 `authored`)。"""
    try:
        path = _profile(key).parent / "tutorial" / "i18n.json"
        if not path.is_file():
            return ""
        return str((json.loads(path.read_text(encoding="utf-8")) or {}).get("authored") or "").lower()
    except (PageError, OSError, ValueError):
        return ""


def language_notice(key: str) -> str:
    """界面语言和正文母语不一致时,插一条说明 —— 半翻译要说出来,不能静默。"""
    lang, authored = configured_language(key), authored_language(key)
    if not lang or not authored or lang == authored:
        return ""
    if lang == "zh":
        text = "界面语言是中文；本页正文为英文原版（数字按原文实测，未逐句翻译）。"
    else:
        text = ("The interface language is English; the body of this page is Chinese-only "
                "because its numbers are measured against this client's data.")
    return (f'<div style="background:#eef4ff;border:1px solid #b6cdf5;border-radius:8px;'
            f'padding:9px 13px;margin:8px 0;font-size:12.5px;line-height:1.6">{text}</div>')


#: 会被"整块翻译"的标签:正文段落、列表项、小标题、表格单元、标签行
_BLOCK = re.compile(r'<(p|li|h2|h3|summary|td|th)([^>]*)>(.*?)</\1>', re.S)
_LABEL_BLOCK = re.compile(r'<div class="label">(.*?)</div>', re.S)


def _visible(inner: str) -> str:
    text = re.sub(r'<[^>]+>', ' ', inner)
    return re.sub(r'\s+', ' ', html.unescape(text)).strip()


def translate_blocks(key: str, html: str) -> str:
    """按**整块**替换正文(`i18n.json` 的 `en_blocks` / 任意 `<lang>_blocks` 表)。

    为什么需要它:字符串表是按连续文本替换的,而正文段落里到处是行内标签
    (`<code>:Candidate</code>、<strong>…</strong>`)—— 同一个句子在 HTML 里不是一个连续串,
    塞进字符串表一条都命中不了(retail 那 52 条就是这么失效的)。块级替换用
    "去掉标签后的可见文本"作键,替换值可以自带行内标签。
    """
    lang = configured_language(key)
    if not lang:
        return html
    try:
        path = _profile(key).parent / "tutorial" / "i18n.json"
        table = (json.loads(path.read_text(encoding="utf-8")) or {}).get(f"{lang}_blocks") or {}
    except (PageError, OSError, ValueError):
        return html
    if not table:
        return html

    def repl(m):
        inner = m.group(3)
        replay = table.get(_visible(inner))
        return m.group(0) if not replay else m.group(0).replace(inner, replay)

    html = _BLOCK.sub(repl, html)

    def repl_label(m):
        replay = table.get(_visible(m.group(1)))
        return m.group(0) if not replay else m.group(0).replace(m.group(1), replay)

    return _LABEL_BLOCK.sub(repl_label, html)


def translate_page(key: str, html: str) -> str:
    """Apply the declared translation, longest source string first, IGNORING whitespace differences.

    A dictionary key is written as one line of prose; the page has the same prose broken across lines
    with indentation. Exact matching therefore missed a lot of it — measured: 52 of 310 retail entries
    never fired because the source had a newline where the key had a space, and the page stayed English
    while the dictionary looked complete. Runs of whitespace in the key match runs in the HTML, which is
    what "the same sentence" means in HTML.
    """
    html = translate_blocks(key, html)      # 块级优先(正文)
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
def localize_steps(key: str, doc: dict) -> dict:
    """让"步骤列表"(浏览器里那一列)跟随全局语言。

    三类来源都走这里:
      ① 声明的 `i18n.<lang>` 块(首选:`tutorial.json` 里按语言给 title/intro/steps)——
         结构和原文一一对应,不靠字符串匹配,所以不会"看着翻译了其实一条没命中";
      ② 没有 `i18n` 块时,退回 `tutorial/i18n.json` 的字符串表,逐串替换 title/intro/步骤标题/正文;
      ③ 两者都没有 → 原样返回(页面上会挂语言说明条,不静默假装翻译过)。
    """
    lang = configured_language(key)
    if not lang or not isinstance(doc, dict):
        return doc
    declared = (doc.get("i18n") or {}).get(lang) or {}
    table = tutorial_i18n(key)

    def tr(text):
        if not isinstance(text, str):
            return text
        return table.get(text, text)

    out = dict(doc)
    if isinstance(declared.get("title"), str):
        out["title"] = declared["title"]
    else:
        out["title"] = tr(out.get("title"))
    if isinstance(declared.get("intro"), str):
        out["intro"] = declared["intro"]
    else:
        out["intro"] = tr(out.get("intro"))
    steps = doc.get("steps") or []
    dsteps = declared.get("steps") or []
    new_steps = []
    for i, st in enumerate(steps):
        if not isinstance(st, dict):
            new_steps.append(st)
            continue
        cur = dict(st)
        d = dsteps[i] if i < len(dsteps) and isinstance(dsteps[i], dict) else {}
        cur["title"] = d.get("title") or tr(st.get("title"))
        cur["body"] = d.get("body") or tr(st.get("body"))
        new_steps.append(cur)
    out["steps"] = new_steps
    out["lang"] = lang
    return out


def steps(key: str) -> dict:
    profile = _profile(key)
    with ontology_runtime._LOCK:
        prof = _compiler()
        prof.use(profile)
        import sqlgen  # noqa: PLC0415
        import tutorial_api  # noqa: PLC0415

        doc = tutorial_api.authored(profile)
        if doc is not None:
            return localize_steps(key, doc)
        return localize_steps(key, {"ok": True, "source": "derived", "profile": profile.name,
                "title": _settings(key).get("title"),
                "guard": _settings(key).get("guard") or {},
                "features": _settings(key).get("features") or {},
                "steps": tutorial_api.derive(_settings(key), sqlgen.load())})


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
    """True when the graph page was built from declarations that have since changed.

    mtime is not enough: a `git pull` gives every file the same timestamp, so a stale page looks current
    (measured on talent_v1: served 9 metrics with 12 structure nodes while the profile declared 11 and
    the generator emitted 13). The page therefore carries a fingerprint of the TTLs it read, and this
    compares it with the declarations on disk.
    """
    if asset is None or not asset.is_file():
        return False
    try:
        profile = _profile(key)
        settings = _settings(key)
    except PageError:
        return False
    html = asset.read_text(encoding="utf-8", errors="replace")
    m = re.search(r'"fingerprint":\s*"([0-9a-f]+)"', html)
    if not m:
        return True                     # a page with no fingerprint predates this check
    pages_fingerprint = m.group(1)

    import hashlib

    onto_dir = profile.parent / (settings.get("ontology_dir") or "ontology")
    candidates: list[pathlib.Path] = []
    overlay = settings.get("overlay")
    if overlay and (profile.parent / overlay).is_file():
        candidates.append(profile.parent / overlay)
    if onto_dir.is_dir():
        candidates += sorted(onto_dir.glob("*.ttl"))
    digest = hashlib.sha256()
    for path in candidates:
        digest.update(str(path.name).encode())
        digest.update(str(path.stat().st_size).encode())
        digest.update(path.read_bytes())
    generator = FEATURE / "compiler" / "graph_view.py"
    if generator.is_file():
        digest.update(generator.read_bytes())
    return digest.hexdigest()[:16] != pages_fingerprint

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

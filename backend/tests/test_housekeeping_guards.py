"""Housekeeping guards — the four truths that rotted quietly, as tests.

These are not feature tests. Each one asserts a property of the repository that was true when it was
written and silently stopped being true, in a way no feature test could notice:

1. **no route is declared twice.** `api/chat/documents.py` declared `/upload` and `/upload-multiple`
   twice (a copy-paste of the whole block). FastAPI registers both and matches the first, so the
   second was unreachable — and a submitter editing it would have changed nothing.
2. **no top-level function is defined twice in one module.** The same file had two
   `_extract_file_text` and two `_index_to_graphindex_for_chat`; Python keeps the LAST binding, so the
   newer helper was dead and the older one ran. Nothing failed; the wrong code just ran.
3. **every route the UI can navigate to actually renders something.** `ROUTE_TO_VIEW['/learning']`
   existed and the ActivityBar offered Learning, but the switch had no `case 'learning'`, so the
   activity silently showed the home page.
4. **the endpoints the instruction files quote exist.** `AGENTS.md` told every agent that
   `POST /api/workflows/{id}/execute` and `POST /api/agents/{id}/chat` are the API; both were gone.

Run: `cd backend && .venv/bin/python -m pytest tests/test_housekeeping_guards.py -q`
The first two read Python source with `ast`, so they need no database and no app import.
"""
from __future__ import annotations

import ast
import pathlib
import re
from collections import defaultdict

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
REPO = BACKEND.parent


def _python_files() -> list[pathlib.Path]:
    skip = {".venv", "venv", "outputs", "data", "__pycache__", "node_modules", "dist", ".uv-cache"}
    out: list[pathlib.Path] = []
    for p in BACKEND.rglob("*.py"):
        if any(part in skip for part in p.parts):
            continue
        out.append(p)
    return out


# ─────────────────────────────── 1. one route, one handler ───────────────────────────────────────
def _declared_routes(path: pathlib.Path) -> list[tuple[str, str, int]]:
    """(method, path, line) for every `@router.<verb>("…")` or `@router.api_route(...)` in a file."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    found: list[tuple[str, str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            fn = dec.func
            if not isinstance(fn, ast.Attribute) or not isinstance(fn.value, ast.Name):
                continue
            if fn.value.id not in ("router", "app"):
                continue
            if not dec.args or not isinstance(dec.args[0], ast.Constant):
                continue
            route = str(dec.args[0].value)
            if fn.attr == "api_route":
                methods = {"GET"}
                for kw in dec.keywords:
                    if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                        methods = {str(e.value).upper() for e in kw.value.elts
                                   if isinstance(e, ast.Constant)}
            else:
                methods = {fn.attr.upper()}
            for m in methods:
                found.append((m, route, node.lineno))
    return found


def test_no_route_is_declared_twice_in_one_router():
    """Two handlers for one (method, path): FastAPI serves the first and the second never runs."""
    problems: list[str] = []
    for path in _python_files():
        seen: dict[tuple[str, str], int] = {}
        for method, route, line in _declared_routes(path):
            key = (method, route)
            if key in seen:
                problems.append(f"{path.relative_to(REPO)}:{line} duplicates {method} {route} "
                                f"(first declared at line {seen[key]})")
            else:
                seen[key] = line
    assert not problems, "a route is declared twice:\n  " + "\n  ".join(problems)


# ─────────────────────────────── 2. one name, one definition ─────────────────────────────────────
@pytest.mark.parametrize("path", _python_files(), ids=lambda p: str(p.relative_to(REPO)))
def test_no_top_level_function_is_defined_twice(path: pathlib.Path):
    """A redefinition is not an error in Python — it silently discards the earlier function."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        pytest.skip("not parseable as Python")
    counts: dict[str, list[int]] = defaultdict(list)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            counts[node.name].append(node.lineno)
    dups = {name: lines for name, lines in counts.items() if len(lines) > 1}
    assert not dups, (f"{path.relative_to(REPO)} defines the same function twice "
                      f"(the last one wins, the rest are dead): {dups}")


# ─────────────────────── 3. every navigable route renders something ─────────────────────────────
APP_TSX = REPO / "src" / "App.tsx"


#: Views that are legitimately rendered somewhere other than the switch. Each entry needs a reason,
#: because the whole point of this test is that "no case" usually means "shows the home page".
RENDERED_ELSEWHERE = {
    # `/chat` is a full-screen page returned before the layout chrome, not a switch arm.
    "chat": "rendered as a full page in App.tsx before the layout (`if (currentView === 'chat')`)",
    # `/settings` renders as a modal over the current view.
    "settings": "rendered as SettingsModal over the current view (state-driven, also opened by the gear)",
}


def _goes_nowhere(views: set[str], cases: set[str]) -> set[str]:
    """Views that are routable but have neither a `case` nor a documented other rendering path."""
    aliases = {"home"}                      # '/': 'home' is the default arm
    return {v for v in views
            if v not in cases and v not in aliases and v not in RENDERED_ELSEWHERE}


@pytest.mark.skipif(not APP_TSX.exists(), reason="frontend not present")
def test_every_route_target_has_a_render_case():
    src = APP_TSX.read_text(encoding="utf-8")
    # ROUTE_TO_VIEW: Record<string, View> = { '/x': 'view', … }
    map_block = re.search(r"ROUTE_TO_VIEW[^=]*=\s*\{(.*?)\n\}", src, re.S)
    assert map_block, "ROUTE_TO_VIEW map not found in App.tsx — did the router change shape?"
    views = set(re.findall(r":\s*'([a-z0-9-]+)'", map_block.group(1)))
    cases = set(re.findall(r"case\s+'([a-z0-9-]+)'", src))
    dead = _goes_nowhere(views, cases)
    assert not dead, (
        "these views are routable but have no case in renderCurrentPage(), so clicking them shows "
        "the home page: " + ", ".join(sorted(dead)) +
        "\n(add a `case`, or document the alternate rendering path in RENDERED_ELSEWHERE)")


# ─────────────────── 4. the endpoints the instruction files quote are real ───────────────────────
INSTRUCTION_FILES = ["AGENTS.md", "CLAUDE.md"]
ENDPOINT_RE = re.compile(r"\b(?:GET|POST|PUT|PATCH|DELETE)\s+(/api/[A-Za-z0-9_\-{}/.]+)")


def _app_route_strings() -> set[str]:
    """Every path any router can mount, from the decorators — static, so no app import is needed."""
    paths: set[str] = set()
    for path in _python_files():
        for _method, route, _line in _declared_routes(path):
            paths.add(route)
    return paths


@pytest.mark.parametrize("doc", INSTRUCTION_FILES)
def test_quoted_api_endpoints_exist(doc: str):
    f = REPO / doc
    if not f.exists():
        pytest.skip(f"{doc} not present")
    text = f.read_text(encoding="utf-8")
    quoted = {m.group(1).rstrip(".,;:`)") for m in ENDPOINT_RE.finditer(text)}
    if not quoted:
        pytest.skip(f"{doc} quotes no endpoints in the VERB /api/… form")
    known = _app_route_strings()
    # a route may be declared with a router prefix, so match on the tail rather than the whole path
    def matches(path: str) -> bool:
        tail = re.sub(r"\{[^}]+\}", "{}", path)
        for candidate in known:
            ctail = re.sub(r"\{[^}]+\}", "{}", candidate)
            if ctail == tail or ctail.endswith(tail) or tail.endswith(ctail):
                return True
            # prefix-only match: '/api/knowledge/documents' vs '/documents' + prefix '/api/knowledge'
            if len(ctail.split("/")) >= 2 and tail.endswith(ctail):
                return True
        return False
    missing = sorted(p for p in quoted if not matches(p))
    assert not missing, (f"{doc} quotes endpoints that no router serves: " + ", ".join(missing) +
                         "\n(paths are matched against every decorator in backend/**/*.py, so a "
                         "missing one is either renamed or gone)")


# ────────────── 5. no component invents its own backend origin ─────────────────────────────────
SRC = REPO / "src"
HARDCODED_ORIGIN = re.compile(r"""['"]https?://(?:localhost|127\.0\.0\.1):8765""")


@pytest.mark.skipif(not SRC.exists(), reason="frontend not present")
def test_no_component_hardcodes_the_backend_origin():
    """Two files hardcoded http://localhost:8765, so they worked only on the developer's laptop.

    The canonical origin is `API_BASE_URL` from `src/config/api.ts` (empty = same origin, which is how
    the app is served in production and through the Vite proxy in dev).
    """
    offenders = []
    for path in SRC.rglob("*"):
        if path.suffix not in (".ts", ".tsx") or not path.is_file():
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("//", "*", "/*")):
                continue
            if HARDCODED_ORIGIN.search(line):
                offenders.append(f"{path.relative_to(REPO)}:{n}: {stripped[:90]}")
    assert not offenders, ("a component hardcodes the backend origin — use API_BASE_URL instead:\n  "
                           + "\n  ".join(offenders))


# ────────────── 6. artifact downloads know which workflow they came from ────────────────────────
def test_downloads_are_named_after_their_workflow():
    """`DownloadProvider` was never mounted, so every artifact was named "Generated_1.<ext>"."""
    canvas = SRC / "features" / "workflows" / "canvas" / "WorkflowCanvas.tsx"
    if not canvas.exists():
        pytest.skip("workflow canvas not present")
    text = canvas.read_text(encoding="utf-8")
    assert "<DownloadProvider" in text, (
        "WorkflowCanvas does not mount DownloadProvider: useDownloadContext falls back to a generic "
        "name, so downloaded images/audio/video are not named after the workflow that produced them")

#!/usr/bin/env python3
"""Settings-enabled dev server for the ontology app.

Routes:
    GET  /               → ontology.html (lane A view) with ⚙ gear and lane badge
    GET  /compare        → approach comparison: lane A (compiled SQL) vs lane B (SPARQL/Ontop)
    GET  /reasoner       → query console: run SPARQL against lane B, the HermiT demo, or a
                           read-only dry-run of a lane C guard ("would this action be admitted?")
    GET  /settings       → the settings form
    GET  /api/settings   → current settings (settings.json)
    GET  /api/lanes      → lane A vs lane B numbers as JSON
    GET  /api/ask        → POST {query}  → run SPARQL on the lane B endpoint
    GET  /api/dl         → POST {}       → run the DL reasoner demo (query_reasoner.py)
    POST /api/guard      → {name,params} → dry-run an action's compiled preconditions (rolls back)
    POST /api/settings   → save settings, regenerate ontology.html, report log

Two approaches, one question. Lane A compiles the ontology's axiom into SQL once and
runs it on the source database. Lane B asks the same question through a SPARQL
endpoint (Ontop over a virtual RDF graph with an R2RML mapping). Both read the same
rows, neither keeps a second copy. The settings panel picks which lane the app is
"on" and /compare shows them side by side; /reasoner lets you type a query yourself.

Stdlib only; regeneration and lane B are delegated to the interpreter that has
rdflib + psycopg2 (the cube tutorial venv), because that is what graph_view.py needs.
The HermiT demo runs under the repo .venv (owlready2 + Java).

Usage:
    python3 serve_ui.py            # http://127.0.0.1:8092
    python3 serve_ui.py --port 8092 --bind 127.0.0.1
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# `i18n`, `guard` and the rest of the compiler live next door in compiler/; the pages it serves
# live here. Both go on the path: the modules import each other by bare name.
_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "compiler"))
import i18n  # noqa: E402  (the UI language table and page translator)
import guard  # noqa: E402  (SQL guardrails: LIMIT, time bound, plan budget, statement timeout)

# The feature's own layout: this file is the WORKBENCH (the standalone server), the compiler sits
# next door, and the declarations live under profiles/. Nothing here is addressed by an absolute
# path to somebody else's machine — that is what made the workbench impossible to deploy.
BASE = pathlib.Path(__file__).resolve().parent          # this dir: the static pages it serves
FEATURE = BASE.parent                                   # backend/features/ontology
# The PROFILE root: the files the ontology owns (its ontology/ dir, schema/, tutorial_ont/,
# settings.json). They used to sit next to the server; now the server, the compiler and the
# declarations are three directories, and every one of them has to say WHICH it means.
PROFILE = FEATURE / "profiles" / "retail"
COMPILER = FEATURE / "compiler"
PROFILES = FEATURE / "profiles"
sys.path.insert(0, str(COMPILER))                       # the compiler imports itself by bare name
REPO = PROFILES
SETTINGS = PROFILES / "retail" / "settings.json"
APP_HTML = BASE / "ontology.html"
PYTHON = os.environ.get("ONTOLOGY_PYTHON") or sys.executable
DL_PYTHON = PYTHON
DL_SCRIPT = str(BASE / "query_reasoner.py")

DEFAULTS = {
    "ns": "https://cube.local/ontology/retail#",
    "ontology_dir": "ontology",
    "overlay": "metrics_ext.ttl",
    "dsn": dict(host="127.0.0.1", port=15432, dbname="retail_db",
                user="postgres", password="postgres"),
    # NOT "Retail ontology": a profile that omits `title` used to inherit that string and stamp it onto its
    # OWN generated page (measured on clinic: a clinic graph under a retail title). An empty default plus
    # `load_settings`'s derivation keeps every profile's page titled after that profile.
    "title": "",
    "sample": 20,
    # --- two approaches -------------------------------------------------------
    "lane": "a",
    "nl": {"backend": "auto", "model": "", "answer_llm": True},                                       # "a" compiled SQL | "b" SPARQL
    "ontop_endpoint": "http://127.0.0.1:8080/sparql",  # lane B: Ontop endpoint
    "ontop_ns": "http://example.org/retail#",          # lane B: its ontology namespace
    "ui": {"language": "en"},                          # "en" | "zh" — the interface language
    "guard": {"enabled": True, "max_rows": 1000, "default_window_days": 90,
              "statement_timeout_ms": 5000, "max_plan_rows": 2_000_000,
              "big_tables": {"orders": "placed_at"}},
    # what this deployment actually has: a profile can switch off the parts that do not exist
    "features": {"actions": True, "lane_b": True, "tutorial": True},
    "samples": [],                      # per-profile example questions for /query
    "profile": "",                      # which entry of `profiles` this process is
    "profiles": [],                     # dataset tabs: [{key, label, url}]
}

PILL = ('display:block;box-sizing:border-box;width:100%;text-align:left;'
        'font:12px -apple-system,Segoe UI,Roboto,sans-serif;color:#334e68;opacity:.72;'
        'text-decoration:none;background:#fff;border:1px solid #e3e6ea;border-radius:6px;'
        'padding:4px 9px;white-space:nowrap')

GEAR = ('<a href="/settings" aria-label="Settings" title="Settings ⚙" '
        'style="display:block;width:100%;text-align:center;font-size:20px;line-height:1;'
        'text-decoration:none;color:#334e68;opacity:.65;padding:2px 0">⚙</a>')

SIDEBAR_ITEMS = [
    ("/", "⌂", "Graph view"),
    ("/reasoner", "⌨", "Reasoner"),
    ("/query", "✦", "Query"),
    ("/actions", "⚡", "Actions"),
    ("/backlog", "▤", "Backlog"),
    ("/tutorial", "▸", "Tutorial"),
    ("/design", "◫", "Design"),
    ("/settings", "⚙", "Settings"),
]
# a profile can add one entry of its own (the training tutorial, for instance)
PROFILE_ITEMS_DEFAULT = []

# which nav entries a profile's `features` block switches off
FEATURE_OF = {"/actions": "actions", "/backlog": "actions", "/tutorial": "tutorial",
              "/compare": "lane_b"}


def _tutorial_style() -> str:
    """`authored` when the profile ships its own tutorial pages, `auto` otherwise.

    `features.tutorial_style` is the explicit answer; without it, a profile whose title and
    namespace are the retail reference (the only one with a hand-written tutorial) keeps it.
    """
    feats = _features()
    style = (feats.get("tutorial_style") or load_settings().get("tutorial_style") or "").lower()
    if style in ("authored", "auto"):
        return style
    s = load_settings()
    if (BASE / "tutorial1.html").exists() and (s.get("ns") or "").startswith(
            "https://cube.local/ontology/retail"):
        return "authored"
    return "auto"


def _features() -> dict:
    feats = dict(DEFAULTS["features"])
    feats.update((load_settings().get("features") or {}))
    return feats


def sidebar_html(active: str) -> str:
    style = (
        "<style>"
        "body{padding-left:56px;box-sizing:border-box}"
        "#sbnav{position:fixed;left:0;top:0;bottom:0;width:56px;background:#fff;"
        "border-right:1px solid #e3e6ea;z-index:1000;display:flex;flex-direction:column;"
        "align-items:center;gap:2px;padding:12px 0;overflow:hidden;"
        "transition:width .16s ease;font:12px -apple-system,Segoe UI,Roboto,sans-serif}"
        "#sbnav:hover{width:184px;align-items:flex-start;box-shadow:2px 0 12px rgba(16,42,67,.08)}"
        "#sbnav a{display:flex;align-items:center;gap:10px;width:100%;box-sizing:border-box;"
        "padding:7px 14px;text-decoration:none;color:#334e68;opacity:.78;white-space:nowrap}"
        "#sbnav a:hover{background:#f2f5f8;opacity:1}"
        "#sbnav a.on{background:#eef3fb;color:#0b4f9c;opacity:1;font-weight:600}"
        "#sbnav .ic{font-size:15px;width:18px;text-align:center;flex:none}"
        "#sbnav .lb{display:none}"
        "#sbnav:hover .lb{display:inline}"
        "#sbnav .sep{width:30px;height:1px;background:#e3e6ea;margin:8px auto;flex:none}"
        "#sbnav:hover .sep{width:100%}"
        "#sbnav .grow{flex:1}"
        "#sbnav .ptabs{display:flex;flex-direction:column;gap:2px;width:100%;"
        "box-sizing:border-box;padding:0 6px;margin-bottom:2px}"
        "#sbnav .ptab{font:10px ui-monospace,Menlo,monospace;text-align:center;"
        "padding:3px 4px;border-radius:5px;color:#687b8f;text-decoration:none;"
        "background:#f2f4f6;opacity:.75;white-space:nowrap;overflow:hidden}"
        "#sbnav .ptab.on{background:#0b4f9c;color:#fff;opacity:1;font-weight:600}"
        "#sbnav:hover .ptabs{flex-direction:row;gap:4px;padding:0 4px}"
        "#sbnav:hover .ptab{flex:1}"
        "</style>")
    feats = _features()
    profile_tabs = ""
    profs = load_settings().get("profiles") or []
    if profs:
        here = load_settings().get("profile") or ""
        tabs = "".join(
            f'<a class="ptab{" on" if pf["key"] == here else ""}" href="{pf["url"]}" '
            f'title="{pf["label"]}">{pf["label"]}</a>' for pf in profs)
        profile_tabs = f'<div class="ptabs">{tabs}</div><span class="sep"></span>'
    # a profile may add entries of its own (the ABC training tutorial, for instance)
    items = list(SIDEBAR_ITEMS) + [tuple(x) for x in (load_settings().get("extra_nav") or [])]
    links = []
    for href, icon, label in items:
        if not feats.get(FEATURE_OF.get(href, ""), True):
            continue
        cls = ' class="on"' if href == active else ""
        label = i18n.tr(label)
        links.append(f'<a href="{href}"{cls} title="{label}"><span class="ic">{icon}</span>'
                     f'<span class="lb">{label}</span></a>')
    # links may be shorter than SIDEBAR_ITEMS when a profile switches entries off
    nav = ('<div id="sbnav">' + profile_tabs + "".join(links[:-1]) +
           '<span class="grow"></span>' + (links[-1] if links else "") + '</div>')
    return style + nav


def inject_nav(html: str, active: str) -> str:
    nav = sidebar_html(active)
    if "</body>" in html:
        return html.replace("</body>", nav + "</body>", 1)
    return html + nav

LANE_LABEL = {
    "a": "lane A · compiled SQL (read)",
    "b": "lane B · SPARQL + Ontop (read)",
}

# bottom-left: the gear, then the ask console, then the action runner.
ASK = ('<a href="/reasoner" aria-label="Reasoner" '
       'title="Reasoner — SPARQL over Ontop, HermiT demo, lane C guard dry-run" '
       f'style="{PILL}">reasoner ⌨</a>')

ACTIONS_LINK = ('<a href="/actions" aria-label="Actions" '
                'title="Declared, validated, audited writes" '
                f'style="{PILL}">actions ⚡</a>')

NL_LINK = ('<a href="/query" aria-label="Query" '
           'title="Query — natural language: rules first, model only if unsure; '
           'answers carry the compiled SQL and capability path" '
           f'style="{PILL}">query ✦</a>')

BACKLOG_LINK = ('<a href="/backlog" aria-label="Declaration backlog" '
                'title="Refusal telemetry — what to declare next, from data (read-only)" '
                f'style="{PILL}">backlog ▤</a>')


def lane_badge(s: dict) -> str:
    lane = s.get("lane", "a")
    text = i18n.tr(LANE_LABEL.get(lane, LANE_LABEL["a"]))
    extra = ' · <a href="/compare" style="color:#0b4f9c;text-decoration:none">' \
        + i18n.tr("compare") + '</a>' if lane == "b" else ""
    return ('<div style="position:fixed;bottom:18px;right:18px;z-index:999;'
            'font:12px -apple-system,Segoe UI,Roboto,sans-serif;color:#687b8f;'
            f'opacity:.8;background:#fff;border:1px solid #e3e6ea;border-radius:6px;'
            f'padding:4px 8px">{text}{extra}'
            + ' · <a href="/actions" style="color:#b3261e;text-decoration:none">'
            + i18n.tr("lane C · actions (write)") + '</a></div>')


COMPILER_READY = True


def apply_profile(s: dict) -> None:
    """Point the compiler modules at this profile (ns, ontology dir, overlay, guard).

    The server itself is stdlib-only — the compiler (and therefore rdflib) lives in the
    child process that regenerates pages and imports metrics. `--settings` used to crash
    the whole server with ModuleNotFoundError when the launcher's interpreter lacked
    rdflib, which made a perfectly loadable profile look broken; now the profile still
    loads and only the compiler-backed endpoints refuse.
    """
    global COMPILER_READY
    try:
        import sqlgen
    except ModuleNotFoundError as exc:                # noqa: BLE001 — a stdlib launcher
        COMPILER_READY = False
        sys.stderr.write(f"[serve_ui] compiler unavailable in this interpreter ({exc}); "
                         f"compiled endpoints will refuse. Run under a python with rdflib "
                         f"for full behaviour.\n")
        guard.SETTINGS = SETTINGS
        return
    COMPILER_READY = True
    sqlgen.reconfigure(ns=s.get("ns"),
                       ontology_dir=str(prof_path(s.get("ontology_dir", "ontology")))
                       if s.get("ontology_dir") else None,
                       overlay=str(prof_path(s["overlay"])) if s.get("overlay") else "",
                       drop_overlay=not s.get("overlay"))
    guard.SETTINGS = SETTINGS
    import actions as _actions
    if s.get("actions_file"):
        _actions.SCHEMA = prof_path(s["actions_file"])


def load_settings() -> dict:
    s = json.loads(json.dumps(DEFAULTS))
    if SETTINGS.exists():
        try:
            s.update(json.loads(SETTINGS.read_text(encoding="utf-8")))
        except Exception:
            pass
    if not s.get("title"):
        # derive from the profile FILE, never from another ontology: `ontologies/clinic/clinic_settings.json`
        # -> "clinic". A page that announces the wrong ontology is the same failure as serving the wrong graph.
        stem = SETTINGS.stem
        s["title"] = stem[:-len("_settings")] if stem.endswith("_settings") else stem
    return s


def save_settings(s: dict) -> None:
    SETTINGS.write_text(json.dumps(s, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def dsn_text(dsn: dict) -> str:
    return " ".join(f"{k}={v}" for k, v in dsn.items())


def prof_path(rel: str) -> pathlib.Path:
    """Resolve a profile-relative path: the profile's own directory wins, then the app's.

    A profile used to live only next to the app, so `BASE / rel` was always right. An
    archived profile (or any profile outside `retail_graph/`) carries its own ontology and
    overlay, and resolving those against the app silently pointed at the retail files —
    the page would load, and show the wrong ontology. Absolute paths pass through.
    """
    if not rel:
        return BASE
    candidate = pathlib.Path(rel)
    if candidate.is_absolute():
        return candidate.resolve()
    near_profile = (SETTINGS.parent / candidate)
    if near_profile.exists():
        return near_profile.resolve()
    return (PROFILES / candidate).resolve()


def profile_path(rel: str) -> pathlib.Path:
    """Resolve a path that BELONGS to the profile — with NO fallback to the app's files.

    `prof_path`'s fallback is right for read-only assets a profile may not ship (it then borrows the app's)
    and WRONG for an output. Measured: `app_html` resolved the generated page through `prof_path`, so a
    profile without its own page — logistics — resolved to `retail_graph/ontology.html`, `_app_page()`
    found that file existing, SKIPPED the regeneration, and served retail's graph as logistics' overview.
    A path that will be written must never resolve to somebody else's file.
    """
    if not rel:
        return SETTINGS.parent
    p = pathlib.Path(rel)
    return p.resolve() if p.is_absolute() else (SETTINGS.parent / p).resolve()


def app_html(s: dict) -> pathlib.Path:
    """The generated graph page belongs to the profile, not to the app."""
    return profile_path(s.get("app_html") or "ontology.html")


def regenerate(s: dict) -> tuple[bool, str]:
    dsn = s["dsn"]
    cmd = [
        PYTHON, str(COMPILER / "graph_view.py"),
        "--ns", s["ns"],
        "--ontology-dir", str(prof_path(s["ontology_dir"])),
        *(["--overlay", str(prof_path(s["overlay"]))] if s.get("overlay") else []),
        "--dsn", dsn_text(dsn),
        "--title", s["title"],
        "--sample", str(s["sample"]),
        "--out", str(app_html(s)),
    ]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        log = (p.stdout or "") + (p.stderr or "")
        return p.returncode == 0, log[-4000:]
    except Exception as exc:  # noqa: BLE001
        return False, f"generator failed: {exc}"


NL_PYTHON = "/Users/weiping/dev/Learn/ontology/.venv/bin/python"


def _ollama_alive() -> bool:
    base = os.getenv("OLLAMA_BASE", "http://127.0.0.1:11434/v1").rstrip("/")
    probe = base[:-3] + "/api/tags" if base.endswith("/v1") else base + "/api/tags"
    try:
        urllib.request.urlopen(probe, timeout=1.5)
        return True
    except Exception:  # noqa: BLE001
        return False


def nl_config() -> dict:
    """What /query will use: the saved settings plus what the ENVIRONMENT can actually run."""
    s = (load_settings().get("nl") or {})
    backend = (s.get("backend") or "auto").lower()
    key_present = bool(os.getenv("DEEPSEEK_API_KEY"))
    ollama = _ollama_alive()
    effective = backend
    if backend == "auto":
        effective = "deepseek" if key_present else ("ollama" if ollama else "fallback")
    return {"backend": backend, "effective": effective, "model": s.get("model") or "",
            "answer_llm": bool(s.get("answer_llm")), "key_present": key_present,
            "ollama_alive": ollama,
            "deepseek_model": os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
            "ollama_model": os.getenv("OLLAMA_MODEL", "qwen2.5:3b")}


# ------------------------------------------------------------------ tutorial step 1
# Hard-coded question -> SQL. No LLM anywhere on this page: the point of step 1 is to show
# that "a question becomes a fixed SQL statement" before any ontology enters the picture.
TUTORIAL1_RULES = [
    (r"dana", r"达娜|dana",
     "SELECT id, name, tier FROM customers WHERE name LIKE '%Dana%';",
     "Dana's tier is DATA in a column, not a definition the system understands — "
     "the answer is one row and one column value."),
    (r"(how many|count).*(customers?|people|users?)|有多少|几个(客户|顾客|用户)",
     r"多少个?(客户|顾客|用户)",
     "SELECT count(*) AS customers FROM customers;",
     "count(*) counts the rows of the table — no WHERE means every row."),
    (r"premium|高级|优质|贵宾",
     r"高级|优质|贵宾",
     "SELECT id, name, tier FROM customers WHERE tier = 'PREMIUM' ORDER BY id;",
     "WHERE tier = 'PREMIUM' keeps only the rows whose tier column equals PREMIUM."),
    (r"standard|普通|标准",
     r"普通|标准",
     "SELECT id, name, tier FROM customers WHERE tier = 'STANDARD' ORDER BY id;",
     "The same WHERE shape with a different literal — that literal is the whole 'rule' here."),
    (r"(list|show|all).*(customers?|people|users?)|all customers",
     r"所有客户|全部客户|列出|看看",
     "SELECT id, name, tier FROM customers ORDER BY id;",
     "SELECT id, name, tier lists three columns of every row."),
]


def _dsn() -> dict:
    d = load_settings()["dsn"]
    return dict(host=d["host"], port=int(d["port"]), dbname=d["dbname"],
                user=d["user"], password=d["password"])


def run_tutorial1(question: str) -> dict:
    q = (question or "").strip().lower()
    if not q:
        return {"ok": False, "hint": "type a question, e.g. \"how many customers?\""}
    for pattern_en, pattern_zh, sql, why in TUTORIAL1_RULES:
        import re as _re
        if _re.search(pattern_en, q) or _re.search(pattern_zh, q):
            import psycopg2 as _pg
            conn = _pg.connect(**_dsn())
            try:
                cur = conn.cursor()
                cur.execute(sql)
                cols = [d[0] for d in cur.description]
                rows = [[str(v) for v in r] for r in cur.fetchall()]
            finally:
                conn.close()
            return {"ok": True, "question": question, "sql": sql, "why": why,
                    "cols": cols, "rows": rows}
    return {"ok": False,
            "hint": "step 1 understands only a few fixed questions (no model is used here). "
                    "Try: how many customers / which customers are premium / "
                    "is Dana premium / list all customers。"}


TUTORIAL2_RULES = [
    # join questions FIRST: "premium ..." must not be swallowed by the plain-revenue rule
    (r"premium.*(revenue|amount|total)|高级客户的(消费|收入|总额|金额)",
     r"高级客户的(消费|收入|总额|金额)",
     "SELECT sum(o.amount) AS premium_revenue FROM orders o "
     "JOIN customers c ON o.customer_id = c.id WHERE c.tier = 'PREMIUM';",
     "An aggregate over a joined set: the join decides WHICH orders, sum() adds them.",
     True),
    (r"premium.*(orders?|customers?)", r"高级客户的订单|高级客户订单",
     "SELECT o.id, c.name, o.amount FROM orders o "
     "JOIN customers c ON o.customer_id = c.id WHERE c.tier = 'PREMIUM' ORDER BY o.id;",
     "The same JOIN, a different WHERE — 'premium customer' is still just a column value.",
     True),
    (r"dana", r"达娜|dana",
     "SELECT o.id, c.name, o.amount, o.placed_at FROM orders o "
     "JOIN customers c ON o.customer_id = c.id WHERE c.name LIKE '%Dana%' ORDER BY o.id;",
     "The JOIN: orders.customer_id = customers.id links each order to its customer; "
     "the WHERE on c.name keeps only Dana's rows.", True),
    (r"(list|show|all).*(orders?)|all orders", r"所有订单|全部订单|列出订单|看看订单",
     "SELECT id, customer_id, amount, placed_at FROM orders ORDER BY id;",
     "One table first: orders alone — no join yet. Every order row points at a customer "
     "through the customer_id column.", False),
    (r"(how many|count).*(orders?)", r"多少(个|笔)?订单|订单数",
     "SELECT count(*) AS orders FROM orders;",
     "count(*) over the orders table — still one table, no join.", False),
    (r"(total|sum|revenue).*(orders?|amount|revenue)|\brevenue\b|total amount",
     r"订单总额|总金额|营收|收入",
     "SELECT sum(amount) AS revenue FROM orders;",
     "sum(amount) adds one column over every order row — the first aggregate, still one table.",
     False),
]


def run_tutorial2(question: str) -> dict:
    q = (question or "").strip().lower()
    if not q:
        return {"ok": False, "hint": "type a question, e.g. \"dana's orders\""}
    import re as _re
    for pattern_en, pattern_zh, sql, why, is_join in TUTORIAL2_RULES:
        if _re.search(pattern_en, q) or _re.search(pattern_zh, q):
            import psycopg2 as _pg
            conn = _pg.connect(**_dsn())
            try:
                cur = conn.cursor()
                cur.execute(sql)
                cols = [d[0] for d in cur.description]
                rows = [[str(v) for v in r] for r in cur.fetchall()]
            finally:
                conn.close()
            return {"ok": True, "question": question, "sql": sql, "why": why,
                    "join": is_join, "cols": cols, "rows": rows}
    return {"ok": False,
            "hint": "step 2 understands only a few fixed questions (no model). Try: "
                    "show all orders / how many orders / total revenue / "
                    "dana's orders / orders of premium customers / premium revenue。"}


def tutorial2_table() -> dict:
    import psycopg2 as _pg
    conn = _pg.connect(**_dsn())
    try:
        cur = conn.cursor()
        og = guard.run(cur, "SELECT id, customer_id, amount, placed_at FROM orders ORDER BY id")
        ocols, orows = og["cols"], [[str(v) for v in r] for r in og["rows"]]
        cg = guard.run(cur, "SELECT id, name, tier FROM customers ORDER BY id")
        ccols, crows = cg["cols"], [[str(v) for v in r] for r in cg["rows"]]
    finally:
        conn.close()
    return {"ok": True, "guard": _guard_report(og), "orders_sql": og["sql"],
            "orders": {"cols": ocols, "rows": orows,
                       "schema": [{"column": "id", "type": "integer", "note": "primary key"},
                                  {"column": "customer_id", "type": "integer",
                                   "note": "FK → customers.id (this is the link)"},
                                  {"column": "amount", "type": "numeric", "note": "order value"},
                                  {"column": "placed_at", "type": "timestamptz",
                                   "note": "when it happened"}]},
            "customers": {"cols": ccols, "rows": crows}}


TUTORIAL3_OBJECTS_TTL = """@prefix : <https://cube.local/ontology/retail#> .

:Customer a owl:Class ; :physicalTable "customers" ; :primaryKey "id" .
:Order    a owl:Class ; :physicalTable "orders"    ; :primaryKey "id" .

:name  a owl:DatatypeProperty ; rdfs:domain :Customer ; :physicalColumn "name" .
:tier  a owl:DatatypeProperty ; rdfs:domain :Customer ; :physicalColumn "tier" ;
       :state "action" .          # only actions may write this

:amount    a owl:DatatypeProperty ; rdfs:domain :Order ; :physicalColumn "amount" .
:placed_at a owl:DatatypeProperty ; rdfs:domain :Order ; :physicalColumn "placed_at" ."""

TUTORIAL3_AXIOM_TTL = """@prefix : <https://cube.local/ontology/retail#> .

:PremiumCustomer
    rdfs:subClassOf :Customer ;
    owl:equivalentClass [
        a owl:Class ;
        owl:intersectionOf (
            :Customer
            [ a owl:Restriction ; owl:onProperty :tier ; owl:hasValue "PREMIUM" ]
        )
    ] .

# The WHERE predicate in the answers below is COMPILED from this axiom:
#   tier = 'PREMIUM'
# — it is written once, in the ontology, not in every SQL statement."""


def tutorial3_table() -> dict:
    import psycopg2 as _pg
    conn = _pg.connect(**_dsn())
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, name, tier FROM customers ORDER BY id")
        cols = [d[0] for d in cur.description]
        rows = [[str(v) for v in r] for r in cur.fetchall()]
        cur.execute("SELECT count(*) FROM orders")
        orders = cur.fetchone()[0]
    finally:
        conn.close()
    return {"ok": True, "cols": cols, "rows": rows, "orders": orders}


def tutorial3_objects() -> dict:
    import sqlgen
    sqlgen.reconfigure(ns="https://cube.local/ontology/retail#",
                       ontology_dir=str(PROFILE / "ontology"))
    g = sqlgen.load()
    wanted = ["Customer", "Order", "PremiumCustomer"]
    classes = []
    for cls in wanted:
        cols = sqlgen.class_columns(g, cls) if cls != "PremiumCustomer" else {}
        base = sqlgen.concept_base_class(g, cls)
        table = sqlgen._one(g, sqlgen.P(cls), sqlgen.P("physicalTable"))
        if table is None and base:
            table = sqlgen._one(g, sqlgen.P(base), sqlgen.P("physicalTable"))
        pk = sqlgen._one(g, sqlgen.P(cls), sqlgen.P("primaryKey"))
        if pk is None and base:
            pk = sqlgen._one(g, sqlgen.P(base), sqlgen.P("primaryKey"))
        entry = {"name": cls, "table": table, "pk": pk,
                 "properties": sorted(cols.items()), "defined": False}
        try:
            pred = sqlgen.concept_sql(g, cls)
            entry.update({"defined": True, "base": base, "predicate": pred})
        except sqlgen.Refusal:
            pass
        classes.append(entry)
    code, acts = actions_cli("list")
    return {"ok": True, "ttl": TUTORIAL3_OBJECTS_TTL, "axiom": TUTORIAL3_AXIOM_TTL,
            "classes": classes,
            "actions": (acts or []) if code == 0 else []}


TUTORIAL3_RULES = [
    # read questions: the WHERE predicate is COMPILED from the ontology axiom
    (r"premium|高级|优质",
     None,
     "premium"),
    (r"(how many|count).*(customers?)|多少(个)?客户", None, "count_customers"),
    (r"(list|show|all).*(orders?)|所有订单|列出订单", None, "list_orders"),
    (r"(how many|count).*(orders?)|多少(个|笔)?订单", None, "count_orders"),
    (r"(promote|升级|提升).*(customer|客户)", None, "promote"),
]


def run_tutorial3(question: str) -> dict:
    q = (question or "").strip().lower()
    if not q:
        return {"ok": False, "hint": "try: which customers are premium? / list orders / "
                                     "promote customer 4"}
    import re as _re
    import sqlgen
    sqlgen.reconfigure(ns="https://cube.local/ontology/retail#",
                       ontology_dir=str(PROFILE / "ontology"))
    g = sqlgen.load()
    import psycopg2 as _pg

    def rows(sql, params=None):
        conn = _pg.connect(**_dsn())
        try:
            cur = conn.cursor()
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            data = [[str(v) for v in r] for r in cur.fetchall()]
        finally:
            conn.close()
        return cols, data

    for pattern_en, _unused, action in TUTORIAL3_RULES:
        if not _re.search(pattern_en, q):
            continue
        if action == "premium":
            pred = sqlgen.concept_sql(g, "PremiumCustomer")
            cols = sorted({c for c in (sqlgen.class_columns(g, "Customer") or {}).values()})
            sql = f"SELECT id, name, tier FROM customers WHERE {pred} ORDER BY id;"
            cols_, data = rows(sql)
            return {"ok": True, "kind": "read", "question": question, "sql": sql,
                    "compiled": pred,
                    "why": "The WHERE predicate `tier = 'PREMIUM'` is compiled from the "
                           "ontology axiom for :PremiumCustomer — no hand-written rule here.",
                    "cols": cols_, "rows": data,
                    "ttl": TUTORIAL3_AXIOM_TTL}
        if action == "count_customers":
            sql = "SELECT count(*) AS customers FROM customers;"
            cols_, data = rows(sql)
            return {"ok": True, "kind": "read", "question": question, "sql": sql,
                    "compiled": None,
                    "why": "The object type :Customer declares :physicalTable \"customers\" — "
                           "the compiler turns the object question into this count.",
                    "cols": cols_, "rows": data, "ttl": TUTORIAL3_OBJECTS_TTL}
        if action == "list_orders":
            sql = "SELECT id, customer_id, amount, placed_at FROM orders ORDER BY id;"
            cols_, data = rows(sql)
            return {"ok": True, "kind": "read", "question": question, "sql": sql,
                    "compiled": None,
                    "why": "Same shape as step 1, but the table/columns come from the "
                           ":Order object type declaration.",
                    "cols": cols_, "rows": data, "ttl": TUTORIAL3_OBJECTS_TTL}
        if action == "count_orders":
            sql = "SELECT count(*) AS orders FROM orders;"
            cols_, data = rows(sql)
            return {"ok": True, "kind": "read", "question": question, "sql": sql,
                    "compiled": None, "why": "Count over the :Order object type.",
                    "cols": cols_, "rows": data, "ttl": TUTORIAL3_OBJECTS_TTL}
        if action == "promote":
            m = _re.search(r"(?:customer|客户)\s*#?(\d+)", q)
            cid = int(m.group(1)) if m else 4
            code, dry = actions_cli("check", "--action", "PromoteCustomer",
                                    "--params", json.dumps({"customer_id": cid}))
            if code != 0 or not isinstance(dry, dict) or not dry.get("ok"):
                return {"ok": False, "hint": f"the guard refused: {dry}"}
            return {"ok": True, "kind": "action", "question": question,
                    "name": "PromoteCustomer", "params": {"customer_id": cid},
                    "admitted": dry.get("admitted"),
                    "sql": dry.get("effect_bound") or dry.get("effect"),
                    "checks": [{"kind": c["kind"], "sql": c.get("sql_bound") or c.get("sql"),
                                "pass": c["pass"]} for c in dry.get("checks", [])],
                    "why": "A WRITE is not a free UPDATE: it is a declared action type with "
                           "preconditions and an audit row. This is a dry-run (nothing written).",
                    "ttl": TUTORIAL3_OBJECTS_TTL}
    return {"ok": False, "hint": "step 3 understands only a few fixed questions. Try: "
                                 "which customers are premium? / how many customers / "
                                 "list orders / how many orders / promote customer 4"}


def _guard_report(g: dict) -> dict:
    """What the guard did, in the form the pages render under the SQL."""
    return {"notes": g.get("notes") or [], "plan_rows": g.get("plan_rows"),
            "ms": g.get("ms"), "text": guard.report(g), "sql": g.get("sql")}


def tutorial1_table() -> dict:
    import psycopg2 as _pg
    conn = _pg.connect(**_dsn())
    try:
        cur = conn.cursor()
        g = guard.run(cur, "SELECT id, name, tier FROM customers ORDER BY id")
        cols, rows = g["cols"], [[str(v) for v in r] for r in g["rows"]]
    finally:
        conn.close()
    return {"ok": True, "cols": cols, "rows": rows, "guard": _guard_report(g),
            "schema": [{"column": "id", "type": "integer", "note": "primary key"},
                       {"column": "name", "type": "text", "note": "the customer's name"},
                       {"column": "tier", "type": "text", "note": "PREMIUM or STANDARD"}]}


def tutorial5_reason(mode: str, customer_id: int = 2) -> dict:
    """Run the video-case reasoner (ontology venv: rdflib + owlrl).

    mode=stored/promote are the in-memory 3-triple demos; mode=live builds the same
    graph from the LIVE database, so an action's effect can be reasoned about right away.
    """
    try:
        p = subprocess.run([NL_PYTHON, str(BASE / "tutorial5_reason.py"), mode, str(customer_id)],
                           capture_output=True, text=True, timeout=90, cwd=str(BASE))
        txt = p.stdout.strip()
        if not txt:
            return {"ok": False, "error": (p.stderr or "no output")[-600:]}
        return json.loads(txt)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"reasoner failed: {exc}"}


TUTORIAL_GRAPHS = {
    1: {"nodes": [
        {"id": "cust", "t": ":Customer", "l": ["object · stored in customers"],
         "x": 40, "y": 40, "w": 170, "h": 54, "k": "object"},
        {"id": "id", "t": "id", "l": ["primary key"], "x": 270, "y": 20, "w": 110, "h": 40, "k": "prop"},
        {"id": "name", "t": "name", "l": ["text"], "x": 270, "y": 70, "w": 110, "h": 40, "k": "prop"},
        {"id": "tier", "t": "tier", "l": ["PREMIUM | STANDARD"], "x": 270, "y": 120, "w": 130, "h": 40, "k": "prop"},
    ], "edges": [
        {"a": "cust", "b": "id", "l": "property"},
        {"a": "cust", "b": "name", "l": "property"},
        {"a": "cust", "b": "tier", "l": "property"},
    ]},
    2: {"nodes": [
        {"id": "cust", "t": ":Customer", "l": ["object · customers"],
         "x": 40, "y": 40, "w": 150, "h": 54, "k": "object"},
        {"id": "ord", "t": ":Order", "l": ["object · orders"],
         "x": 260, "y": 40, "w": 150, "h": 54, "k": "object"},
        {"id": "fk", "t": "customer", "l": ["the link", "customer_id = id"],
         "x": 150, "y": 130, "w": 150, "h": 44, "k": "defined"},
    ], "edges": [
        {"a": "ord", "b": "fk", "l": "link", "k": "join"},
        {"a": "fk", "b": "cust", "l": "link", "k": "join"},
    ]},
    3: {"nodes": [
        {"id": "Customer", "t": ":Customer", "l": ["table customers"],
         "x": 40, "y": 30, "w": 150, "h": 50, "k": "class"},
        {"id": "Order", "t": ":Order", "l": ["table orders"],
         "x": 250, "y": 30, "w": 150, "h": 50, "k": "class"},
        {"id": "PremiumCustomer", "t": ":PremiumCustomer", "l": ["defined class"],
         "x": 40, "y": 130, "w": 170, "h": 50, "k": "defined"},
    ], "edges": [
        {"a": "PremiumCustomer", "b": "Customer", "l": "subClassOf", "k": "sub"},
        {"a": "Order", "b": "Customer", "l": "customer_id", "k": "join"},
        {"a": "PremiumCustomer", "b": "PremiumCustomer", "l": "≡ tier = 'PREMIUM'", "k": "def", "self": True},
    ]},
    4: {"nodes": [
        {"id": "Promote", "t": "PromoteCustomer", "l": ["action type"],
         "x": 40, "y": 60, "w": 170, "h": 50, "k": "action"},
        {"id": "Customer", "t": ":Customer", "l": ["table customers"],
         "x": 270, "y": 30, "w": 150, "h": 50, "k": "class"},
        {"id": "tier", "t": "tier", "l": ["PREMIUM"], "x": 270, "y": 120, "w": 110, "h": 40, "k": "prop"},
        {"id": "audit", "t": "audit_events", "l": ["before / after / spec"],
         "x": 460, "y": 60, "w": 170, "h": 50, "k": "store"},
    ], "edges": [
        {"a": "Promote", "b": "Customer", "l": "appliesTo", "k": "join"},
        {"a": "Promote", "b": "tier", "l": "writes", "k": "write"},
        {"a": "Promote", "b": "audit", "l": "audits", "k": "write"},
    ]},
    5: {"nodes": [
        {"id": "Customer", "t": ":Customer", "l": ["customers"],
         "x": 40, "y": 30, "w": 140, "h": 50, "k": "class"},
        {"id": "Order", "t": ":Order", "l": ["orders"],
         "x": 40, "y": 130, "w": 140, "h": 50, "k": "class"},
        {"id": "placesOrder", "t": "placesOrder", "l": ["inverseOf customer"], "x": 230, "y": 80, "w": 150, "h": 44, "k": "prop"},
        {"id": "amount", "t": "amount", "l": ["numeric"], "x": 230, "y": 150, "w": 110, "h": 40, "k": "prop"},
        {"id": "PremiumCustomer", "t": ":PremiumCustomer", "l": ["defined: amount ≥ gate"],
         "x": 430, "y": 30, "w": 180, "h": 50, "k": "defined"},
    ], "edges": [
        {"a": "Customer", "b": "placesOrder", "l": "domain", "k": "join"},
        {"a": "placesOrder", "b": "Order", "l": "range", "k": "join"},
        {"a": "Order", "b": "amount", "l": "column", "k": "prop"},
        {"a": "PremiumCustomer", "b": "Customer", "l": "⊓ ∃ placesOrder", "k": "def"},
        {"a": "PremiumCustomer", "b": "amount", "l": "≥ gate", "k": "def"},
    ]},
    6: {"nodes": [
        {"id": "Order", "t": ":Order", "l": ["grain of the metrics"],
         "x": 40, "y": 30, "w": 140, "h": 50, "k": "class"},
        {"id": "Customer", "t": ":Customer", "l": ["customers"],
         "x": 40, "y": 130, "w": 140, "h": 50, "k": "class"},
        {"id": "revenue", "t": "orderRevenue", "l": ["sum(amount)"], "x": 230, "y": 20, "w": 140, "h": 44, "k": "prop"},
        {"id": "aov", "t": "averageOrderValue", "l": ["ratio_of_sums"], "x": 230, "y": 90, "w": 140, "h": 44, "k": "prop"},
        {"id": "window", "t": "revenueLastDays", "l": ["sum where RecentOrder"], "x": 230, "y": 160, "w": 170, "h": 44, "k": "prop"},
        {"id": "prem", "t": "premiumCustomerRevenue", "l": ["where tier='PREMIUM'"], "x": 430, "y": 60, "w": 170, "h": 44, "k": "defined"},
        {"id": "customers", "t": "customers", "l": ["count(*)"], "x": 430, "y": 140, "w": 120, "h": 44, "k": "prop"},
    ], "edges": [
        {"a": "Order", "b": "revenue", "l": "grain", "k": "join"},
        {"a": "Order", "b": "aov", "l": "grain", "k": "join"},
        {"a": "Order", "b": "window", "l": "grain", "k": "join"},
        {"a": "Customer", "b": "prem", "l": "where", "k": "join"},
        {"a": "Customer", "b": "customers", "l": "grain", "k": "join"},
    ]},
    7: {"nodes": [
        {"id": "Order", "t": ":Order", "l": ["orders"], "x": 30, "y": 30, "w": 130, "h": 46,
         "k": "class"},
        {"id": "Product", "t": ":Product", "l": ["products"], "x": 30, "y": 140, "w": 130, "h": 46,
         "k": "class"},
        {"id": "OrderLine", "t": "Order contains Product", "l": ["link → order_lines", "carries qty"],
         "x": 210, "y": 85, "w": 170, "h": 46, "k": "defined"},
        {"id": "qty", "t": "qty", "l": ["int"], "x": 400, "y": 20, "w": 90, "h": 38, "k": "prop"},
        {"id": "price", "t": "price", "l": ["money"], "x": 400, "y": 90, "w": 100, "h": 38,
         "k": "prop"},
        {"id": "rev", "t": "revenueByProduct", "l": ["sum(qty * price)"], "x": 400, "y": 160,
         "w": 170, "h": 40, "k": "prop"},
        {"id": "byCity", "t": "revenueByProductCity", "l": ["GROUP BY product, city"],
         "x": 600, "y": 120, "w": 195, "h": 40, "k": "store"},
    ], "edges": [
        {"a": "OrderLine", "b": "Order", "l": "order_ref", "k": "join"},
        {"a": "OrderLine", "b": "Product", "l": "product_ref", "k": "join"},
        {"a": "OrderLine", "b": "qty", "l": "column", "k": "prop"},
        {"a": "Product", "b": "price", "l": "column", "k": "prop"},
        {"a": "OrderLine", "b": "rev", "l": "grain", "k": "prop"},
        {"a": "rev", "b": "byCity", "l": "two keys", "k": "join"},
    ]},
    8: {"nodes": [
        {"id": "Order", "t": ":Order", "l": ["orders"], "x": 30, "y": 30, "w": 130, "h": 46,
         "k": "class"},
        {"id": "Store", "t": ":Store", "l": ["stores"], "x": 30, "y": 140, "w": 130, "h": 46,
         "k": "class"},
        {"id": "soldAt", "t": "sold_at", "l": ["FK on the order row", "many orders → one store"],
         "x": 210, "y": 85, "w": 190, "h": 46, "k": "defined"},
        {"id": "city", "t": "city", "l": ["the dimension"], "x": 430, "y": 20, "w": 110, "h": 38,
         "k": "prop"},
        {"id": "byCity", "t": "revenueByCity", "l": ["sum(amount) GROUP BY city"],
         "x": 430, "y": 90, "w": 180, "h": 40, "k": "prop"},
        {"id": "prem", "t": "premiumRevenueByCity", "l": ["WHERE tier='PREMIUM'"],
         "x": 430, "y": 160, "w": 190, "h": 40, "k": "store"},
    ], "edges": [
        {"a": "Order", "b": "soldAt", "l": "link", "k": "join"},
        {"a": "soldAt", "b": "Store", "l": "link", "k": "join"},
        {"a": "Store", "b": "city", "l": "column", "k": "prop"},
        {"a": "Store", "b": "byCity", "l": "group key", "k": "join"},
        {"a": "byCity", "b": "prem", "l": "filtered by", "k": "join"},
    ]},
}

def tutorial_graph(step: int) -> dict:
    g = TUTORIAL_GRAPHS.get(step)
    if g is None:
        return {"ok": False, "error": f"no graph for step {step}"}
    return {"ok": True, "step": step, "nodes": g["nodes"], "edges": g["edges"]}


# ------------------------------------------------------------------ tutorial step 6
STEP6_METRICS = ["orderRevenue", "orderCount", "averageOrderValue", "maximumOrderValue",
                 "customers", "premiumCustomers", "premiumCustomerRevenue",
                 "premiumCustomersWithOrders", "revenuePerCustomer"]


def _window_since(days: int):
    """Midnight N days ago (UTC). The window is whole days, so the date shown in the UI is
    exactly the boundary the compiled SQL filters on — no hidden hours."""
    import datetime as dt
    now = dt.datetime.now(dt.timezone.utc)
    return (now - dt.timedelta(days=int(days))).replace(hour=0, minute=0, second=0,
                                                        microsecond=0)


def _tutorial6_graph(days: int | None = None, formula: str | None = None,
                     aggregate: str | None = None, where: str | None = None,
                     metric: str | None = None):
    """App ontology + overlay, with optional in-memory edits for one metric."""
    import sqlgen
    from rdflib import Literal, RDF, OWL, RDFS
    from rdflib.collection import Collection
    from rdflib.namespace import XSD
    sqlgen.reconfigure(ns="https://cube.local/ontology/retail#",
                       ontology_dir=str(PROFILE / "ontology"))
    g = sqlgen.load()
    P = sqlgen.P
    if days is not None:
        # :RecentOrder ≡ :Order ⊓ (:placed_at ≥ now - days)  — a time window
        since = _window_since(days).isoformat()
        rnode = P("_r_recent")
        g.add((rnode, RDF.type, OWL.Restriction))
        g.add((rnode, OWL.onProperty, P("placed_at")))
        g.add((rnode, XSD.minInclusive, Literal("'" + since + "'")))
        lst = P("_l_recent")
        Collection(g, lst, [P("Order"), rnode])
        inter = P("_i_recent")
        g.add((inter, RDF.type, OWL.Class))
        g.add((inter, OWL.intersectionOf, lst))
        g.add((P("RecentOrder"), RDF.type, OWL.Class))
        g.add((P("RecentOrder"), RDFS.subClassOf, P("Order")))
        g.add((P("RecentOrder"), OWL.equivalentClass, inter))
        g.add((P("revenueLastDays"), RDF.type, OWL.DatatypeProperty))
        g.add((P("revenueLastDays"), P("aggregate"), Literal("sum")))
        g.add((P("revenueLastDays"), P("grain"), P("Order")))
        g.add((P("revenueLastDays"), P("universe"), P("Order")))
        g.add((P("revenueLastDays"), P("formula"), Literal("amount")))
        g.add((P("revenueLastDays"), P("where"), P("RecentOrder")))
        g.add((P("revenueLastDays"), P("unit"), Literal("money")))
        g.add((P("revenueLastDays"), RDFS.label, Literal(f"Revenue last {int(days)} days")))
    if metric and formula and aggregate:
        g.remove((P(metric), P("formula"), None))
        g.remove((P(metric), P("aggregate"), None))
        g.remove((P(metric), P("where"), None))
        g.add((P(metric), P("formula"), Literal(formula)))
        g.add((P(metric), P("aggregate"), Literal(aggregate)))
        if where:
            g.add((P(metric), P("where"), P(where)))
    return g


def tutorial6_ask(question: str, days: int | None = 30) -> dict:
    """A question answered AGAINST THE METRIC DEFINITIONS this step shows.

    The pipeline is the one /query runs (menu -> interpret -> validate -> execute ->
    answer); only the menu differs: this page's overlay puts :revenueLastDays on it, so a
    windowed question can resolve. A window in the words ("last 7 days") re-parameterises
    that metric instead of stacking a second filter, and the answer carries the definition
    that produced the number — that is the whole point of asking here.
    """
    import nl
    q = (question or "").strip()
    if not q:
        return {"ok": False, "refused": "empty question"}
    # a window in the words re-parameterises :revenueLastDays (its threshold lives in the
    # axiom, so "last 7 days" rewrites the facet — it does not stack a second filter)
    import re as _re
    tw = (nl._slots(q).get("TimeWindow") or {}) if q else {}
    label = (tw.get("label") or "").lower()
    m = _re.search(r"(\d+)\s*days?", label)
    asked_days = int(m.group(1)) if m else None
    if tw and asked_days is None:
        g0 = _tutorial6_graph(days or 30)
        return {"ok": False, "question": q,
                "refused": f"this page's window metric counts whole days — "
                           f"ask “revenue last N days” instead of “{tw.get('label')}”",
                "menu": _metric_menu(g0)}
    window_days = int(asked_days or days or 30)
    g = _tutorial6_graph(window_days)
    try:
        out = nl.ask(q, graph=g, record=False, slots=False)
    except nl.NlRefusal as exc:
        return {"ok": False, "question": q, "refused": str(exc),
                "menu": _metric_menu(g)}
    r = out.get("result") or {}
    name = r.get("name")
    return {"ok": True, "question": q, "intent": out.get("intent"),
            "answer": out.get("answer"), "answer_source": out.get("answer_source"),
            "steps": out.get("steps"), "total_ms": out.get("total_ms"),
            "window_days": window_days,
            "is_card": name in STEP6_METRICS + ["revenueLastDays"],
            "result": {"name": name, "kind": r.get("kind"), "sql": r.get("sql"),
                       "compiled_sql": r.get("compiled_sql"),
                       "guard": r.get("guard"),
                       "value": r.get("value"), "rows": r.get("rows") or [],
                       "capability_path": r.get("capability_path") or [],
                       "notes": r.get("notes") or [],
                       "definition": _metric_definition(g, name) if name else None,
                       "label": (nl._label(g, name)[0] if name else None)}}


def _metric_menu(g) -> dict:
    """The metrics this page can answer from — used to explain a refusal."""
    import nl
    m = nl.menu(g)
    return {"metrics": [{"name": x["name"], "label": x.get("label"),
                         "definition": _metric_definition(g, x["name"])}
                        for x in m.get("metrics", [])]}


# ------------------------------------------------------------------ tutorial step 7
STEP7_METRICS = ["productRevenue", "revenueByProduct", "revenueByProductCity",
                 "premiumProductRevenue", "premiumRevenueByProduct"]
STEP8_METRICS = ["revenueByCity", "premiumRevenueByCity"]


def tutorial7_tables() -> dict:
    """The third table, and the association that connects it to orders."""
    import psycopg2 as _pg
    conn = _pg.connect(**_dsn())
    try:
        cur = conn.cursor()
        pg_ = guard.run(cur, "SELECT id, name, price FROM products ORDER BY id")
        pcols, prows = pg_["cols"], [[str(v) for v in r] for r in pg_["rows"]]
        lg_ = guard.run(cur, "SELECT id, order_id, product_id, qty FROM order_lines ORDER BY id")
        lcols, lrows = lg_["cols"], [[str(v) for v in r] for r in lg_["rows"]]
    finally:
        conn.close()
    return {"ok": True,
            "products": {"cols": pcols, "rows": prows,
                         "schema": [{"column": "id", "type": "integer", "note": "primary key"},
                                    {"column": "name", "type": "text",
                                     "note": "what the product is called"},
                                    {"column": "price", "type": "numeric",
                                     "note": "unit price — money per item"}]},
            "order_lines": {"cols": lcols, "rows": lrows,
                            "schema": [{"column": "id", "type": "integer", "note": "primary key"},
                                       {"column": "order_id", "type": "integer",
                                        "note": "FK → orders.id"},
                                       {"column": "product_id", "type": "integer",
                                        "note": "FK → products.id (the link to products)"},
                                       {"column": "qty", "type": "integer",
                                        "note": "how many of that product"}]}}


def tutorial8_tables() -> dict:
    """The object that is only ever a dimension: Store."""
    import psycopg2 as _pg
    conn = _pg.connect(**_dsn())
    try:
        cur = conn.cursor()
        sg = guard.run(cur, "SELECT id, city FROM stores ORDER BY id")
        cols, rows = sg["cols"], [[str(v) for v in r] for r in sg["rows"]]
        cg = guard.run(cur, "SELECT s.city, count(*) AS orders, "
                            "coalesce(sum(o.amount), 0) AS revenue "
                            "FROM orders o JOIN stores s ON o.sold_at = s.id "
                            "GROUP BY s.city ORDER BY 3 DESC", mode="declared")
        per_city = [{"city": r[0], "orders": int(r[1]), "revenue": _fmt_value(r[2], money=True)}
                    for r in cg["rows"]]
    finally:
        conn.close()
    return {"ok": True,
            "stores": {"cols": cols, "rows": rows,
                       "schema": [{"column": "id", "type": "integer", "note": "primary key"},
                                  {"column": "city", "type": "text",
                                   "note": "the dimension every city metric groups by"}]},
            "per_city": per_city}


def _metric_cards(names, graph=None) -> dict:
    """Definition + compiled SQL + value/rows per metric — the card every step shows."""
    import sqlgen
    from rdflib import RDFS
    g = graph if graph is not None else _tutorial6_graph(None)
    out = []
    import psycopg2 as _pg
    conn = _pg.connect(**_dsn())
    try:
        cur = conn.cursor()
        for name in names:
            try:
                c = sqlgen.compile_metric(g, name)
            except sqlgen.Refusal as exc:
                out.append({"name": name, "error": str(exc).splitlines()[0]})
                continue
            d = _metric_definition(g, name)
            run = guard.run(cur, c.sql, mode="declared")
            rows = run["rows"]
            card = {"name": name, "label": sqlgen._one(g, sqlgen.P(name), RDFS.label),
                    "sql": run["sql"], "compiled_sql": c.sql, "guard": _guard_report(run),
                    "definition": d, "notes": c.notes,
                    "tables": sorted({t for t in _tables_in(c.sql)})}
            if d.get("groupBy"):
                k = len(d["groupBy"])
                card["rows"] = [
                    {"keys": [str(v) for v in r[:k]],
                     "value": _fmt_value(r[-1], money=d.get("unit") == "money")}
                    for r in rows]
                card["value"] = None
            else:
                card["value"] = _fmt_value(rows[0][0], money=d.get("unit") == "money") if rows else "—"
                card["rows"] = []
            out.append(card)
    finally:
        conn.close()
    return {"ok": True, "metrics": out}


def tutorial7_metrics() -> dict:
    """Metrics that only exist because products joined the model: 2 and 4 table compiles."""
    return _metric_cards(STEP7_METRICS)


def tutorial8_metrics() -> dict:
    """Metrics whose value is a sum of orders but whose KEY is a dimension on Store."""
    return _metric_cards(STEP8_METRICS)


def _tables_in(sql: str) -> list[str]:
    """Which physical tables a compiled statement touches — the page counts them."""
    import re as _re
    names = set()
    for m in _re.finditer(r"\bFROM\s+([a-z_][a-z0-9_]*)|\bJOIN\s+([a-z_][a-z0-9_]*)",
                          sql, _re.I):
        names.add(m.group(1) or m.group(2))
    return sorted(names)


# ------------------------------------------------------------------ ABC 冷链 tutorial
def _abc_conn():
    import psycopg2 as _pg
    return _pg.connect(**_dsn())


def abct_vehicles() -> dict:
    conn = _abc_conn()
    try:
        cur = conn.cursor()
        g = guard.run(cur, "SELECT id, plate, tonnage::text, emission, age_years::text, "
                           "core_zone_permit::text, box_capacity, volume_capacity::text "
                           "FROM vehicles ORDER BY tonnage DESC, plate")
        cols, rows = g["cols"], [[str(v) for v in r] for r in g["rows"]]
    finally:
        conn.close()
    return {"ok": True, "cols": cols, "rows": rows, "guard": _guard_report(g),
            "schema": [{"column": "id", "type": "bigint", "note": "主键"},
                       {"column": "plate", "type": "text", "note": "车牌"},
                       {"column": "tonnage", "type": "numeric", "note": "吨位：能装多少"},
                       {"column": "emission", "type": "text", "note": "国四 / 国五 / 国六 / 新能源"},
                       {"column": "age_years", "type": "numeric", "note": "车龄"},
                       {"column": "core_zone_permit", "type": "boolean", "note": "核心城区通行证"},
                       {"column": "box_capacity", "type": "integer", "note": "可装箱数"},
                       {"column": "volume_capacity", "type": "numeric", "note": "容积 m³"}]}


def abct_trips() -> dict:
    conn = _abc_conn()
    try:
        cur = conn.cursor()
        g = guard.run(cur, "SELECT id, trip_date::text, vehicle_id, driver_id, "
                           "planned_stops, load_boxes FROM trips ORDER BY id")
        cols, rows = g["cols"], [[str(v) for v in r] for r in g["rows"]]
    finally:
        conn.close()
    return {"ok": True, "cols": cols, "rows": rows, "guard": _guard_report(g),
            "schema": [{"column": "id", "type": "bigint", "note": "主键"},
                       {"column": "trip_date", "type": "date", "note": "出车日期"},
                       {"column": "vehicle_id", "type": "bigint", "note": "FK → vehicles.id（这就是连接）"},
                       {"column": "driver_id", "type": "bigint", "note": "FK → drivers.id"},
                       {"column": "planned_stops", "type": "integer", "note": "本趟计划站点数"},
                       {"column": "load_boxes", "type": "integer", "note": "实际装箱数"}]}


def abct_stops() -> dict:
    conn = _abc_conn()
    try:
        cur = conn.cursor()
        g = guard.run(cur, "SELECT trip_id, seq, store_id, on_time::text, "
                           "temp_excursion::text, damaged_boxes, alarm_triggered::text "
                           "FROM stops ORDER BY id LIMIT 8")
        cols, rows = g["cols"], [[str(v) for v in r] for r in g["rows"]]
    finally:
        conn.close()
    return {"ok": True, "cols": cols, "rows": rows,
            "schema": [{"column": "on_time", "note": "是否在收货窗口内"},
                       {"column": "temp_excursion", "note": "在途温度是否越界（倒温）"},
                       {"column": "damaged_boxes", "note": "破损箱数"},
                       {"column": "alarm_triggered", "note": "是否误触安防警铃"},
                       {"column": "baskets_missing", "note": "退货筐未回收数"},
                       {"column": "handler_id", "note": "装卸工（空 = 司机自己搬）"}]}


ABCT_NAMED_SQL = {
    "vehicles_count": "SELECT count(*) AS vehicles FROM vehicles;",
    "vehicles_core_permit": "SELECT plate, tonnage::text, emission FROM vehicles "
                            "WHERE core_zone_permit ORDER BY tonnage DESC;",
    "vehicles_gb4": "SELECT plate, emission FROM vehicles WHERE emission = '国四' ORDER BY plate;",
    "vehicles_12t": "SELECT plate, tonnage::text FROM vehicles WHERE tonnage = 12 ORDER BY plate;",
    "vehicles_old": "SELECT plate, age_years::text FROM vehicles WHERE age_years > 10 "
                    "ORDER BY age_years DESC;",
    "trips_count": "SELECT count(*) AS trips FROM trips;",
    "trips_8t": "SELECT count(*) AS trips FROM trips t JOIN vehicles v ON v.id = t.vehicle_id "
                "WHERE v.tonnage = 8;",
    "trips_gb4": "SELECT count(*) AS trips FROM trips t JOIN vehicles v ON v.id = t.vehicle_id "
                 "WHERE v.emission = '国四';",
    "trips_per_vehicle": "SELECT v.plate, count(*) AS trips FROM trips t "
                         "JOIN vehicles v ON v.id = t.vehicle_id GROUP BY v.plate "
                         "ORDER BY 2 DESC LIMIT 10;",
    "trips_no_permit": "SELECT count(*) AS trips FROM trips t JOIN vehicles v "
                       "ON v.id = t.vehicle_id WHERE NOT v.core_zone_permit;",
}


def abct_named_sql(name: str) -> dict:
    """Run one of the named teaching statements. The client never sends SQL."""
    sql = ABCT_NAMED_SQL.get(name)
    if sql is None:
        return {"ok": False, "error": f"unknown statement {name!r}"}
    if not sql.lower().lstrip().startswith("select"):
        return {"ok": False, "error": "only SELECT is allowed here"}
    conn = _abc_conn()
    try:
        cur = conn.cursor()
        g = guard.run(cur, sql, mode="rows")
        return {"ok": True, "sql": sql, "cols": g["cols"],
                "rows": [[str(v) for v in r] for r in g["rows"]], "guard": _guard_report(g)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc).splitlines()[0][:200]}
    finally:
        conn.close()


def abct_sql(sql: str) -> dict:
    """Run ONE statement the page already wrote down (the step-1/2 teaching pages).

    The guard still applies: a page cannot ask for an unbounded scan by accident.
    """
    if not sql.lower().lstrip().startswith("select"):
        return {"ok": False, "error": "only SELECT is allowed here"}
    conn = _abc_conn()
    try:
        cur = conn.cursor()
        g = guard.run(cur, sql, mode="rows")
        return {"ok": True, "cols": g["cols"], "rows": [[str(v) for v in r] for r in g["rows"]],
                "guard": _guard_report(g)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc).splitlines()[0][:200]}
    finally:
        conn.close()


def abct_objects() -> dict:
    import sqlgen
    g = sqlgen.load()
    out = []
    for cls in ("Vehicle", "Driver", "Trip", "Stop", "Route", "Store", "Complaint", "Handler"):
        out.append({"name": cls,
                    "table": sqlgen._one(g, sqlgen.P(cls), sqlgen.P("physicalTable")),
                    "pk": sqlgen._one(g, sqlgen.P(cls), sqlgen.P("primaryKey"))})
    try:
        pred, _ = sqlgen.concept_predicate(g, "VehicleNoPermit")
    except sqlgen.Refusal as exc:
        pred = f"refused: {exc}"
    ttl = f"""# :VehicleNoPermit ≡ :Vehicle ⊓ (core_zone_permit = false)
:Vehicle a owl:Class ; :physicalTable "vehicles" ; :primaryKey "id" .
:core_zone_permit a owl:DatatypeProperty ; rdfs:domain :Vehicle .
:VehicleNoPermit
    owl:equivalentClass [ owl:intersectionOf ( :Vehicle
        [ a owl:Restriction ; owl:onProperty :core_zone_permit ; owl:hasValue false ] ) ] .

# 编译出的谓词 → {pred}"""
    return {"ok": True, "objects": out, "definition": ttl}


def abct_metrics() -> dict:
    import sqlgen
    g = sqlgen.load()
    names = ["trips", "stops", "overloadedTrips", "overloadRate", "onTimeRate",
             "complaintRate", "stopsPerTrip", "damagePer1kStops", "permitCoverage",
             "atRiskDrivers", "unjudgedComplaints"]
    out = []
    for n in names:
        d = _metric_definition(g, n)
        out.append({"name": n, "definition": " · ".join(
            x for x in [d.get("aggregate"), d.get("formula"), d.get("grain"),
                        d.get("where"), (":" + ",:".join(d["groupBy"])) if d.get("groupBy") else None,
                        (f":numerator {d['numerator']}/:{d['denominator']}"
                         if d.get("numerator") else None)] if x)})
    return {"ok": True, "metrics": out}


def abct_overload() -> dict:
    cols = [{"column": "load_boxes", "note": "实际装箱数（派遣时）"},
            {"column": "box_capacity_snapshot", "note": "那台车的额定箱数（派遣时冻结）"},
            {"column": "load_volume / volume_capacity_snapshot", "note": "容积维度"},
            {"column": "load_weight / weight_capacity_snapshot", "note": "重量维度"}]
    conn = _abc_conn()
    try:
        cur = conn.cursor()
        cur.execute("""SELECT id, load_boxes, box_capacity_snapshot,
                       round(100.0 * load_boxes / NULLIF(box_capacity_snapshot,0), 1)
                       FROM trips ORDER BY id LIMIT 6""")
        sample = [[str(v) for v in r] for r in cur.fetchall()]
    finally:
        conn.close()
    ttl = """# 超载 = 任一维度达到或超过派遣时冻结的装载能力
:OverloadedTrip a owl:Class ;
    :physicalPredicate "load_boxes >= box_capacity_snapshot * {pct}/100
                        OR load_volume >= volume_capacity_snapshot * {pct}/100
                        OR load_weight >= weight_capacity_snapshot * {pct}/100" ."""
    return {"ok": True, "cols": cols, "sample": sample, "definition": ttl}


def abct_overload_compile(pct: float = 100.0) -> dict:
    import sqlgen
    factor = pct / 100.0
    pred = (f"(load_boxes >= box_capacity_snapshot * {factor} "
            f"OR load_volume >= volume_capacity_snapshot * {factor} "
            f"OR load_weight >= weight_capacity_snapshot * {factor})")
    sql = f"SELECT count(*) FROM trips WHERE {pred};"
    conn = _abc_conn()
    try:
        cur = conn.cursor()
        g = guard.run(cur, sql, mode="declared")
        count = int(g["rows"][0][0])
        cur.execute("SELECT count(*) FROM trips")
        total = int(cur.fetchone()[0])
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc).splitlines()[0][:200]}
    finally:
        conn.close()
    return {"ok": True, "predicate": pred, "sql": sql, "count": count, "total": total,
            "rate": round(100.0 * count / max(total, 1), 1),
            "note": "阈值 {:.0f}% 只出现在本体这一处；改它，数字跟着变。".format(pct)}


def abct_versions() -> dict:
    conn = _abc_conn()
    try:
        cur = conn.cursor()
        cur.execute("""SELECT version, count(*) AS routes, sum(planned_stops) AS planned
                       FROM routes GROUP BY 1 ORDER BY 1""")
        versions = [{"version": r[0], "routes": int(r[1]), "planned": int(r[2])}
                    for r in cur.fetchall()]
        cur.execute("""
            SELECT r.version,
                   round(avg(s.n), 2) AS stops,
                   round(100.0 * avg(s.over), 1) AS overload,
                   round(100.0 * avg(s.ontime), 1) AS on_time
            FROM (SELECT t.id, t.route_id,
                         (SELECT count(*) FROM stops s WHERE s.trip_id = t.id) AS n,
                         CASE WHEN t.load_boxes >= t.box_capacity_snapshot
                              OR t.load_volume >= t.volume_capacity_snapshot
                              OR t.load_weight >= t.weight_capacity_snapshot THEN 1 ELSE 0 END AS over,
                         (SELECT avg(s2.on_time::int) FROM stops s2 WHERE s2.trip_id = t.id) AS ontime
                  FROM trips t) s
            JOIN routes r ON r.id = s.route_id
            GROUP BY r.version ORDER BY 1""")
        # json cannot serialise Decimal: the endpoints convert, the SQL stays exact
        compare = [{"version": r[0], "stops": float(r[1]) if r[1] is not None else 0,
                    "overload": float(r[2]) if r[2] is not None else 0,
                    "on_time": float(r[3]) if r[3] is not None else 0}
                   for r in cur.fetchall()]
    finally:
        conn.close()
    return {"ok": True, "versions": versions, "compare": compare}


def abct_audit() -> dict:
    code, data = actions_cli("audit", "--limit", "6")
    return data if isinstance(data, dict) else {"ok": False, "rows": []}


def abct_action(verb: str, name: str, params: dict, actor: str) -> dict:
    if verb == "reset":
        code, data = actions_cli("reset", "--action", name, "--params", json.dumps(params))
    elif verb == "check":
        code, data = actions_cli("check", "--action", name, "--params", json.dumps(params))
    else:
        code, data = actions_cli("run", "--action", name, "--params", json.dumps(params),
                                 "--actor", actor)
    return data if isinstance(data, dict) else {"ok": False, "error": "no output"}


def abct_ask(question: str) -> dict:
    """Resolve a training question: the NL layer first, then the profile's phrase table.

    The Chinese NL gap is real (the rules tokenise English camel-case), so a tutorial page
    must not depend on it. The table is explicit and small: the page can only answer what
    it lists — the same discipline as steps 1-2's fixed rules.
    """
    import sqlgen
    q = (question or "").strip()
    if not q:
        return {"ok": False, "refused": "问题为空"}
    aliases = (load_settings().get("ask_aliases") or {})
    hit = aliases.get(q)
    if hit is None:
        code, data = nl_cli(q, confirm=False)
        if isinstance(data, dict) and data.get("ok"):
            return data
        return {"ok": False, "refused": (data or {}).get("refused") or "这一页没有认出的问法"}
    g = sqlgen.load()
    try:
        if hit["kind"] == "metric":
            c = sqlgen.compile_metric(g, hit["name"])
        else:
            pred = sqlgen.concept_sql(g, hit["name"])
            base = sqlgen.concept_base_class(g, hit["name"]) or hit["name"]
            table = sqlgen.table_of(g, base)
            c = sqlgen.Compiled(hit["name"], f"SELECT count(*) FROM {table} WHERE {pred};", [])
    except (sqlgen.Refusal, actions.Refusal) as exc:
        return {"ok": False, "refused": str(exc).splitlines()[0]}
    conn = _abc_conn()
    try:
        cur = conn.cursor()
        run = guard.run(cur, c.sql, mode="declared")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "refused": str(exc).splitlines()[0][:200]}
    finally:
        conn.close()
    rows = run["rows"]
    grouped = " GROUP BY " in c.sql.upper()
    result = {"kind": hit["kind"], "name": hit["name"], "sql": run["sql"],
              "definition": _metric_definition(g, hit["name"]) if hit["kind"] == "metric" else None,
              "guard": _guard_report(run),
              "rows": ([{"keys": [str(x) for x in r[:-1]], "value": str(r[-1])} for r in rows]
                       if grouped else []),
              "value": None if grouped else (str(rows[0][0]) if rows else None)}
    if grouped:
        answer = f"{hit['name']} 按组拆分：" + " · ".join(
            "/".join(x["keys"]) + f": {x['value']}" for x in result["rows"][:8])
    else:
        answer = f"{hit['name']} = {result['value']}。编译 SQL：{run['sql']}"
    return {"ok": True, "question": q, "intent": hit, "result": result, "answer": answer,
            "answer_source": "profile phrase table (recognised phrasing)"}


def abct_tutorial_page(step: int, embed: bool) -> str:
    path = FEATURE / "profiles" / "abc" / "tutorial" / f"step{step}.html"
    html = path.read_text(encoding="utf-8")
    if embed:
        html = html.replace("</head>", "<style>body{padding-left:0!important}</style></head>", 1)
    return html


def _fmt_value(v, money: bool = False) -> str | None:
    """Digits the way an analyst reads them: 242.38, not 242.3750000000000000."""
    if v is None:
        return "—"      # an aggregate over an empty window is null, not zero
    from decimal import Decimal
    if isinstance(v, Decimal):
        q = v.quantize(Decimal("0.01"))
        if not money and q == q.to_integral_value() and v == v.to_integral_value():
            return f"{int(q):,}"
        return f"{q:,}"
    if isinstance(v, float):
        return f"{round(v, 2):,}"
    return str(v)


def tutorial6_metrics(days: int | None = None) -> dict:
    """Every metric card: definition fields, compiled SQL, live value."""
    import sqlgen
    from rdflib import RDFS
    g = _tutorial6_graph(days)
    out = []
    import psycopg2 as _pg
    window = None
    if days:
        # the window is real dates, not a number the user has to trust
        import datetime as dt
        since = _window_since(days)
        until = dt.datetime.now(dt.timezone.utc)
        window = {"days": int(days), "since": since.date().isoformat(),
                  "until": until.date().isoformat(), "since_ts": since.isoformat()}
    conn = _pg.connect(**_dsn())
    try:
        cur = conn.cursor()
        for name in STEP6_METRICS + (["revenueLastDays"] if days else []):
            try:
                c = sqlgen.compile_metric(g, name)
            except sqlgen.Refusal as exc:
                out.append({"name": name, "error": str(exc).splitlines()[0]})
                continue
            d = _metric_definition(g, name)
            run = guard.run(cur, c.sql, mode="declared")
            rows = run["rows"]
            label = sqlgen._one(g, sqlgen.P(name), RDFS.label)
            card = {"name": name, "label": label, "sql": run["sql"], "compiled_sql": c.sql,
                    "guard": _guard_report(run),
                    "value": _fmt_value(rows[0][0], money=d.get("unit") == "money")
                    if rows else None,
                    "definition": d, "notes": c.notes}
            if name == "revenueLastDays" and window:
                wg = guard.run(cur, "SELECT count(*) AS total, "
                                    "count(*) FILTER (WHERE placed_at >= %s) AS inside "
                                    "FROM orders", (window["since_ts"],), mode="declared")
                total, inside = wg["rows"][0]
                card["window"] = {k: v for k, v in window.items() if k != "since_ts"}
                card["window"].update(ordersInside=int(inside), ordersTotal=int(total))
                card["label"] = f"Revenue in the last {window['days']} days"
            out.append(card)
    finally:
        conn.close()
    return {"ok": True, "metrics": out, "window": window}


def tutorial6_compile(metric: str, formula: str, aggregate: str,
                      where: str | None) -> dict:
    import sqlgen
    g = _tutorial6_graph(metric=metric, formula=formula, aggregate=aggregate, where=where)
    try:
        c = sqlgen.compile_metric(g, metric)
    except sqlgen.Refusal as exc:
        return {"ok": False, "error": str(exc).splitlines()[0]}
    import psycopg2 as _pg
    conn = _pg.connect(**_dsn())
    try:
        cur = conn.cursor()
        cur.execute(c.sql)
        row = cur.fetchone()
    finally:
        conn.close()
    return {"ok": True, "sql": c.sql, "value": str(row[0]) if row else None,
            "definition": _metric_definition(g, metric)}


def _metric_definition(g, name: str) -> dict:
    import sqlgen
    P = sqlgen.P
    def one(field):
        return sqlgen._one(g, P(name), P(field))
    metas = sqlgen.metrics(g)
    m = metas.get(name)
    d = {"formula": one("formula"), "aggregate": one("aggregate"),
         "grain": sqlgen._local(one("grain")), "universe": sqlgen._local(one("universe")),
         "where": sqlgen._local(one("where")), "unit": one("unit"),
         "groupBy": [sqlgen._local(o) for o in g.objects(P(name), P("groupBy"))],
         "numerator": sqlgen._local(one("numerator")),
         "denominator": sqlgen._local(one("denominator"))}
    return d


def tutorial5_compile(gate: float | None = None) -> dict:
    """Compile the tutorial ontology's behaviour definition and run it (lane A).

    `gate` optionally REWRITES the axiom's minInclusive facet in memory before compiling,
    so the page can let a user change the threshold and watch the definition — not any SQL —
    change the answer.
    """
    try:
        import sqlgen
        from rdflib import Literal
        from rdflib.namespace import XSD
        sqlgen.reconfigure(ns="https://cube.local/ontology/retail#",
                           ontology_dir=str(PROFILE / "tutorial_ont"))
        g = sqlgen.load()
        used_gate = None
        if gate is not None:
            used_gate = float(gate)
            for subj, pred, obj in list(g.triples((None, XSD.minInclusive, None))):
                g.remove((subj, pred, obj))
                g.add((subj, pred, Literal(str(used_gate))))
        pred = sqlgen.concept_sql(g, "PremiumCustomer")
        sql = f"SELECT id, name FROM customers WHERE {pred} ORDER BY id;"
        import psycopg2 as _pg
        conn = _pg.connect(**_dsn())
        try:
            cur = conn.cursor()
            cur.execute(sql)
            cols = [d[0] for d in cur.description]
            rows = [[str(v) for v in r] for r in cur.fetchall()]
        finally:
            conn.close()
        ttl = (PROFILE / "tutorial_ont" / "premium_by_orders.ttl").read_text(encoding="utf-8")
        return {"ok": True, "predicate": pred, "sql": sql, "cols": cols, "rows": rows,
                "ttl": ttl, "gate": used_gate}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def nl_backlog() -> dict:
    """Run nl.py --backlog (same venv as the NL layer)."""
    env = dict(os.environ, LANGCHAIN_TRACING_V2="false", LANGSMITH_TRACING="false",
               LANGSMITH_TRACING_V2="false", LANGCHAIN_TRACING="false")
    try:
        p = subprocess.run([NL_PYTHON, str(COMPILER / "nl.py"), "--backlog"],
                           capture_output=True, text=True, timeout=60,
                           cwd=str(BASE), env=env)
        txt = p.stdout.strip()
        return json.loads(txt) if txt else {"ok": False, "error": (p.stderr or "no output")[-400:]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"nl.py --backlog failed: {exc}"}


def metric_import_cli(payload: dict, timeout=180) -> tuple[int, dict]:
    """Run metric_import.py in the venv that has rdflib + psycopg2.

    The server itself is stdlib-only, so the compiler lives in the child — the same
    interpreter that regenerates the page. The child prints one JSON object and exits
    non-zero when it refused something; a refusal is a result, so it is passed through
    exactly as printed.
    """
    import tempfile

    mode = (payload.get("mode") or "").strip()
    if mode not in ("nl", "upload"):
        return 1, {"ok": False, "refused": [{"name": "(request)",
                                             "why": "mode must be 'nl' or 'upload'"}]}
    env = dict(os.environ, LANGCHAIN_TRACING_V2="false", LANGSMITH_TRACING="false",
               LANGSMITH_TRACING_V2="false", LANGCHAIN_TRACING="false")
    nlset = (load_settings().get("nl") or {})
    env["NL_BACKEND"] = (nlset.get("backend") or "auto").lower()
    model = (nlset.get("model") or "").strip()
    if model:
        env["DEEPSEEK_MODEL" if env["NL_BACKEND"] == "deepseek" else "OLLAMA_MODEL"] = model

    args = [PYTHON, str(COMPILER / "metric_import.py"), "--profile", str(SETTINGS), "--mode", mode]
    if mode == "nl":
        args += ["--text", (payload.get("text") or "").strip()]
    else:
        content = payload.get("content") or ""
        name = (payload.get("filename") or "upload.csv").replace("/", "_")
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="metric-import-")) / name
        tmp.write_text(content, encoding="utf-8")
        args += ["--file", str(tmp)]
    if payload.get("dry_run"):
        args.append("--dry-run")
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                           cwd=str(BASE), env=env)
    except Exception as exc:                                   # noqa: BLE001
        return 1, {"ok": False, "refused": [{"name": "(runner)",
                                             "why": f"{type(exc).__name__}: {exc}"}]}
    try:
        data = json.loads((p.stdout or "").strip().splitlines()[-1])
    except Exception:                                          # noqa: BLE001
        return p.returncode, {"ok": False, "refused": [{
            "name": "(runner)", "why": "metric_import.py printed no JSON: "
            + ((p.stderr or p.stdout or "")[-800:])}]}
    return p.returncode, data


def nl_cli(question: str, timeout=90, confirm: bool = False) -> tuple[int, dict | list | None]:
    """Run nl.py under the venv that has psycopg2 + rdflib + langchain_openai."""
    try:
        env = dict(os.environ, LANGCHAIN_TRACING_V2="false", LANGSMITH_TRACING="false",
                   LANGSMITH_TRACING_V2="false", LANGCHAIN_TRACING="false")
        env["APP_SETTINGS"] = str(SETTINGS)      # the child compiles the SAME profile
        prof = load_settings()
        env["APP_ACTIONS"] = str((PROFILE / prof["actions_file"]).resolve()) \
            if prof.get("actions_file") else ""
        nlset = (load_settings().get("nl") or {})
        env["NL_BACKEND"] = (nlset.get("backend") or "auto").lower()
        model = (nlset.get("model") or "").strip()
        if model and env["NL_BACKEND"] == "deepseek":
            env["DEEPSEEK_MODEL"] = model
        elif model and env["NL_BACKEND"] == "ollama":
            env["OLLAMA_MODEL"] = model
        elif model:
            env["OLLAMA_MODEL"] = model          # auto: the model name is an Ollama one
        env["NL_ANSWER_LLM"] = "1" if nlset.get("answer_llm") else "0"
        args = [NL_PYTHON, str(COMPILER / "nl.py"), question]
        if confirm:
            args.append("--confirm")
        p = subprocess.run(args,
                           capture_output=True, text=True, timeout=timeout,
                           cwd=str(BASE), env=env)
        txt = p.stdout.strip()
        if not txt:
            return p.returncode, {"ok": False,
                                  "refused": ("nl.py produced no output: "
                                              + (p.stderr or "no stderr")[-600:])}
        try:
            return p.returncode, json.loads(txt)
        except json.JSONDecodeError:
            return p.returncode, {"ok": False,
                                  "refused": ("nl.py returned non-JSON: "
                                              + (txt or p.stderr or "no output")[-600:])}
    except Exception as exc:  # noqa: BLE001
        return 1, {"ok": False, "refused": f"nl.py failed: {exc}"}


def declared_actions_file(prof: dict | None = None) -> pathlib.Path | None:
    """The actions declaration of the ACTIVE profile, or None when it declares no write verbs.

    Resolution is the profile's, not the code's: `actions_file` when the profile names one, otherwise
    the `schema/actions.yml` that sits in the profile's own directory (retail and abc declare their
    verbs that way). It NEVER falls back to another ontology's file — that fallback is how retail's
    PromoteCustomer ended up being compiled against clinic's graph, returned as a 500 for an ontology
    that simply has no writes.
    """
    prof = prof if prof is not None else load_settings()
    raw = (prof.get("actions_file") or "").strip()
    if raw:
        p = pathlib.Path(raw)
        return (SETTINGS.parent / p).resolve() if not p.is_absolute() else p
    conventional = SETTINGS.parent / "schema" / "actions.yml"
    return conventional.resolve() if conventional.is_file() else None


def actions_cli(*args, timeout=120) -> tuple[int, dict | list | None]:
    """Run retail_graph/actions.py (psycopg2 + rdflib + pyyaml live in the cube venv)."""
    try:
        env = dict(os.environ, APP_SETTINGS=str(SETTINGS))
        declared = declared_actions_file()
        env["APP_ACTIONS"] = str(declared) if declared else ""
        p = subprocess.run([PYTHON, str(COMPILER / "actions.py"), *args],
                           capture_output=True, text=True, timeout=timeout, env=env)
        txt = p.stdout.strip()
        try:
            return p.returncode, json.loads(txt) if txt else None
        except json.JSONDecodeError:
            return p.returncode, {"error": (p.stderr or txt or "no output")[-600:]}
    except Exception as exc:  # noqa: BLE001
        return 1, {"error": f"actions.py failed: {exc}"}


def run_lane_b(s: dict) -> dict:
    """Lane B numbers (SPARQL/Ontop) for the comparison page and the save log."""
    cmd = [PYTHON, str(COMPILER / "lane_b.py"),
           "--endpoint", s["ontop_endpoint"],
           "--ontop-ns", s["ontop_ns"],
           "--sample", str(s["sample"])]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        lines = [ln for ln in p.stdout.splitlines() if ln.strip().startswith("{")]
        if not lines:
            return {"ok": False, "note": (p.stderr or "no output")[-400:], "rows": []}
        return json.loads(lines[-1])
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "note": f"lane B failed: {exc}", "rows": []}


def run_sparql(s: dict, query_text: str) -> dict:
    """POST a SPARQL query to lane B's endpoint and shape the result for the UI."""
    body = urllib.parse.urlencode({"query": query_text}).encode()
    req = urllib.request.Request(
        s["ontop_endpoint"], data=body,
        headers={"Accept": "application/sparql-results+json",
                 "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            j = json.load(r)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"endpoint {s['ontop_endpoint']}: {exc}"}

    if "boolean" in j:
        return {"ok": True, "boolean": j["boolean"], "vars": [], "rows": []}
    vars_ = j.get("head", {}).get("vars", [])
    rows = []
    for b in j.get("results", {}).get("bindings", [])[:300]:
        rows.append({var: (b[var].get("value") if var in b else None) for var in vars_})
    total = len(j.get("results", {}).get("bindings", []))
    return {"ok": True, "vars": vars_, "rows": rows, "total": total}


def run_dl_demo() -> dict:
    """Run query_reasoner.py (HermiT, before/after) and return its log."""
    try:
        p = subprocess.run([DL_PYTHON, DL_SCRIPT], capture_output=True,
                           text=True, timeout=180)
        log = (p.stdout or "") + (p.stderr or "")
        return {"ok": p.returncode == 0, "log": log[-4000:]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "log": f"DL demo failed: {exc}"}


def comparison_text(lanes: dict) -> str:
    if not lanes.get("ok"):
        return f"lane B unavailable: {lanes.get('note')}"
    parts = []
    for row in lanes.get("rows", []):
        b = row.get("laneB")
        b_txt = "—" if b is None else str(b)
        verdict = "=" if row.get("match") is True else ("≠" if row.get("match") is False else "—")
        parts.append(f"{row['name']} A={row['laneA']} B={b_txt} {verdict}")
    return "  lane A vs lane B:  " + "  ·  ".join(parts)


def compare_html(s: dict, lanes: dict) -> str:
    rows = []
    for row in lanes.get("rows", []):
        b = row.get("laneB")
        b_txt = "—" if b is None else str(b)
        if row.get("match") is True:
            badge = '<span style="color:#1d7a3a">✓ match</span>'
        elif row.get("match") is False:
            badge = '<span style="color:#b3261e">✗ mismatch</span>'
        elif not row.get("served"):
            badge = '<span style="color:#687b8f">not served by the mapping</span>'
        else:
            badge = "—"
        rows.append(
            f"<tr><td style='padding:8px 10px;font-weight:600'>{row['name']}</td>"
            f"<td style='padding:8px 10px;font-family:ui-monospace,Menlo,monospace'>{row['laneA']}</td>"
            f"<td style='padding:8px 10px;font-family:ui-monospace,Menlo,monospace'>{b_txt}</td>"
            f"<td style='padding:8px 10px'>{badge}</td></tr>")
    note = lanes.get("note") or ""
    err = "" if lanes.get("ok") else (
        f"<p style='color:#b3261e;font-size:13px'>lane B error: {lanes.get('note')}</p>")
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Compare lanes — ontology app</title>
<style>
  body {{ font-family:-apple-system,"Segoe UI",Roboto,sans-serif; background:#f6f7f9; margin:0; color:#1c1e21; }}
  header {{ background:#102a43; color:#fff; padding:18px 26px; }}
  header h1 {{ margin:0; font-size:17px; }}
  header a {{ color:#9fb8cf; font-size:13px; }}
  main {{ max-width:860px; margin:20px auto; padding:0 20px; }}
  .card {{ background:#fff; border:1px solid #e3e6ea; border-radius:10px; padding:18px 20px; margin-bottom:16px; }}
  table {{ width:100%; border-collapse:collapse; font-size:14px; }}
  th {{ text-align:left; font-size:12px; text-transform:uppercase; letter-spacing:.4px; color:#687b8f;
        padding:6px 10px; border-bottom:1px solid #e3e6ea; }}
  td {{ border-bottom:1px solid #f0f2f5; }}
  .muted {{ color:#687b8f; font-size:13px; }}
  a.btn {{ display:inline-block; margin-top:8px; background:#0b4f9c; color:#fff; text-decoration:none;
           padding:8px 14px; border-radius:8px; font-size:13px; }}
</style></head>
<body>
<header><h1>⚖ Two approaches, one question</h1>
  <a href="/">← back to the app</a> · <a href="/reasoner">⌨ reasoner</a> · <a href="/query">query ✦</a> · <a href="/settings">settings</a></header>
<main>
  <div class="card">
    <p class="muted">Lane A compiles the TTL axiom into SQL once (<code>:PremiumCustomer owl:equivalentClass …</code>
    → <code>WHERE tier = 'PREMIUM'</code>) and runs it on the source database. Lane B asks SPARQL against
    <code>{s['ontop_endpoint']}</code> (Ontop: virtual RDF graph + R2RML mapping, OWL 2 QL entailment).</p>
    {err}
    <table>
      <tr><th>class</th><th>lane A · compiled SQL</th><th>lane B · SPARQL + Ontop</th><th>verdict</th></tr>
      {''.join(rows)}
    </table>
    <p class="muted">{note}</p>
    <a class="btn" href="/">open the app (lane A view)</a>
    <a class="btn" href="/reasoner" style="background:#334e68">open the reasoner</a>
  </div>
  <div class="card">
    <p class="muted" style="margin:0">Both lanes read the same rows and neither materializes a copy:
    an UPDATE on the source table changes both answers on the next query. Beyond OWL 2 QL
    (e.g. <code>owl:hasValue</code>) lane B cannot answer at all — the setting
    <code>lane = b</code> records which projection the app is currently on.</p>
  </div>
</main></body></html>"""


def ontology_api() -> dict:
    """The loaded ontology as JSON — objects, definitions, links, metrics (+ compiled SQL).

    Delegated to the interpreter with rdflib, exactly like the metric import: the server
    stays stdlib-only, and there is one implementation of "what is declared".
    """
    try:
        p = subprocess.run([PYTHON, str(COMPILER / "ontology_api.py"), "--profile", str(SETTINGS)],
                           capture_output=True, text=True, timeout=180, cwd=str(BASE),
                           env=dict(os.environ))
        return json.loads((p.stdout or "").strip().splitlines()[-1])
    except Exception as exc:                                   # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _tutorial_cli(*args: str, timeout: int = 180) -> dict:
    """Run tutorial_api.py under the interpreter that has rdflib + psycopg2.

    The server itself is stdlib-only (it also runs under a plain `python3`), so anything that
    reads the ontology graph has to happen in the child — same rule as ontology_api and the
    metric import.
    """
    try:
        p = subprocess.run([PYTHON, str(COMPILER / "tutorial_api.py"), "--profile", str(SETTINGS),
                            *args],
                           capture_output=True, text=True, timeout=timeout, cwd=str(BASE),
                           env=dict(os.environ))
        return json.loads((p.stdout or "").strip().splitlines()[-1])
    except Exception as exc:                                   # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def tutorial_data() -> dict:
    return _tutorial_cli("--mode", "steps")


def tutorial_run(name: str) -> dict:
    if not name:
        return {"ok": False, "error": "metric is required"}
    return _tutorial_cli("--mode", "run", "--metric", name)


def tutorial_definition(name: str) -> dict:
    if not name:
        return {"ok": False, "error": "class is required"}
    return _tutorial_cli("--mode", "definition", "--class", name)


def metrics_import_state() -> dict:
    """The page's read-only view, from the child that has rdflib: declared metrics only.

    The server is stdlib-only, so it does not parse the ontology itself — asking the
    same CLI that will do the import keeps one implementation of "what is declared".
    """
    try:
        p = subprocess.run([PYTHON, str(COMPILER / "metric_import.py"), "--profile", str(SETTINGS),
                            "--mode", "state"],
                           capture_output=True, text=True, timeout=120, cwd=str(BASE),
                           env=dict(os.environ))
        data = json.loads((p.stdout or "").strip().splitlines()[-1])
        data.setdefault("profile", SETTINGS.name)
        return data
    except Exception as exc:                                   # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "metrics": []}


class Handler(BaseHTTPRequestHandler):
    server_version = "OntologyAppUI/1.2"

    # ---- helpers ----
    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        # The workbench is meant to be EMBEDDED (the LangConfig UI opens it as an app), and
        # the host page can only check liveness with fetch() — which is blocked without
        # CORS. Everything here is read-only JSON on localhost; the SQL guardrails, not the
        # browser, are what protects the database.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802 — CORS preflight for the embedder
        self._send(204, b"", "text/plain")

    def _json(self, obj, status: int = 200) -> None:
        self._send(status, json.dumps(obj).encode(), "application/json")

    def _app_page(self) -> None:
        s = load_settings()
        page = app_html(s)
        if not page.exists():
            ok, log = regenerate(s)
            if not ok:
                return self._json({"ok": False, "log": log}, 500)
        html = page.read_text(encoding="utf-8")
        lang = self._lang()
        body = i18n.render(self._present(html, "/", self._embed()), lang or None)
        self._send(200, body.encode(), "text/html; charset=utf-8")

    def _query(self) -> dict:
        raw = self.path.split("?", 1)[1] if "?" in self.path else ""
        out: dict[str, str] = {}
        for part in raw.split("&"):
            if "=" in part:
                k, v = part.split("=", 1)
                out[urllib.parse.unquote(k)] = urllib.parse.unquote(v)
        return out

    def _embed(self) -> bool:
        return self._query().get("embed") in ("1", "true", "yes")

    def _theme(self) -> str:
        """dark/light, supplied by the embedding app so the workbench matches it."""
        theme = (self._query().get("theme") or "").lower()
        return theme if theme in ("dark", "light") else ""

    def _lang(self) -> str:
        lang = (self._query().get("lang") or "").lower()
        return lang if lang in {code for code, _ in i18n.LANGS} else ""

    def _present(self, html: str, active: str, embed: bool) -> str:
        """Wrap a page for the context it is shown in.

        `embed=1` means "you are inside another app's frame": the workbench's own browser
        (the icon rail `#sbnav` and the documentation index `#index`) is dropped, because the
        host app already lists ontologies and their sections. `theme=dark` re-skins the main
        surfaces so the frame does not flash a white page inside a dark shell.
        """
        extra = ""
        if embed:
            # Only the app's own rail goes: the host app already lists the ontologies and
            # their sections. The documentation index (#index: classes + data properties) and
            # the detail panel (#panel) are the page's own content — an embedded ontology with
            # no list of entities is the graph without the thing that explains it.
            extra += ("<style>"
                      "#sbnav{display:none!important}"
                      "body{padding-left:0!important}"
                      "</style>")
        if self._theme() == "dark":
            extra += ("<style>:root{--ink:#e6e8eb;--dim:#9aa4af;--faint:#7b8794;"
                      "--line:#39424e;--pick:#3d3venue}"
                      "html,body{background:#15181d!important;color:var(--ink)}"
                      "#index,#panel,#bar,#controls,#hint{background:#1b1f26!important;"
                      "color:var(--ink);border-color:#2a3039!important}"
                      "#index a{color:var(--ink)}#index a:hover{background:#222833}"
                      "#index .head,#index .grp{color:var(--dim);border-color:#232a33}"
                      "pre,code,.mono{background:#11151a;color:#dbe7f3}"
                      "table,th,td{border-color:#2a3039}"
                      "svg text{fill:#dbe7f3}"
                      "</style>").replace("#3d3venue", "#3d3220")
        if extra:
            html = html.replace("</head>", extra + "</head>", 1)
        if embed:
            return html
        return inject_nav(html, active)

    def _page(self, filename: str, active: str, embed: bool = False) -> None:
        html = (BASE / filename).read_text(encoding="utf-8")
        lang = self._lang()
        self._send(200, i18n.render(self._present(html, active, embed or self._embed()), lang or None)
                   .encode(), "text/html; charset=utf-8")

    def _compare_page(self) -> None:
        s = load_settings()
        lanes = run_lane_b(s)
        self._send(200, i18n.render(self._present(compare_html(s, lanes), "/compare",
                                                  self._embed())).encode(),
                   "text/html; charset=utf-8")

    # ---- routes ----
    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        feat = FEATURE_OF.get(path)
        if feat and not _features().get(feat, True):
            return self._json({"ok": False, "error": f"{path} is not part of this profile"}, 404)
        if path in ("/", "/ontology.html"):
            self._app_page()
        elif path == "/compare":
            self._compare_page()
        elif path == "/tutorial":
            # A profile that ships its own eight-step tutorial keeps it (retail's walks
            # retail concepts). Everything else gets the generated tutorial: the objects,
            # definitions, metrics and refusals of THIS ontology, with the numbers run live.
            if _tutorial_style() == "authored":
                self._page("tutorial.html", "/tutorial")
            else:
                self._page("tutorial_auto.html", "/tutorial", embed=self._embed())
        elif path == "/tutorial/1":
            self._page("tutorial1.html", "/tutorial", embed=self._embed())
        elif path == "/tutorial/2":
            self._page("tutorial2.html", "/tutorial", embed=self._embed())
        elif path == "/api/tutorial2/table":
            self._json(tutorial2_table())
        elif path == "/tutorial/3":
            self._page("tutorial3.html", "/tutorial", embed=self._embed())
        elif path == "/tutorial/4":
            self._page("tutorial4.html", "/tutorial", embed=self._embed())
        elif path == "/tutorial/5":
            self._page("tutorial5.html", "/tutorial", embed=self._embed())
        elif path == "/tutorial/6":
            self._page("tutorial6.html", "/tutorial", embed=self._embed())
        elif path == "/tutorial/7":
            self._page("tutorial7.html", "/tutorial", embed=self._embed())
        elif path == "/api/tutorial7/tables":
            self._json(tutorial7_tables())
        elif path == "/api/tutorial7/metrics":
            self._json(tutorial7_metrics())
        elif path == "/tutorial/8":
            self._page("tutorial8.html", "/tutorial", embed=self._embed())
        elif path == "/api/tutorial8/tables":
            self._json(tutorial8_tables())
        elif path == "/api/tutorial8/metrics":
            self._json(tutorial8_metrics())
        elif path == "/api/tutorial5/compile":
            gate = None
            if "?" in self.path:
                from urllib.parse import parse_qs
                q = parse_qs(self.path.split("?", 1)[1])
                try:
                    gate = float((q.get("gate") or [""])[0])
                except ValueError:
                    gate = None
            self._json(tutorial5_compile(gate))
        elif path.startswith("/api/tutorial6/metrics"):
            days = None
            if "?" in self.path:
                from urllib.parse import parse_qs
                q = parse_qs(self.path.split("?", 1)[1])
                try:
                    days = int((q.get("days") or ["30"])[0])
                except ValueError:
                    days = 30
            self._json(tutorial6_metrics(days))
        elif path.startswith("/api/graph"):
            step = 1
            if "?" in self.path:
                from urllib.parse import parse_qs
                q = parse_qs(self.path.split("?", 1)[1])
                try:
                    step = int((q.get("step") or ["1"])[0])
                except ValueError:
                    step = 1
            self._json(tutorial_graph(step))
        elif path.startswith("/api/tutorial5/reason"):
            mode, cid = "stored", 2
            if "?" in self.path:
                from urllib.parse import parse_qs
                q = parse_qs(self.path.split("?", 1)[1])
                mode = (q.get("mode") or ["stored"])[0]
                try:
                    cid = int((q.get("customer_id") or ["2"])[0])
                except ValueError:
                    cid = 2
            self._json(tutorial5_reason(mode, cid))
        elif path == "/api/tutorial4/table":
            self._json(tutorial3_table())
        elif path == "/api/tutorial3/objects":
            self._json(tutorial3_objects())
        elif path == "/api/tutorial3/table":
            self._json(tutorial3_table())
        elif path == "/abctutorial":
            self._send(200, i18n.render(
                (FEATURE / "profiles" / "abc" / "tutorial" / "shell.html").read_text(encoding="utf-8")
            ).encode(), "text/html; charset=utf-8")
        elif path.startswith("/abctutorial/"):
            try:
                step = int(path.rsplit("/", 1)[1])
            except ValueError:
                step = 1
            q = self.path.split("?", 1)[1] if "?" in self.path else ""
            self._send(200, abct_tutorial_page(step, "embed=1" in q).encode(),
                       "text/html; charset=utf-8")
        elif path == "/api/abct/vehicles":
            self._json(abct_vehicles())
        elif path == "/api/abct/trips":
            self._json(abct_trips())
        elif path == "/api/abct/stops":
            self._json(abct_stops())
        elif path == "/api/abct/objects":
            self._json(abct_objects())
        elif path == "/api/abct/metrics":
            self._json(abct_metrics())
        elif path == "/api/abct/overload":
            self._json(abct_overload())
        elif path.startswith("/api/abct/overload/compile"):
            pct = 100.0
            if "?" in self.path:
                from urllib.parse import parse_qs
                q = parse_qs(self.path.split("?", 1)[1])
                try:
                    pct = float((q.get("pct") or ["100"])[0])
                except ValueError:
                    pct = 100.0
            self._json(abct_overload_compile(pct))
        elif path == "/api/abct/versions":
            self._json(abct_versions())
        elif path == "/api/abct/audit":
            self._json(abct_audit())
        elif path == "/api/tutorial1/table":
            self._json(tutorial1_table())
        elif path == "/query":
            self._page("nl.html", "/query")
        elif path == "/backlog":
            self._page("backlog.html", "/backlog")
        elif path == "/design":
            svg = (BASE / "architecture.svg").read_text(encoding="utf-8")
            page = ("<!DOCTYPE html><html><head><meta charset='utf-8'>"
                    "<title>Architecture — ontology app</title>"
                    "<style>body{margin:0;background:#f6f7f9;font-family:-apple-system,Segoe UI,Roboto,sans-serif}"
                    "main{max-width:1400px;margin:18px auto;padding:0 16px}"
                    "h1{font-size:17px;color:#102a43;margin:6px 0 2px}"
                    "p{color:#687b8f;font-size:13px;margin:0 0 14px}"
                    "a{color:#0b4f9c}</style></head><body>"
                    "<main><h1>retail_graph — ontology architecture</h1>"
                    "<p><a href='/'>← back to the app</a> · generated by make_architecture_svg.py"
                    " · the full text is in ARCHITECTURE.md</p>" + svg + "</main></body></html>")
            self._send(200, i18n.render(self._present(page, "/design", self._embed())).encode(),
                       "text/html; charset=utf-8")
        elif path == "/architecture.svg":
            self._send(200, (BASE / "architecture.svg").read_bytes(), "image/svg+xml")
        elif path == "/tutorial_graph.js":
            self._send(200, (BASE / "tutorial_graph.js").read_bytes(),
                       "application/javascript; charset=utf-8")
        elif path == "/api/metrics/cards":
            # every metric as a card (declaration, compiled SQL, number, guard report) — the
            # shape the workbench's own metric grid uses
            return self._json(_tutorial_cli("--mode", "cards", timeout=240))
        elif path == "/api/tutorial/steps":
            return self._json(tutorial_data())
        elif path == "/api/tutorial/run":
            name = (urllib.parse.parse_qs(self.path.split("?", 1)[1]).get("metric") or [""])[0]
            return self._json(tutorial_run(name))
        elif path == "/api/tutorial/definition":
            name = (urllib.parse.parse_qs(self.path.split("?", 1)[1]).get("class") or [""])[0]
            return self._json(tutorial_definition(name))
        elif path == "/api/sections":
            feats = _features()
            # A section that is switched off in the profile must not be advertised: an
            # embedder that lists it sends the user to a 404 inside a frame.
            rows = [
                # "Graph view", not "Overview": the page IS the generated graph + documentation from the
                # TTL (graph_view.py), and calling it Overview implied a summary this profile does not have.
                # The KEY stays `home` so existing `?view=home` links and bookmarks keep working.
                {"key": "home", "label": "Graph view", "path": "/", "enabled": True,
                 "hint": "the graph and the documentation generated from this profile's TTL, with live numbers"},
                {"key": "query", "label": "Query", "path": "/query", "enabled": True,
                 "hint": "ask in your own words; rules first, model only when unsure"},
                {"key": "actions", "label": "Actions", "path": "/actions",
                 "enabled": bool(feats.get("actions", True)),
                 "hint": "declared writes: compiled preconditions, dry-run, audit"},
                {"key": "design", "label": "Design", "path": "/design", "enabled": True,
                 "hint": "the architecture of this ontology: two lanes, one question"},
                {"key": "tutorial", "label": "Tutorial", "path": "/tutorial",
                 "enabled": bool(feats.get("tutorial", True)),
                 "hint": "a guided walk through the axioms and their numbers"},
            ]
            return self._json({"ok": True, "profile": SETTINGS.name,
                               "features": feats, "sections": rows})
        elif path == "/api/ontology":
            return self._json(ontology_api())
        elif path == "/api/metrics/import":
            return self._json(metrics_import_state())
        elif path == "/reasoner":
            self._page("ask.html", "/reasoner")
        elif path == "/settings":
            self._page("settings.html", "/settings")
        elif path == "/api/samples":
            self._json({"ok": True, "samples": load_settings().get("samples") or []})
        elif path == "/api/i18n":
            lang = i18n.current()
            if "?" in self.path:
                from urllib.parse import parse_qs
                q = parse_qs(self.path.split("?", 1)[1])
                lang = (q.get("lang") or [lang])[0]
            self._json({"ok": True, "lang": lang, "langs": i18n.LANGS,
                        "phrases": i18n.PHRASES.get(lang, {})})
        elif path == "/i18n.js":
            self._send(200, i18n.CLIENT_JS.encode(),
                       "application/javascript; charset=utf-8")
        elif path == "/api/settings":
            self._json(load_settings())
        elif path == "/api/nl/config":
            self._json(nl_config())
        elif path == "/api/nl/backlog":
            self._json(nl_backlog())
        elif path == "/api/lanes":
            self._json(run_lane_b(load_settings()))
        elif path == "/actions":
            self._page("actions.html", "/actions")
        elif path == "/api/actions":
            # A profile that declares no write verbs (features.actions false, or no actions_file) has an
            # EMPTY verb list — that is a fact about this ontology, not a server error. Without this guard
            # the compiler fell back to retail's declarations and tried to compile PromoteCustomer against
            # this ontology's graph: "cannot compile action declarations: :Customer has no :physicalTable",
            # returned as a 500 for a profile that simply has no writes.
            if declared_actions_file() is None:
                return self._json({"ok": True, "actions": [],
                                   "note": "this ontology declares no write verbs (no actions file)"})
            code, data = actions_cli("list")
            if code != 0:
                return self._json({"ok": False, "error": data}, 500)
            self._json({"ok": True, "actions": data})
        elif path == "/api/actions/audit":
            code, data = actions_cli("audit")
            if code != 0:
                return self._json({"ok": False, "error": data}, 500)
            self._json({"ok": True, "rows": data})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return self._json({"ok": False, "error": "invalid JSON"}, 400)

        if path == "/api/metrics/import":
            code, data = metric_import_cli(payload)
            if code == 0 and data.get("ok") and not payload.get("dry_run"):
                # the read page embeds its numbers at build time: rebuild it so a newly
                # imported metric shows up on the menu without a manual restart
                threading.Thread(target=regenerate, args=(load_settings(),),
                                 daemon=True).start()
            return self._json(data, 200 if code == 0 else 400)

        if path == "/api/tutorial8/ask":
            q = (payload.get("question") or "").strip()
            return self._json(tutorial6_ask(q, None))

        if path == "/api/abct/query":
            return self._json(abct_named_sql((payload.get("name") or "").strip()))
        if path == "/api/abct/ask":
            return self._json(abct_ask((payload.get("question") or "").strip()))
        if path.startswith("/api/abct/action/"):
            verb = path.rsplit("/", 1)[1]
            return self._json(abct_action(verb, (payload.get("name") or "").strip(),
                                          payload.get("params") or {},
                                          (payload.get("actor") or "training").strip()))
        if path == "/api/tutorial7/ask":
            q = (payload.get("question") or "").strip()
            return self._json(tutorial6_ask(q, None))

        if path == "/api/tutorial6/ask":
            q = (payload.get("question") or "").strip()
            try:
                days = int(payload.get("days") or 30)
            except (TypeError, ValueError):
                days = 30
            return self._json(tutorial6_ask(q, days))

        if path == "/api/tutorial6/compile":
            metric = (payload.get("metric") or "").strip()
            formula = (payload.get("formula") or "").strip()
            aggregate = (payload.get("aggregate") or "").strip()
            where = (payload.get("where") or "").strip() or None
            if not metric or not formula or not aggregate:
                return self._json({"ok": False,
                                   "error": "metric, formula, aggregate are required"}, 400)
            return self._json(tutorial6_compile(metric, formula, aggregate, where))

        if path == "/api/ask":
            q = (payload.get("query") or "").strip()
            if not q:
                return self._json({"ok": False, "error": "empty query"}, 400)
            return self._json(run_sparql(load_settings(), q))
        if path == "/api/actions/run":
            name = (payload.get("name") or "").strip()
            actor = (payload.get("actor") or "web").strip()
            params = payload.get("params") or {}
            if not name:
                return self._json({"ok": False, "error": "name is required"}, 400)
            code, data = actions_cli("run", "--action", name,
                                     "--params", json.dumps(params),
                                     "--actor", actor)
            if code == 0:
                # the read page embeds numbers generated at build time: refresh it in the
                # background so the write shows up on / a few seconds later, without making
                # the action call itself wait for a full graph_view run.
                threading.Thread(target=regenerate, args=(load_settings(),),
                                 daemon=True).start()
            self._json(data, 200 if code in (0, 2) else 500)
        if path == "/api/dl":
            return self._json(run_dl_demo())
        if path == "/api/nl/config":
            return self._json(nl_config())
        if path == "/api/tutorial3":
            q = (payload.get("question") or "").strip()
            return self._json(run_tutorial3(q), 200)
        if path == "/api/tutorial2":
            q = (payload.get("question") or "").strip()
            return self._json(run_tutorial2(q), 200)
        if path == "/api/tutorial1":
            q = (payload.get("question") or "").strip()
            return self._json(run_tutorial1(q), 200)
        if path == "/api/nl":
            q = (payload.get("question") or "").strip()
            if not q:
                return self._json({"ok": False, "refused": "empty question"}, 400)
            code, data = nl_cli(q, confirm=bool(payload.get("confirm")))
            if not isinstance(data, dict):
                return self._json({"ok": False,
                                   "refused": f"nl.py gave no result (exit {code})"}, 500)
            return self._json(data, 200 if code in (0, 2) else 500)
        if path == "/api/guard":
            gname = (payload.get("name") or "").strip()
            gparams = payload.get("params") or {}
            if not gname:
                return self._json({"ok": False, "error": "name is required"}, 400)
            code, data = actions_cli("check", "--action", gname,
                                     "--params", json.dumps(gparams))
            if code == 0 and isinstance(data, dict) and data.get("ok"):
                # ALSO ask lane A/B about the guard's class: the compiled predicate that
                # gates the write is the same one lane A/B serve, so report their parity.
                lanes = run_lane_b(load_settings())
                data["lanes"] = {"ok": bool(lanes.get("ok")),
                                 "classes": [r for r in (lanes.get("rows") or [])
                                             if r.get("served")]}
            return self._json(data, 200 if code == 0 else 500)

        if path != "/api/settings":
            return self._json({"error": "not found"}, 404)

        s = load_settings()
        for key in ("ns", "ontology_dir", "overlay", "title", "sample",
                    "lane", "ontop_endpoint", "ontop_ns", "nl", "ui", "guard"):
            if key in payload:
                s[key] = payload[key]
        if isinstance(payload.get("ui"), dict):
            lang = payload["ui"].get("language")
            if lang and lang not in dict(i18n.LANGS):
                return self._json({"ok": False, "error": f"unknown language: {lang}"}, 400)
            s.setdefault("ui", {})["language"] = lang or i18n.current()
        if isinstance(payload.get("dsn"), dict):
            s["dsn"].update(payload["dsn"])
        if s.get("lane") not in ("a", "b"):
            s["lane"] = "a"
        if not s.get("ns") or not s["dsn"].get("dbname"):
            return self._json({"ok": False, "error": "ns and dsn.dbname are required"}, 400)

        before = load_settings()
        only_language = (json.dumps({k: v for k, v in before.items() if k != "ui"},
                                    sort_keys=True)
                         == json.dumps({k: v for k, v in s.items() if k != "ui"},
                                       sort_keys=True))
        save_settings(s)
        if only_language:
            # a language switch changes no data and no ontology: nothing to regenerate
            return self._json({"ok": True, "log": "language set — restart not needed\n",
                               "settings": s, "redirect": "/settings"})
        ok, log = regenerate(s)
        extra = ""
        if ok:
            lanes = run_lane_b(s)
            extra = "\n" + comparison_text(lanes) + "\n"
        self._json({"ok": ok, "log": log + extra, "settings": s,
                    "redirect": "/compare" if s.get("lane") == "b" else "/"})

    def log_message(self, fmt: str, *args) -> None:  # quieter default logging
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8092)
    ap.add_argument("--settings", default="", help="a profile file (default: settings.json)")
    args = ap.parse_args()
    if args.settings:
        global SETTINGS
        SETTINGS = pathlib.Path(args.settings).resolve()
        i18n.SETTINGS = SETTINGS          # the language switch must follow the same profile
        apply_profile(load_settings())
    srv = ThreadingHTTPServer((args.bind, args.port), Handler)
    print(f"settings-enabled app on http://{args.bind}:{args.port}  (settings /settings, compare /compare, reasoner /reasoner, query /query)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

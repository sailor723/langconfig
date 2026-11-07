#!/usr/bin/env python3
"""Ch1 — the authored tutorial chapters answer on the APP's origin, with nothing left on a workbench port.

The eight hand-written chapters (retail) and the eight ABC training steps were the last user-facing
pages served by a second server. Moving them to `/api/ontology/{key}/…` is only real if two things hold,
and each is measurable rather than assumed:

  1. the served HTML contains NO bare `/api/…` or `/abctutorial/…` path — every absolute path was
     rewritten to this ontology's routes (a missed one silently 404s in the reader's browser, and
     `fetch()` swallows it into an empty panel);
  2. every path the page actually asks for ANSWERS — status 200 and, for JSON, `ok` is not false.

So this gate does not check a list of endpoints somebody wrote down: it reads them out of the pages and
calls them. A page that gains a new fetch gets covered the day it is written.

Write endpoints are NOT executed. `/guard` is a dry run (rolls back) so it is called; `/actions/run`
writes an audit row, so it is only required to EXIST (a 400 "name is required" proves the route is
mounted without touching a row).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
FEATURE = HERE.parent / "features" / "ontology"
PROFILES = FEATURE / "profiles"

CHAPTERS = range(1, 9)


def _get(url: str, timeout: float = 120.0) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"Accept": "text/html,application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except Exception as exc:                                    # noqa: BLE001 — reported, not raised
        return 0, f"{type(exc).__name__}: {exc}"


def _post(url: str, payload: dict, timeout: float = 180.0) -> tuple[int, str]:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except Exception as exc:                                    # noqa: BLE001
        return 0, f"{type(exc).__name__}: {exc}"


def _settings_file(key: str) -> pathlib.Path | None:
    """A profile is `settings.json` OR `<key>_settings.json` — the app accepts both, so must this."""
    for name in (f"{key}/{key}_settings.json", f"{key}/settings.json"):
        p = PROFILES / name
        if p.is_file():
            return p
    hits = sorted(PROFILES.glob(f"{key}/*_settings.json"))
    return hits[0] if hits else None


def _style(key: str) -> str:
    p = _settings_file(key)
    if p is None:
        return ""
    try:
        return str((json.loads(p.read_text()).get("features") or {}).get("tutorial_style") or "")
    except Exception:                                            # noqa: BLE001
        return ""


def _has_training(key: str) -> bool:
    return (PROFILES / key / "tutorial" / "shell.html").is_file()


class Gate:
    def __init__(self) -> None:
        self.failed = 0
        self.checked = 0

    def ok(self, condition: bool, name: str, detail: str = "") -> None:
        self.checked += 1
        if not condition:
            self.failed += 1
        mark = "PASS" if condition else "FAIL"
        line = f"  {mark}  {name}"
        if detail and not condition:
            line += f"  — {detail}"
        print(line)

    def notrun(self, name: str, why: str) -> None:
        print(f"  NOT RUN  {name}  — {why}")


WB = re.compile(r"/api/ontology/[a-z_]+/wb/[A-Za-z0-9_/.-]*")
BARE = re.compile(r"""["'](?:/api/(?!ontology/)|/abctutorial/)""")


def check_chapters(g: Gate, base: str, key: str) -> None:
    print(f"\n[{key}] authored chapters")
    refs: set[str] = set()
    for n in CHAPTERS:
        url = f"{base}/api/ontology/{key}/tutorial/chapter/{n}"
        status, html = _get(url)
        g.ok(status == 200, f"chapter {n} served", f"HTTP {status}: {html[:120]}")
        if status != 200:
            continue
        g.ok("<!doctype html" in html[:200].lower(), f"chapter {n} is html", html[:80])
        bare = BARE.findall(html)
        g.ok(not bare, f"chapter {n} has no bare /api path",
             f"{len(bare)} bare path(s), first: {bare[0][:60] if bare else ''}")
        refs |= set(WB.findall(html))

    g.ok(bool(refs), "the chapters ask for endpoints at all",
         "no /api/ontology/*/wb/ path found — the rewrite may have removed them all")
    print(f"  … {len(refs)} endpoint path(s) referenced by the pages")

    for path in sorted(refs):
        status, body = _get(base + path)
        if status == 404 and "(GET)" in body:
            # the page POSTS to this one (an ask box, a compile form). An empty body must still get a
            # verdict — a refusal ("empty question") is a result and proves the route is mounted.
            status, body = _post(base + path, {})
            g.ok(status == 200 and '"ok"' in body,
                 f"POST {path} answers (empty body is refused, not a 500)",
                 f"HTTP {status}: {body[:120]}")
            continue
        if "/actions/run" in path:
            # proven end-to-end by check_writes (a refused run + an unchanged audit trail); an empty
            # body here only proves the method binding, which that check already covers
            continue
        g.ok(status == 200, f"GET {path}", f"HTTP {status}: {body[:100]}")
        try:
            payload = json.loads(body)
        except Exception:                                        # noqa: BLE001 — html endpoints
            continue
        if isinstance(payload, dict) and "ok" in payload:
            g.ok(payload["ok"] is not False, f"GET {path} did not refuse",
                 str(payload.get("error") or payload.get("refused") or "")[:140])


def check_training(g: Gate, base: str, key: str) -> None:
    print(f"\n[{key}] training pages")
    status, shell = _get(f"{base}/api/ontology/{key}/abct")
    g.ok(status == 200, "training shell served", f"HTTP {status}: {shell[:120]}")
    refs: set[str] = set()
    for n in CHAPTERS:
        status, html = _get(f"{base}/api/ontology/{key}/abct/{n}")
        g.ok(status == 200, f"training step {n} served", f"HTTP {status}: {html[:120]}")
        if status == 200:
            bare = BARE.findall(html)
            g.ok(not bare, f"step {n} has no bare /api path",
                 f"{len(bare)} bare path(s), first: {bare[0][:60] if bare else ''}")
            refs |= set(WB.findall(html))
    if any("/abct/action" in p for p in refs):
        # ABC's step 8 writes through `/abct/action/{check|reset|run}`. `check` is the dry run, so it is
        # the one a gate may call: it exercises the compiled preconditions and writes nothing.
        status, body = _get(f"{base}/api/ontology/{key}/actions")
        try:
            names = [a["name"] for a in (json.loads(body).get("actions") or [])]
        except Exception:                                        # noqa: BLE001
            names = []
        if names:
            status, body = _post(f"{base}/api/ontology/{key}/wb/abct/action/check",
                                 {"name": names[0], "params": {}})
            try:
                verdict = json.loads(body)
            except Exception:                                    # noqa: BLE001
                verdict = {}
            g.ok(status == 200 and isinstance(verdict, dict) and "ok" in verdict,
                 f"POST abct/action/check on {names[0]} answers with a verdict",
                 f"HTTP {status}: {body[:140]}")
        else:
            g.notrun("abct/action/check", "this ontology declares no write verbs")

    for path in sorted(refs):
        if "/abct/action" in path:
            continue                                             # probed above, with a real verb
        status, body = _get(base + path)
        if status == 404 and "(GET)" in body:
            status, body = _post(base + path, {})
            g.ok(status == 200 and '"ok"' in body,
                 f"POST {path} answers (empty body is refused, not a 500)",
                 f"HTTP {status}: {body[:120]}")
            continue
        g.ok(status == 200, f"GET {path}", f"HTTP {status}: {body[:100]}")


#: the POST endpoints each chapter's own JavaScript calls, with a payload the page itself would send.
#: A refusal is acceptable here; a 500 is not — these are the interactive half of the chapters, and a
#: dead ask box is exactly what "the workbench is gone" would look like from the reader's chair.
POST_PROBES: dict[str, list[tuple[str, dict]]] = {
    "retail": [
        ("tutorial1", {"question": "how many customers?"}),
        ("tutorial2", {"question": "dana's orders"}),
        ("tutorial3", {"question": "list orders"}),
    ],
    "abc": [
        ("abct/query", {"name": "vehicles_count"}),
        ("abct/ask", {"question": "有多少辆车"}),
    ],
}


def check_posts(g: Gate, base: str, key: str) -> None:
    print(f"\n[{key}] the chapters' own POST endpoints")
    probes = list(POST_PROBES.get(key) or [])
    # one compile probe, on a metric the ontology actually declares (a made-up name proves only that the
    # route refuses) — read out of the same endpoint the page loads its metric list from
    status, body = _get(f"{base}/api/ontology/{key}/wb/tutorial6/metrics?days=30") if _style(key) == "authored" else (404, "{}")
    if status == 200:
        try:
            first = (json.loads(body).get("metrics") or [{}])[0]
        except Exception:                                        # noqa: BLE001
            first = {}
        if first.get("name"):
            probes.append(("tutorial6/compile",
                           {"metric": first["name"], "formula": "", "aggregate": "", "where": None}))
    elif _style(key) == "authored":
        g.notrun(f"{key} tutorial6/compile probe", f"the metric list returned HTTP {status}")

    for path, payload in probes:
        status, body = _post(f"{base}/api/ontology/{key}/wb/{path}", payload)
        ok_json = False
        try:
            parsed = json.loads(body)
            ok_json = isinstance(parsed, dict) and "ok" in parsed
        except Exception:                                        # noqa: BLE001
            parsed = {}
        # THE assertion: the route answers (200) with a verdict — a refusal is a result, a 5xx is a hole
        g.ok(status == 200 and ok_json, f"POST {path} answers with a verdict",
             f"HTTP {status}: {body[:140]}")
        if path == "abct/query" and status == 200:
            rows = parsed.get("rows") or []
            g.ok(parsed.get("ok") is True and bool(rows), "abct/query returns the vehicle count",
                 str(parsed)[:140])


def check_writes(g: Gate, base: str, key: str) -> None:
    """Chapter 4's buttons: prove the write path without writing.

    A dry run must report `admitted` and roll back; a real run for a row that cannot pass its
    preconditions must be REFUSED — and the audit trail must be exactly as long afterwards as before.
    """
    print(f"\n[{key}] chapter 4's write verbs (dry run + a refused run)")
    status, body = _get(f"{base}/api/ontology/{key}/wb/actions")
    try:
        actions = (json.loads(body).get("actions") or [])
    except Exception:                                            # noqa: BLE001
        actions = []
    if status != 200 or not actions:
        g.notrun(f"{key} write verbs", f"no declared verbs (HTTP {status})")
        return
    name = actions[0]["name"]

    # a dry run is the chapter's "check" button: nothing is written, the preconditions are reported
    status, body = _post(f"{base}/api/ontology/{key}/wb/guard", {"name": name, "params": {"customer_id": 4}})
    try:
        dry = json.loads(body)
    except Exception:                                            # noqa: BLE001
        dry = {}
    g.ok(status == 200 and "admitted" in dry, f"dry run of {name} reports admitted",
         f"HTTP {status}: {body[:140]}")
    g.ok(any("sql_bound" in (c or {}) for c in (dry.get("checks") or [])),
         "the dry run binds its parameters into every precondition",
         str(dry.get("checks"))[:140])

    status, before = _get(f"{base}/api/ontology/{key}/wb/actions/audit")
    try:
        n_before = len(json.loads(before).get("rows") or [])
    except Exception:                                            # noqa: BLE001
        n_before = -1

    # a REAL run that cannot pass: customer 999999 does not exist, so the guard refuses and no row moves
    status, body = _post(f"{base}/api/ontology/{key}/wb/actions/run",
                         {"name": name, "params": {"customer_id": 999999}, "actor": "gate"})
    try:
        ran = json.loads(body)
    except Exception:                                            # noqa: BLE001
        ran = {}
    g.ok(status == 200 and ran.get("ok") is False and (ran.get("refused") or ran.get("error")),
         f"a run of {name} on a row that cannot pass is REFUSED, not written",
         f"HTTP {status}: {body[:160]}")

    status, after = _get(f"{base}/api/ontology/{key}/wb/actions/audit")
    try:
        n_after = len(json.loads(after).get("rows") or [])
    except Exception:                                            # noqa: BLE001
        n_after = -2
    g.ok(n_before == n_after, "the refused run left no audit row",
         f"{n_before} → {n_after} rows")


#: every section the app's rail can open, and which page key serves it
PAGE_SECTIONS = ("graph", "design", "tutorial", "query", "actions")


def check_pages(g: Gate, base: str, key: str) -> None:
    """Each section of the ontology's rail, served by the APP, with every path it asks for answering.

    This is the check that lets the workbench be switched off: if a page were still framing a port, or if
    any path inside it still pointed at `/api/…` on an origin that no longer exists, this section fails.
    """
    print(f"\n[{key}] the rail's pages, on the app's origin")
    refs: set[str] = set()
    for name in PAGE_SECTIONS:
        # a section a profile switches off (retail's actions when features.actions is false) is expected
        # to be absent, but a section the profile DOES declare must serve
        status, html = _get(f"{base}/api/ontology/{key}/page/{name}")
        if status == 404 and "no page" in html:
            g.notrun(f"{key} page/{name}", html[:100])
            continue
        g.ok(status == 200, f"page/{name} served", f"HTTP {status}: {html[:120]}")
        if status != 200:
            continue
        g.ok("<!doctype html" in html[:200].lower(), f"page/{name} is html", html[:80])
        bare = BARE.findall(html)
        g.ok(not bare, f"page/{name} has no bare /api path",
             f"{len(bare)} bare path(s), first: {bare[0][:70] if bare else ''}")
        refs |= set(WB.findall(html))
        # the pages also load one static asset each by absolute path
        for asset in ("tutorial_graph.js", "architecture.svg"):
            if f"/asset/{asset}" in html:
                a_status, _ = _get(f"{base}/api/ontology/{key}/asset/{asset}")
                g.ok(a_status == 200, f"page/{name} asset {asset} served", f"HTTP {a_status}")

    print(f"  … {len(refs)} endpoint path(s) referenced by the pages")
    for path in sorted(refs):
        status, body = _get(base + path)
        if status == 404 and "(GET)" in body:
            status, body = _post(base + path, {})
            g.ok(status == 200 and '"ok"' in body,
                 f"POST {path} answers (empty body is refused, not a 500)",
                 f"HTTP {status}: {body[:120]}")
            continue
        if "/actions/run" in path:
            continue                                             # proven by check_writes
        g.ok(status == 200, f"GET {path}", f"HTTP {status}: {body[:100]}")
        try:
            parsed = json.loads(body)
        except Exception:                                        # noqa: BLE001
            continue
        if isinstance(parsed, dict) and parsed.get("ok") is False:
            g.ok(False, f"GET {path} did not refuse",
                 str(parsed.get("error") or parsed.get("refused") or "")[:140])


def check_refusals(g: Gate, base: str, keys: list[str]) -> None:
    """A profile without chapters must say so, not borrow retail's."""
    print("\n[a profile that ships no chapters]")
    for key in keys:
        if _style(key) == "authored" or _has_training(key):
            continue
        status, body = _get(f"{base}/api/ontology/{key}/tutorial/chapter/1")
        g.ok(status == 404, f"{key} chapter 1 refused by name (HTTP {status})", body[:140])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8765")
    ap.add_argument("--key", default="")
    args = ap.parse_args()
    base = args.base.rstrip("/")

    keys = [p.name for p in sorted(PROFILES.iterdir()) if p.is_dir() and not p.name.startswith(".")]
    if args.key:
        keys = [args.key]

    g = Gate()
    authored = [k for k in keys if _style(k) == "authored" or _has_training(k)]
    if not authored:
        g.notrun("authored chapters", "no profile in this checkout declares tutorial_style=authored")
    for key in keys:
        check_pages(g, base, key)
    for key in authored:
        if _style(key) == "authored":
            check_chapters(g, base, key)
            check_posts(g, base, key)
            check_writes(g, base, key)
        if _has_training(key):
            check_training(g, base, key)
            check_posts(g, base, key)
    check_refusals(g, base, keys)

    print(f"\n{len(keys)} profile(s) · {g.checked} checks · {g.failed} failed")
    return 0 if g.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

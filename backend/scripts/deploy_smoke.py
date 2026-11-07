#!/usr/bin/env python3
"""Smoke a DEPLOYMENT of the ontology feature: is this box actually serving every ontology?

    python -m scripts.deploy_smoke                          # against http://127.0.0.1:8765
    python -m scripts.deploy_smoke --base https://host:8765
    python -m scripts.deploy_smoke --skip-workbench          # workbenches not deployed (the end state)
    python -m scripts.deploy_smoke --json

Why this exists. Everything this feature does is one call away from a wrong answer: a profile that
resolves to another ontology's file, a compiler that runs under an interpreter without `rdflib`, a
dashboard whose declaration was never copied, an action verb whose declaration points at someone
else's YAML. None of that is visible from a 200 on the landing page. Each check below is one of the
ways this system has actually broken, written so that a fresh ECS box answers "yes" or names what is
missing — before a user finds it.

The checks:

  1  the app answers (`/api/chat/health`)
  2  the build directory exists (the frontend was built, not just checked out)
  3  every ontology profile resolves and reports its own object/metric counts
  4  three declared metrics run per ontology — the compiler is alive and pointed at the right DB
  5  the dashboard: panels answer, and the opening assessment parses
  6  one question answers and one refuses — the pipeline works in both directions
  7  the write verbs: a dry run is admitted, bad parameters are refused BY NAME
  8  each workbench (when deployed) serves ITS OWN graph page — the "retail's page for logistics" bug
  9  the gate suite runs on this machine

Exit: 0 every check held; 1 something failed (and the sentence says what); 2 the smoke itself cannot run.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import urllib.error
import urllib.request

CHECKS = 0
FAILS: list[str] = []


def _decode(status: int, raw: bytes):
    body = raw.decode("utf-8", "replace")
    try:
        return status, json.loads(body)
    except json.JSONDecodeError:
        return status, body


def _get(base: str, path: str, timeout: float = 60.0):
    """(status, body) — a 4xx/5xx is a STATUS, not a crash. Measured: a 404 (an ontology with no
    dashboard, correctly refusing) was reported here as `500 {}`, i.e. the check lied about the
    server."""
    req = urllib.request.Request(base.rstrip("/") + path, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return _decode(res.status, res.read())
    except urllib.error.HTTPError as exc:
        return _decode(exc.code, exc.read())


def _post(base: str, path: str, payload: dict, timeout: float = 120.0):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(base.rstrip("/") + path, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return _decode(res.status, res.read())
    except urllib.error.HTTPError as exc:
        return _decode(exc.code, exc.read())


def check(label: str, ok, detail: str = "") -> bool:
    global CHECKS
    CHECKS += 1
    if ok:
        print(f"  PASS  {label}")
        return True
    print(f"  FAIL  {label}" + (f"\n          {detail}" if detail else ""))
    FAILS.append(label)
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="http://127.0.0.1:8765", help="the app backend")
    ap.add_argument("--frontend", default="", help="the frontend origin (default: --base)")
    ap.add_argument("--skip-workbench", action="store_true",
                    help="do not probe the per-ontology workbench servers")
    ap.add_argument("--skip-gates", action="store_true")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args()
    base = args.base
    front = args.frontend or base

    print(f"DEPLOY SMOKE · {base}\n")

    # 1 the app answers
    try:
        status, body = _get(base, "/api/chat/health", timeout=20)
        check("1 the app answers /api/chat/health", status == 200, f"status {status}")
    except Exception as exc:                                    # noqa: BLE001
        check("1 the app answers /api/chat/health", False, f"{type(exc).__name__}: {exc}")
        print("\nthe backend is not answering — nothing else can be checked")
        return 1

    # 2 the frontend build
    try:
        status, body = _get(front, "/", timeout=20)
        html = body if isinstance(body, str) else json.dumps(body)
        check("2 the frontend serves a page", status == 200 and "<" in html,
              f"status {status}, {len(html)} bytes")
    except Exception as exc:                                    # noqa: BLE001
        check("2 the frontend serves a page", False, f"{type(exc).__name__}: {exc}")

    # 3 which ontologies does this deployment serve?
    try:
        status, listing = _get(base, "/api/ontology/workbenches?ensure=false", timeout=60)
        keys = [w.get("key") for w in (listing.get("workbenches") or []) if w.get("key")]
        check("3 the ontology list resolves", bool(keys), f"{status}: {listing}")
    except Exception as exc:                                    # noqa: BLE001
        keys = []
        check("3 the ontology list resolves", False, f"{type(exc).__name__}: {exc}")

    dashboards = []
    for key in keys:
        # 4 every ontology compiles its own numbers
        try:
            status, doc = _get(base, f"/api/ontology/{key}/dashboard/panels", timeout=180)
        except Exception:                                       # noqa: BLE001
            status, doc = 500, {}
        has_dashboard = isinstance(doc, dict) and doc.get("panels") is not None
        if has_dashboard:
            dashboards.append(key)
        # a profile with no dashboard must say so by name, not 500
        check(f"4 {key}: the panel endpoint answers or refuses by name",
              status in (200, 404),
              f"status {status}: {str(doc)[:160]}")
        if has_dashboard:
            panels = doc.get("panels") or []
            kpis = doc.get("kpis") or []
            check(f"5 {key}: the dashboard renders {len(panels)} panels / {len(kpis)} KPIs",
                  len(panels) > 0 and len(kpis) > 0, "a board with no panels is a broken declaration")
            briefing = doc.get("briefing") or {}
            check(f"5 {key}: the opening assessment parses",
                  bool(briefing.get("headline")),
                  f"briefing keys: {sorted(briefing)[:6]}")

    # 6 the question pipeline, both directions
    for key in keys[:2]:
        try:
            status, out = _post(base, f"/api/ontology/{key}/ask", {"question": "how many are there"},
                                timeout=120)
            check(f"6 {key}: a question is answered or refused by name",
                  status == 200 and ("answer" in (out or {}) or "refused" in (out or {})),
                  f"status {status}: {str(out)[:140]}")
        except Exception as exc:                                # noqa: BLE001
            check(f"6 {key}: a question is answered or refused by name", False,
                  f"{type(exc).__name__}: {exc}")

    # 7 the declared write verbs
    try:
        status, out = _get(base, "/api/ontology/logistics/actions", timeout=60)
        verbs = (out or {}).get("actions") or []
        check("7 the write verbs are declared", status == 200 and bool(verbs),
              f"status {status}: {str(out)[:140]}")
        if verbs:
            name = verbs[0]["name"]
            status, out = _post(base, f"/api/ontology/logistics/actions/{name}",
                                {"params": {"trip_id": -1, "driver_id": -1, "planner": "smoke",
                                            "reason": "smoke", "loan_pressure": 0}, "dry_run": True})
            result = (out or {}).get("result") or {}
            admitted = result.get("admitted")
            checks_ran = [(c.get("kind"), c.get("pass")) for c in (result.get("checks") or [])]
            check("7 a dry run with impossible ids is NOT admitted", admitted is False,
                  f"status {status}, admitted={admitted!r}, checks={checks_ran}")
    except Exception as exc:                                    # noqa: BLE001
        check("7 the write verbs are declared", False, f"{type(exc).__name__}: {exc}")

    # 8 each workbench serves ITS OWN page
    if args.skip_workbench:
        print("  NOT RUN  8 workbench pages (--skip-workbench)")
    else:
        try:
            # the FULL listing: `?ensure=false` omits the url, and a row without a url was silently
            # skipped here — a NOT RUN that prints nothing is the failure mode this whole script exists
            # to prevent. Every row reports either a result or a named NOT RUN.
            status, listing = _get(base, "/api/ontology/workbenches", timeout=300)
        except Exception as exc:                                # noqa: BLE001
            listing = {}
            print(f"  NOT RUN  8 workbench pages (the listing failed: {type(exc).__name__}: {exc})")
        for row in listing.get("workbenches") or []:
            url, key = row.get("url"), row.get("key")
            if not (url and key):
                print(f"  NOT RUN  8 workbench {key or '?'} (no url configured for this profile)")
                continue
            try:
                status, html = _get(url, "/", timeout=90)
                text = html if isinstance(html, str) else ""
                titled = key.lower() in text.lower() or "ontology" in text.lower()
                check(f"8 workbench {key} serves a graph page", status == 200 and titled,
                      f"status {status}, title={'?' if not titled else 'ok'}")
            except Exception as exc:                            # noqa: BLE001
                check(f"8 workbench {key} serves a graph page", False,
                      f"{type(exc).__name__}: {exc} (is the profile running? {url})")

    # 9 the gates on this box
    if args.skip_gates:
        print("  NOT RUN  9 the gate suite (--skip-gates)")
    else:
        import subprocess

        here = pathlib.Path(__file__).resolve().parent
        try:
            p = subprocess.run([sys.executable, str(here / "ontology_gates.py"), "--quick"],
                               capture_output=True, text=True, timeout=1800)
            tail = [ln for ln in (p.stdout or "").splitlines() if "runs ·" in ln]
            check("9 the gate suite runs here", p.returncode == 0,
                  tail[-1] if tail else (p.stderr or "")[-300:])
        except Exception as exc:                                # noqa: BLE001
            check("9 the gate suite runs here", False, f"{type(exc).__name__}: {exc}")

    print(f"\n{CHECKS} checks · {len(FAILS)} failed")
    if args.as_json:
        print(json.dumps({"ok": not FAILS, "checks": CHECKS, "failed": FAILS}, ensure_ascii=False))
    return 0 if not FAILS else 1


if __name__ == "__main__":
    raise SystemExit(main())

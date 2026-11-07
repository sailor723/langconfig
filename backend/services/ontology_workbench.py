"""Ontology workbench supervisor — a DEVELOPMENT tool, not part of serving the app.

**Status after M5: nothing in the app calls this.** The graph page, the query console, the actions page,
the tutorial (all eight authored chapters) and ABC's training pages are served by the app itself
(`api/ontology/routes.py` → `services/ontology_pages.py` + `services/ontology_tutorial_chapters.py`), and
every number in them is compiled in-process. Five processes were only ever a URL, and that URL is gone.

It is kept because a workbench is still the fastest way to look at ONE profile's pages while editing the
HTML, and because a learning mirror of the same material still runs one. Starting a child now requires an
explicit `ensure=true`; the default is to report what already exists. A deploy that
forgets this module exists loses nothing.

The workbench (``ontology/retail_graph/serve_ui.py``) is a separate process per profile — it

The workbench (``ontology/retail_graph/serve_ui.py``) is a separate process per profile — it
loads one ontology folder and serves it. Asking a user to open four terminals is not a
feature: this module starts a profile's workbench on demand, remembers the child, and
reports its state, so the Ontology activity can simply say "running" instead of handing out
URLs.

Design decisions that matter:

* **Lazy, never at boot.** A server is started the first time somebody asks for that
  profile's status, not when the app starts. Four always-on Python servers for an activity
  nobody opened yet is a cost with no user.
* **One process per profile, keyed by the profile URL's port.** A second request finds the
  child in the registry instead of spawning a duplicate; a child that died is re-spawned on
  the next request (the registry remembers the intent, not the process).
* **Health is the workbench's own answer.** ``GET <url>/api/ontology`` — a TCP connect is
  not "running"; a process that boots and refuses the profile is not "running" either.
* **Nothing is killed implicitly.** ``stop`` is explicit; a child dies with the parent
  process group on shutdown (``start_new_session`` keeps that from taking the whole app
  down when a workbench is stopped).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

#: The workbench runs from this app: the script is `features/ontology/workbench/serve_ui.py` and the
#: interpreter is the one already running the app (it has rdflib + psycopg2 — that is what serves every
#: number). `settings.ontology.python` can still override the interpreter, and nothing assumes a path on
#: somebody's laptop.

_PROC: dict[str, subprocess.Popen] = {}
#: When each child was started (epoch seconds). A child that predates the workbench script
#: is serving old code — measured: an ABC workbench started at 00:05 kept returning 404 for
#: /api/metrics/cards, added to serve_ui.py at 00:09, and the UI showed an empty metric grid
#: with no error anywhere. Restarting on staleness is the only honest way to survive a
#: deploy: the process looks healthy and answers every endpoint it knows about.
_SPAWNED: dict[str, float] = {}


def _settings() -> dict:
    """The `ontology` settings document (owner layer), or {} — never raises."""
    try:
        from core.settings import store
        from db.database import SessionLocal

        db = SessionLocal()
        try:
            own, effective = store.get_effective_document(db, "ontology")
            return dict(effective or own or {})
        finally:
            db.close()
    except Exception as exc:                                    # noqa: BLE001
        logger.debug("ontology settings unreadable: %s", exc)
        return {}


def _profile_rows() -> list[dict]:
    doc = _settings()
    rows = []
    for item in doc.get("items") or []:
        if not isinstance(item, dict) or not item.get("url"):
            continue
        if item.get("enabled") is False:
            continue
        rows.append({
            "key": str(item.get("key") or ""),
            "label": str(item.get("label") or item.get("key") or ""),
            "url": str(item["url"]).rstrip("/"),
            "profile": (item.get("profile") or "").strip(),
            "note": item.get("note") or None,
        })
    return rows


def _repo() -> pathlib.Path:
    """Where the ontology code lives: THIS app's feature (the learning mirror is not spawned from)."""
    configured = (_settings().get("repo_path") or "").strip()
    return pathlib.Path(configured) if configured else _feature()


def _feature() -> pathlib.Path:
    """The ontology FEATURE: the workbench script, the profiles and the compiler live here."""
    return pathlib.Path(__file__).resolve().parents[1] / "features" / "ontology"


def _python() -> str:
    """The app's own interpreter unless a profile owner overrides it — never a hard-coded venv."""
    return (_settings().get("python") or "").strip() or sys.executable


def _port(url: str) -> int | None:
    try:
        from urllib.parse import urlparse

        return urlparse(url).port
    except Exception:                                          # noqa: BLE001
        return None


def _script_mtime() -> float:
    try:
        return (_feature() / "workbench" / "serve_ui.py").stat().st_mtime
    except OSError:
        return 0.0


def _listener_pid(port: int) -> int | None:
    """The PID listening on `port` — the child may not be one we spawned (a restarted backend
    finds the previous run's children still serving)."""
    try:
        out = subprocess.run(["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
                             capture_output=True, text=True, timeout=5).stdout.split()
        return int(out[0]) if out else None
    except Exception:                                           # noqa: BLE001
        return None


def _listener_start(pid: int) -> float | None:
    """Epoch seconds when `pid` started, from the OS (ps), not from our own bookkeeping."""
    try:
        out = subprocess.run(["ps", "-p", str(pid), "-o", "lstart="],
                             capture_output=True, text=True, timeout=5,
                             env=dict(os.environ, LC_ALL="C")).stdout.strip()
        if not out:
            return None
        import datetime
        return datetime.datetime.strptime(" ".join(out.split()), "%a %b %d %H:%M:%S %Y").timestamp()
    except Exception:                                           # noqa: BLE001
        return None


def _is_stale(url: str) -> bool:
    """True when the process serving this URL was started before serve_ui.py was edited.

    Two ways to know the start time: our own spawn stamp when we started it, or the OS when
    the child came from a previous backend process (measured: an ABC workbench started at
    00:05 kept 404-ing /api/metrics/cards, added at 00:09, and looked healthy — every endpoint
    it knew about answered). A stale child is restarted, because "it answers" is not "it is
    current".
    """
    mtime = _script_mtime()
    if not mtime:
        return False
    proc = _PROC.get(url)
    if proc is not None and proc.poll() is None:
        started = _SPAWNED.get(url)
        if started is not None:
            return mtime > started
    port = _port(url)
    if port is None:
        return False
    pid = _listener_pid(port)
    if pid is None:
        return False
    started = _listener_start(pid)
    return bool(started and mtime > started + 1)     # 1s slack for clock granularity


def _stop_proc(url: str) -> None:
    proc = _PROC.pop(url, None)
    _SPAWNED.pop(url, None)
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _probe(url: str, timeout: float = 1.5) -> tuple[bool, dict | Exception]:
    """Ask the workbench what it serves. `ok` means it answered with a profile."""
    try:
        with urllib.request.urlopen(f"{url}/api/ontology", timeout=timeout) as r:
            body = json.load(r)
        return bool(body.get("ok")), body
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        return False, exc
    except Exception as exc:                                    # noqa: BLE001
        return False, exc


def _spawn(row: dict) -> tuple[bool, str]:
    """Start one profile's workbench. Returns (started, detail)."""
    feature = _feature()
    script = feature / "workbench" / "serve_ui.py"
    if not script.exists():
        return False, f"no workbench script at {script}"
    port = _port(row["url"])
    if port is None:
        return False, f"the URL has no port: {row['url']}"
    profile = row.get("profile") or ""
    if not profile:
        return False, "the profile has no path configured"
    profile_path = pathlib.Path(profile)
    if not profile_path.is_absolute():
        # a profile is named relative to the feature's profiles/ (e.g. "logistics/logistics_settings.json")
        profile_path = feature / "profiles" / profile
    if not profile_path.exists():
        return False, f"profile not found: {profile_path}"

    args = [_python(), str(script), "--settings", str(profile_path), "--port", str(port)]
    try:
        log = pathlib.Path("/tmp") / f"langconfig-workbench-{row['key'] or port}.log"
        with log.open("ab") as fh:
            proc = subprocess.Popen(  # noqa: S603 — a fixed argv, not a shell string
                args,
                cwd=str(feature / "workbench"),
                stdout=fh,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env=dict(os.environ, PYTHONUNBUFFERED="1"),
            )
    except Exception as exc:                                    # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    _PROC[row["url"]] = proc
    _SPAWNED[row["url"]] = time.time()
    logger.info("started workbench %s on :%s (pid %s)", row["key"], port, proc.pid)
    return True, f"pid {proc.pid}, log {log}"


async def ensure_started(row: dict, wait_s: float = 12.0) -> dict:
    """Probe; if it is not answering, start it and wait for it — bounded and reported."""
    restarted = False
    if _is_stale(row["url"]):
        logger.info("workbench %s predates serve_ui.py — restarting it", row["key"])
        _stop_proc(row["url"])
        port = _port(row["url"])
        pid = _listener_pid(port) if port else None
        if pid:
            try:
                os.kill(pid, 15)
                time.sleep(0.6)
            except OSError:
                pass
        restarted = True

    up, detail = _probe(row["url"])
    if up:
        return {"key": row["key"], "url": row["url"], "up": True, "started": False,
                "restarted": restarted,
                "profile": detail.get("profile"), "counts": detail.get("counts")}
    proc = _PROC.get(row["url"])
    started = False
    note = ""
    if proc is not None and proc.poll() is None:
        note = f"already starting (pid {proc.pid})"
    else:
        started, note = _spawn(row)
        if not started:
            return {"key": row["key"], "url": row["url"], "up": False, "started": False,
                    "error": note}
    deadline = asyncio.get_event_loop().time() + wait_s
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.4)
        up, detail = _probe(row["url"], timeout=1.0)
        if up:
            return {"key": row["key"], "url": row["url"], "up": True, "started": started,
                    "restarted": restarted,
                    "profile": detail.get("profile"), "counts": detail.get("counts"),
                    "note": note}
        proc = _PROC.get(row["url"])
        if proc is not None and proc.poll() is not None:
            return {"key": row["key"], "url": row["url"], "up": False, "started": started,
                    "error": f"the workbench exited (code {proc.returncode}); see {note}"}
    return {"key": row["key"], "url": row["url"], "up": False, "started": started,
            "error": f"did not answer within {wait_s:.0f}s ({note})"}


async def status(ensure: bool = False) -> dict:
    """Every configured workbench, and what it says about itself.

    `ensure=True` (explicit, opt-in) starts whatever is missing — that is the development flow. The
    default only reports: no page of the app needs a workbench to answer any more, so nothing should be
    starting one behind a user's back.
    """
    rows = _profile_rows()
    if not rows:
        return {"ok": True, "auto_start": False, "workbenches": [],
                "note": "no ontology profiles configured (Settings → Ontology)"}
    if ensure:
        results = await asyncio.gather(*(ensure_started(r) for r in rows))
    else:
        results = [{"key": r["key"], "url": r["url"], "up": _probe(r["url"])[0]}
                   for r in rows]
    by_key = {r["key"]: r for r in rows}
    out = []
    for res in results:
        row = by_key.get(res["key"], {})
        out.append({
            "key": res["key"],
            # the URL belongs in the payload: a deploy check (and the app) must be able to reach the
            # workbench it is being told about, and `?ensure=false` used to drop it silently
            "url": row.get("url") or res.get("url"),
            "label": row.get("label") or res["key"],
            "profile": row.get("profile"),
            "note": row.get("note"),
            "up": bool(res.get("up")),
            "started": bool(res.get("started")),
            "restarted": bool(res.get("restarted")),
            "counts": res.get("counts"),
            "error": res.get("error"),
        })
    return {"ok": True, "auto_start": True, "repo": str(_repo()), "workbenches": out}


def stop(key: str) -> dict:
    for url, proc in list(_PROC.items()):
        row = next((r for r in _profile_rows() if r["url"] == url), None)
        if (row or {}).get("key") != key:
            continue
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        _PROC.pop(url, None)
        _SPAWNED.pop(url, None)
        return {"ok": True, "stopped": key}
    return {"ok": True, "stopped": None, "note": f"{key} was not started by this process"}


def shutdown() -> None:
    """Stop every child this process started (called from app shutdown)."""
    for url, proc in list(_PROC.items()):
        if proc.poll() is None:
            proc.terminate()
        _PROC.pop(url, None)
        _SPAWNED.pop(url, None)

"""Ontology workbench supervisor.

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
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

#: Where the ontology repo lives and which interpreter has rdflib/psycopg2. Overridable in
#: the `ontology` settings namespace (repo_path / python), because none of this is portable.
DEFAULT_REPO = "/Users/weiping/dev/Learn/ontology"
DEFAULT_PYTHON = "/Users/weiping/dev/Learn/cube/tutorial/.venv/bin/python"

_PROC: dict[str, subprocess.Popen] = {}


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
    return pathlib.Path(_settings().get("repo_path") or DEFAULT_REPO)


def _python() -> str:
    return _settings().get("python") or DEFAULT_PYTHON


def _port(url: str) -> int | None:
    try:
        from urllib.parse import urlparse

        return urlparse(url).port
    except Exception:                                          # noqa: BLE001
        return None


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
    repo = _repo()
    script = repo / "retail_graph" / "serve_ui.py"
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
        profile_path = repo / profile
    if not profile_path.exists():
        return False, f"profile not found: {profile_path}"

    args = [_python(), str(script), "--settings", str(profile_path), "--port", str(port)]
    try:
        log = pathlib.Path("/tmp") / f"langconfig-workbench-{row['key'] or port}.log"
        with log.open("ab") as fh:
            proc = subprocess.Popen(  # noqa: S603 — a fixed argv, not a shell string
                args,
                cwd=str(repo / "retail_graph"),
                stdout=fh,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env=dict(os.environ, PYTHONUNBUFFERED="1"),
            )
    except Exception as exc:                                    # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    _PROC[row["url"]] = proc
    logger.info("started workbench %s on :%s (pid %s)", row["key"], port, proc.pid)
    return True, f"pid {proc.pid}, log {log}"


async def ensure_started(row: dict, wait_s: float = 12.0) -> dict:
    """Probe; if it is not answering, start it and wait for it — bounded and reported."""
    up, detail = _probe(row["url"])
    if up:
        return {"key": row["key"], "url": row["url"], "up": True, "started": False,
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
                    "profile": detail.get("profile"), "counts": detail.get("counts"),
                    "note": note}
        proc = _PROC.get(row["url"])
        if proc is not None and proc.poll() is not None:
            return {"key": row["key"], "url": row["url"], "up": False, "started": started,
                    "error": f"the workbench exited (code {proc.returncode}); see {note}"}
    return {"key": row["key"], "url": row["url"], "up": False, "started": started,
            "error": f"did not answer within {wait_s:.0f}s ({note})"}


async def status(ensure: bool = True) -> dict:
    """Every configured workbench, started on demand unless `ensure` is False."""
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
            "label": row.get("label") or res["key"],
            "profile": row.get("profile"),
            "note": row.get("note"),
            "up": bool(res.get("up")),
            "started": bool(res.get("started")),
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
        return {"ok": True, "stopped": key}
    return {"ok": True, "stopped": None, "note": f"{key} was not started by this process"}


def shutdown() -> None:
    """Stop every child this process started (called from app shutdown)."""
    for url, proc in list(_PROC.items()):
        if proc.poll() is None:
            proc.terminate()
        _PROC.pop(url, None)

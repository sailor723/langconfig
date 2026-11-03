"""Semantics API — read and edit `backend/semantics/<db>/SEMANTICS.md`.

Why this exists as an endpoint rather than a file on disk someone edits in vim:
`load_semantics` (backend/langgraph/langgraph_semantic.py) reads this file **on
every run** and injects its blocks into the SQL prompts. That makes it the single
highest-leverage text in the system — and until now it had no UI at all, so a
typo'd rule or a truncated file changed every answer with nothing to look at.

Placement follows the same logic as the rest of the studio: the file is chosen by
the ACTIVE database target (`sql_setup_db.get_target_database()`), which is what
the Studio's database picker sets. So the canvas "semantic" view shows exactly the
file the next run will load.

Write safety, because this file steers every answer:

* `{database}` is validated against the directories that exist under
  `backend/semantics/` (plus names that already appear as targets) — the path is
  built server-side, never supplied by the caller, so there is no traversal surface.
* Save is admin-only. Read is open.
* Writes are atomic (tmp + os.replace) and keep one `SEMANTICS.md.bak`, so a bad
  edit is one request from undone.
* Save runs the database's own checker when it has one (`check_semantics.py`) and
  returns its verdict, so a rule that contradicts the data fails here rather than
  three questions later in chat.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/semantics", tags=["semantics"])

BACKEND = Path(__file__).resolve().parents[2]
SEMANTICS_ROOT = BACKEND / "semantics"
FILENAME = "SEMANTICS.md"
MAX_BYTES = 256 * 1024

# A database name maps 1:1 onto a directory here. Anything that is not a plain
# identifier is refused before it reaches the filesystem.
_DB_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class SemanticsSave(BaseModel):
    text: str


def _blocks(text: str) -> list[str]:
    """Which blocks the loader will find — same function, not a lookalike."""
    sys.path.insert(0, str(BACKEND / "langgraph"))
    from semantics_blocks import present_blocks

    return present_blocks(text)


def _known_databases() -> list[str]:
    """Databases that can have a semantics file: existing dirs + registered targets."""
    names: set[str] = set()
    if SEMANTICS_ROOT.is_dir():
        names.update(p.name for p in SEMANTICS_ROOT.iterdir() if p.is_dir())
    try:
        import sys as _sys

        _sys.path.insert(0, str(BACKEND / "langgraph"))
        from sql_setup_db import list_targets

        names.update(list_targets())
    except Exception:  # noqa: BLE001 — the registry is a convenience, not a requirement
        pass
    return sorted(names)


def _resolve(database: str, create: bool = False) -> Path:
    db = (database or "").strip().lower()
    if not db or not _DB_RE.match(db):
        raise HTTPException(400, f"invalid database name '{database}'")
    known = _known_databases()
    if db not in known:
        raise HTTPException(
            404,
            f"unknown database '{db}'. Databases with semantics: {known or '(none)'}",
        )
    folder = SEMANTICS_ROOT / db
    if not folder.is_dir():
        if not create:
            raise HTTPException(404, f"no semantics directory for '{db}' ({folder})")
        folder.mkdir(parents=True, exist_ok=True)
    return folder / FILENAME


def _require_admin() -> Optional[int]:
    """The calling user id, or 403 when they are not an admin.

    Editing this file changes what every account's SQL agent says, so it is an
    operator surface. `subject_user_id()` gives the request's account (falling back
    to the install owner when nobody is signed in, which is the single-user case).
    """
    from services.user_roots import subject_user_id

    uid = subject_user_id()
    if uid is None:
        return None  # no accounts configured → single-user install, allow
    try:
        from db.database import SessionLocal
        from services.user_service import get_user

        db = SessionLocal()
        try:
            user = get_user(db, uid) if get_user else None
            role = getattr(user, "role", None)
            role = getattr(role, "value", role)
            if role != "admin":
                raise HTTPException(403, f"editing semantics needs an admin account (you are role={role})")
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — an unreadable role must not grant write
        logger.warning("semantics: could not read role for user %s (%s)", uid, exc)
        raise HTTPException(403, "could not verify your role; semantics editing is disabled")
    return uid


def _checker_for(db_dir: Path) -> Optional[Path]:
    p = db_dir / "check_semantics.py"
    return p if p.is_file() else None


@router.get("")
def list_semantics() -> Dict[str, Any]:
    """Every database that has (or can have) a semantics file."""
    from services.user_roots import subject_user_id

    try:
        sys.path.insert(0, str(BACKEND / "langgraph"))
        from sql_setup_db import get_target_database

        active = get_target_database()
    except Exception:  # noqa: BLE001
        active = None

    out = []
    for db in _known_databases():
        path = SEMANTICS_ROOT / db / FILENAME
        exists = path.is_file()
        text = path.read_text(encoding="utf-8") if exists else ""
        out.append({
            "database": db,
            "path": str(path),
            "exists": exists,
            "bytes": len(text.encode("utf-8")),
            "blocks": _blocks(text) if exists else [],
            "checker": str(_checker_for(SEMANTICS_ROOT / db) or ""),
            "active": db == active,
        })
    return {
        "database": active,
        "items": out,
        "user": subject_user_id(),
    }


@router.get("/{database}")
def get_semantics(database: str) -> Dict[str, Any]:
    """The file the next run will load for this database."""
    path = _resolve(database)
    if not path.is_file():
        return {
            "database": database,
            "path": str(path),
            "exists": False,
            "text": "",
            "bytes": 0,
            "blocks": [],
            "checker": str(_checker_for(path.parent) or ""),
            "mtime": None,
        }
    text = path.read_text(encoding="utf-8")
    checker = _checker_for(path.parent)
    return {
        "database": database,
        "path": str(path),
        "exists": True,
        "text": text,
        "bytes": len(text.encode("utf-8")),
        "blocks": _blocks(text),
        "checker": str(checker or ""),
        "mtime": path.stat().st_mtime,
    }


def _run_checker(db: str, path: Path) -> Dict[str, Any]:
    """Run `check_semantics.py` for this database, if it has one.

    Deliberately a subprocess against the backend venv: the checkers connect to the
    database and, for TPCH, compare every documented number. Running them outside
    the request's process keeps a hanging connection from stalling the API.
    """
    checker = _checker_for(path.parent)
    if checker is None:
        return {"status": "absent", "lines": [], "checker": None}
    try:
        proc = subprocess.run(
            [sys.executable, str(checker)],
            capture_output=True,
            text=True,
            timeout=180,
            cwd=str(checker.parent),
        )
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "lines": ["checker exceeded 180s"], "checker": str(checker)}
    lines = [ln for ln in (proc.stdout or "").strip().splitlines() if ln.strip()]
    return {
        "status": "pass" if proc.returncode == 0 else "fail",
        "exit": proc.returncode,
        "lines": lines[-12:],
        "checker": str(checker),
    }


@router.put("/{database}")
def save_semantics(database: str, payload: SemanticsSave) -> Dict[str, Any]:
    """Save, keep a backup, then run the database's gate against the new text."""
    user = _require_admin()
    path = _resolve(database, create=True)

    text = payload.text or ""
    if not text.strip():
        raise HTTPException(400, "refusing to save an empty SEMANTICS.md — the graph would load nothing")
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise HTTPException(400, f"SEMANTICS.md is larger than {MAX_BYTES} bytes")

    # The loader splits on "## Section" headings and drops anything it cannot
    # classify. A file with no recognised section injects NOTHING — measured: a
    # whole rewrite using "###" headings left every block empty and the model got
    # no rules at all, with no error anywhere. Refuse that save instead.
    if not _blocks(text):
        raise HTTPException(
            400,
            "this file has no '## ' section headings the loader recognises, so it "
            "would inject nothing into the SQL prompts. Add sections such as "
            "'## 表与 join', '## 口径规则', '## 示例' (## or deeper, with a space).",
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        backup = path.with_suffix(".md.bak")
        try:
            backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 — a missing backup must not block the save
            logger.warning("semantics: could not write backup for %s (%s)", path, exc)

    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".semantics-", suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except Exception as exc:  # noqa: BLE001
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise HTTPException(500, f"could not write {path}: {exc}")

    check = _run_checker(database, path)
    logger.info(
        "semantics: %s saved by user %s (%d bytes, blocks=%s, gate=%s)",
        path.name, user, len(text.encode("utf-8")), _blocks(text), check["status"],
    )
    return {
        "saved": True,
        "database": database,
        "path": str(path),
        "bytes": len(text.encode("utf-8")),
        "blocks": _blocks(text),
        "check": check,
        "note": "load_semantics re-reads the file on every run — the change applies to the next chat/Studio run.",
    }


@router.post("/{database}/check")
def check_semantics(database: str) -> Dict[str, Any]:
    """Run the gate without writing anything."""
    path = _resolve(database)
    if not path.is_file():
        raise HTTPException(404, f"{path} does not exist")
    return {"database": database, "check": _run_checker(database, path)}

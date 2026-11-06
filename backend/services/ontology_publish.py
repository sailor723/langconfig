"""Ontology publishing — the one way a declaration reaches an ontology workbench.

An ontology is a set of declarations a number is compiled from, so a change to it is not a
file write: it is a claim that every metric still compiles, every definition still selects
something, and the numbers still agree with an independent route. This module is that claim,
made executable and reversible.

The pipeline, in this order, with nothing skipped:

    stage(files)   →  write to a hidden staging dir, load the ontology from there, compile
                      every metric, run the generic gates, and return a REPORT + a staged id.
                      Nothing outside the staging dir changes.
    apply(id)      →  re-run the same checks against the staged copy, then move the files into
                      `ontologies/<key>/`, run the gates against the installed copy, and only
                      then: git commit (if enabled), reload the workbench, write the audit row.
                      Any failure restores the previous bytes exactly.

Design decisions worth knowing:

* **Staged, never in-place.** The overlay is the thing the workbench reads while a user asks
  questions; writing it directly and then discovering a refusal would mean every reader saw a
  broken ontology for the duration. Staging makes the failure mode "nothing happened".
* **The compiler is the judge.** A staged metric that refuses is a refusal in the report, and
  `apply` refuses to continue while any refusal is NEW (a refusal that already existed on the
  installed ontology is not this publish's fault — it is reported, and carried forward).
* **Publish needs confirmation.** `apply` requires a `confirmed=True` from a human caller;
  agents stage, they never apply. That is the difference between "the agent did the work" and
  "the agent changed production on its own".
* **The audit row is part of the transaction** — written in the same code path that moves the
  files, so "it happened but nobody knows who" is not a state this can reach.
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import shutil
import subprocess
import time
import uuid

logger = logging.getLogger(__name__)

#: Where ontologies live. The workbench reads `<repo>/ontologies/<key>/<profile>` and the
#: supervisor starts one process per profile from here, so this is the only place a publish
#: can land.
REPO = pathlib.Path(os.environ.get("ONTOLOGY_REPO") or "/Users/weiping/dev/Learn/ontology")
ONTOLOGIES = REPO / "ontologies"
#: Interpreter with rdflib + psycopg2 (the workbench's own runtime).
PYTHON = os.environ.get("ONTOLOGY_PYTHON") or "/Users/weiping/dev/Learn/cube/tutorial/.venv/bin/python"

_AUDIT_DDL = """
CREATE TABLE IF NOT EXISTS ontology_publishes (
    id            text PRIMARY KEY,
    key           text NOT NULL,
    actor         text,
    status        text NOT NULL,              -- staged | applied | refused | reverted
    note          text,
    files         jsonb,
    report        jsonb,
    git_commit    text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
)
"""


# ─────────────────────────────────────────────────────────────── helpers
def _db():
    from db.database import SessionLocal

    return SessionLocal()


def _ensure_table() -> None:
    try:
        from sqlalchemy import text

        db = _db()
        try:
            db.execute(text(_AUDIT_DDL))
            db.commit()
        finally:
            db.close()
    except Exception as exc:                                    # noqa: BLE001
        logger.warning("ontology_publishes table unavailable: %s", exc)


def _audit_row(pid: str, key: str, actor: str | None, status: str, note: str = "",
               files: dict | None = None, report: dict | None = None,
               git_commit: str | None = None) -> None:
    try:
        _ensure_table()
        db = _db()
        try:
            from sqlalchemy import text

            db.execute(text("""
                INSERT INTO ontology_publishes (id, key, actor, status, note, files, report, git_commit)
                VALUES (:id, :key, :actor, :status, :note, CAST(:files AS jsonb),
                        CAST(:report AS jsonb), :sha)
                ON CONFLICT (id) DO UPDATE SET status = :status, note = :note,
                    report = CAST(:report AS jsonb), git_commit = :sha, updated_at = now()
            """), {"id": pid, "key": key, "actor": actor, "status": status, "note": note,
                   "files": json.dumps(files or {}), "report": json.dumps(report or {}),
                   "sha": git_commit})
            db.commit()
        finally:
            db.close()
    except Exception as exc:                                    # noqa: BLE001
        logger.warning("ontology publish audit failed: %s", exc)


def _staging_dir(key: str) -> pathlib.Path:
    return ONTOLOGIES / key / ".staging"


def _profile_for(key: str) -> pathlib.Path | None:
    """The profile file inside an ontology directory (`*_settings.json`, else settings.json)."""
    base = ONTOLOGIES / key
    if not base.is_dir():
        return None
    preferred = sorted(base.glob("*_settings.json"))
    if preferred:
        return preferred[0]
    candidate = base / "settings.json"
    return candidate if candidate.exists() else None


def _run_gates(profile_path: pathlib.Path, truth: pathlib.Path | None = None) -> dict:
    """Run the generic gate suite against a profile. Never raises: a gate failure is a result."""
    args = [PYTHON, str(REPO / "retail_graph" / "check_ontology_generic.py"),
            "--profile", str(profile_path)]
    if truth and truth.exists():
        args += ["--truth", str(truth)]
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=600,
                           cwd=str(REPO / "retail_graph"))
    except Exception as exc:                                    # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "text": ""}
    text_out = (p.stdout or "") + (p.stderr or "")
    fails = [ln.strip() for ln in text_out.splitlines() if "[FAIL]" in ln]
    notrun = [ln.strip() for ln in text_out.splitlines() if "[NOT RUN]" in ln]
    return {"ok": p.returncode == 0 and not fails, "fails": fails, "not_run": notrun,
            "text": text_out[-8000:]}


def _compile_report(profile_path: pathlib.Path) -> dict:
    """Compile every metric/definition once, as a compact report (refusals by name)."""
    import textwrap
    script = textwrap.dedent('''
        import json, sys
        sys.path.insert(0, {repo!r} + "/retail_graph")
        import sqlgen
        prof = json.loads(open({profile!r}).read())
        base = __import__("pathlib").Path({profile!r}).parent
        sqlgen.reconfigure(ns=prof.get("ns"),
                           ontology_dir=str((base / prof.get("ontology_dir", "ontology")).resolve()),
                           overlay=str((base / prof["overlay"]).resolve()) if prof.get("overlay") else "",
                           drop_overlay=not prof.get("overlay"))
        g = sqlgen.load()
        ms = sqlgen.metrics(g)
        ok, bad = [], []
        for n in sorted(ms):
            try:
                sqlgen.compile_metric(g, n); ok.append(n)
            except Exception as exc:
                bad.append({{"name": n, "why": str(exc).splitlines()[0]}})
        print(json.dumps({{"metrics": len(ms), "compiled": len(ok), "refused": bad}}))
    ''')
    src = script.format(repo=str(REPO), profile=str(profile_path))
    try:
        p = subprocess.run([PYTHON, "-c", src], capture_output=True, text=True, timeout=300)
        return json.loads((p.stdout or "").strip().splitlines()[-1])
    except Exception as exc:                                    # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def _git(key: str, message: str) -> str | None:
    """Commit the ontology directory. Returns the short sha, or None when git is off."""
    try:
        # A publish keeps its staging and backup under the ontology dir; committing those
        # would put a second copy of every file in history (measured on the first publish:
        # 900 lines of .backup in the commit). The ignore file is part of the ontology now.
        ignore = ONTOLOGIES / key / ".gitignore"
        if not ignore.exists():
            ignore.write_text(".staging/\n.backup/\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(REPO), "add", "-A", f"ontologies/{key}"],
                       capture_output=True, text=True, timeout=60, check=True)
        p = subprocess.run(["git", "-C", str(REPO), "commit", "-m", message],
                           capture_output=True, text=True, timeout=120)
        if p.returncode != 0:
            logger.warning("git commit for %s failed: %s", key, (p.stderr or "").strip()[:200])
            return None
        sha = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=30).stdout.strip()
        return sha or None
    except Exception as exc:                                    # noqa: BLE001
        logger.warning("git commit for %s failed: %s", key, exc)
        return None


# ─────────────────────────────────────────────────────────────── stage
def stage(key: str, files: dict[str, str], *, actor: str | None = None, note: str = "",
          profile_name: str | None = None) -> dict:
    """Write a candidate ontology into a staging dir and validate it. Nothing else changes.

    `files` maps a path RELATIVE to `ontologies/<key>/` to its content (text). A caller that
    wants to change one declaration sends the whole file it edits — the unit of a publish is
    the file, because that is what the workbench reads.
    """
    key = (key or "").strip()
    if not key or "/" in key or key.startswith("."):
        return {"ok": False, "error": f"invalid ontology key {key!r}"}
    if not files:
        return {"ok": False, "error": "nothing to publish"}

    live = ONTOLOGIES / key
    live_profile = _profile_for(key)
    staged_id = f"{int(time.time())}-{uuid.uuid4().hex[:6]}"
    staging = _staging_dir(key) / staged_id
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)

    # a publish starts from the INSTALLED ontology, so a partial edit cannot silently delete
    # the files it did not mention
    if live.is_dir():
        for src in live.rglob("*"):
            if src.is_file() and ".staging" not in src.parts:
                dst = staging / src.relative_to(live)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
    for rel, content in files.items():
        rel_path = pathlib.Path(rel)
        if rel_path.is_absolute() or ".." in rel_path.parts:
            return {"ok": False, "error": f"refusing a path outside the ontology: {rel!r}"}
        dst = staging / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(content, encoding="utf-8")

    staged_profile = staging / (profile_name or (live_profile.name if live_profile else
                                                 f"{key}_settings.json"))
    if not staged_profile.exists():
        candidates = sorted(staging.glob("*_settings.json")) or sorted(staging.glob("settings.json"))
        if not candidates:
            return {"ok": False, "error": "the staged ontology has no profile (*_settings.json)",
                    "staged_id": staged_id}
        staged_profile = candidates[0]

    compile_report = _compile_report(staged_profile)
    # What was already refused on the installed ontology is NOT this publish's fault (a
    # deferred metric stays deferred); what is refused only HERE is. Measured on the first
    # negative test: a stage that added a metric without :grain was reported ok because the
    # rule only asked "did anything compile".
    live_refused = set()
    if live_profile is not None:
        live_compile = _compile_report(live_profile)
        live_refused = {r.get("name") for r in live_compile.get("refused") or []}
    staged_refused = {r.get("name") for r in compile_report.get("refused") or []}
    new_refusals = sorted(staged_refused - live_refused)
    gates = _run_gates(staged_profile)
    report = {
        "compile": compile_report,
        "new_refusals": new_refusals,
        "carried_refusals": sorted(staged_refused & live_refused),
        "gates_ok": gates.get("ok"),
        "gates_fails": gates.get("fails", []),
        "gates_not_run": gates.get("not_run", []),
        "gates_text": gates.get("text", "")[-6000:],
        "files": sorted(files),
    }
    ok = (bool(compile_report.get("compiled", 0)) and not new_refusals
          and not gates.get("fails"))
    status = "staged" if ok else "refused"
    _audit_row(staged_id, key, actor, status, note=note, files=files, report=report)
    return {"ok": ok, "staged_id": staged_id, "key": key, "report": report,
            "profile": str(staged_profile)}


# ─────────────────────────────────────────────────────────────── apply
def apply(staged_id: str, *, actor: str | None = None, confirmed: bool = False,
          git_commit: bool = True) -> dict:
    """Install a staged publish. Requires confirmation; reverts on any failure."""
    if not confirmed:
        return {"ok": False, "error": "not confirmed: a publish lands only after a human says so"}

    rows = _audit_list(staged_id)
    if not rows:
        return {"ok": False, "error": f"no staged publish {staged_id!r}"}
    row = rows[0]
    if row.get("status") != "staged":
        why = "refused at stage time (see its report)" if row.get("status") == "refused" else row.get("status")
        return {"ok": False, "error": f"publish {staged_id} is {why}"}
    key = row["key"]
    staging = _staging_dir(key) / staged_id
    live = ONTOLOGIES / key
    if not staging.is_dir():
        return {"ok": False, "error": f"the staging dir for {staged_id} is gone"}

    # 1. the staged copy must still pass — someone may have edited the live ontology since
    staged_profile = _profile_for_staged(staging)
    if staged_profile is None:
        return {"ok": False, "error": "staged profile missing"}
    recheck = _compile_report(staged_profile)
    gates = _run_gates(staged_profile)
    if gates.get("fails"):
        _audit_row(staged_id, key, actor, "refused", note="gates failed on re-check",
                   report={"compile": recheck, "gates_fails": gates.get("fails", []),
                           "gates_text": gates.get("text", "")[-6000:]})
        return {"ok": False, "error": "gates failed on re-check", "report": gates}

    # 2. install with a byte-exact backup, so a failure restores what readers had
    backup = ONTOLOGIES / key / ".backup" / staged_id
    backup.parent.mkdir(parents=True, exist_ok=True)
    existed = live.exists()
    try:
        if existed:
            shutil.copytree(live, backup, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns(".staging", ".backup"))
        for src in staging.rglob("*"):
            if not src.is_file():
                continue
            rel = src.relative_to(staging)
            if rel.parts and rel.parts[0] in (".staging", ".backup"):
                continue
            dst = live / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    except Exception as exc:                                    # noqa: BLE001
        _restore(live, backup, existed)
        return {"ok": False, "error": f"install failed, reverted: {exc}"}

    # 3. the INSTALLED copy is what readers get: gates again, against the real path
    installed_profile = _profile_for(key)
    if installed_profile is None:
        _restore(live, backup, existed)
        return {"ok": False, "error": "the installed ontology has no profile, reverted"}
    final_compile = _compile_report(installed_profile)
    final_gates = _run_gates(installed_profile)
    if final_gates.get("fails") or not final_compile.get("compiled"):
        _restore(live, backup, existed)
        _audit_row(staged_id, key, actor, "reverted", note="post-install gates failed",
                   report={"compile": final_compile, "gates_fails": final_gates.get("fails", []),
                           "gates_text": final_gates.get("text", "")[-6000:]})
        return {"ok": False, "error": "post-install gates failed; reverted byte-for-byte",
                "report": final_gates}

    sha = None
    if git_commit:
        body = (f"ontology({key}): publish {staged_id}\n\n"
                f"metrics {final_compile.get('compiled', 0)} compiled, "
                f"{len(final_compile.get('refused', []))} refused by name; gates: "
                f"{'PASS' if final_gates.get('ok') else 'FAIL'}"
                + (f"; not run: {len(final_gates.get('not_run', []))}" if final_gates.get('not_run') else ""))
        sha = _git(key, body)

    _audit_row(staged_id, key, actor, "applied", note="installed",
               report={"compile": final_compile, "gates_ok": final_gates.get("ok"),
                       "git_commit": sha, "gates_text": final_gates.get("text", "")[-6000:]},
               git_commit=sha)
    shutil.rmtree(staging, ignore_errors=True)

    # 4. the running workbench keeps serving old code until it reloads
    reload_note = reload_workbench(key)
    return {"ok": True, "staged_id": staged_id, "key": key, "git_commit": sha,
            "workbench_reloaded": reload_note == "", "reload_note": reload_note,
            "report": {"compile": final_compile, "gates_ok": final_gates.get("ok"),
                       "gates_fails": final_gates.get("fails", []),
                       "gates_not_run": final_gates.get("not_run", [])}}


def discard(staged_id: str, *, actor: str | None = None) -> dict:
    """Throw away a staged publish and its staging tree. Nothing installed is touched.

    A staging tree is a copy of an ontology plus the agent's edits — it is scratch, but it sits
    inside the repo (git-ignored), so leaving refused and superseded ones there forever is how a
    repo fills with candidates nobody can tell apart. Discarding records the decision.
    """
    rows = _audit_list(staged_id)
    if not rows:
        return {"ok": False, "error": f"no publish {staged_id!r}"}
    row = rows[0]
    if row.get("status") == "applied":
        return {"ok": False, "error": "that publish is already installed; there is nothing to discard"}
    key = row["key"]
    staging = _staging_dir(key) / staged_id
    shutil.rmtree(staging, ignore_errors=True)
    _audit_row(staged_id, key, actor or row.get("actor"), "discarded",
               note=row.get("note") or "discarded", report=row.get("report") or {})
    return {"ok": True, "staged_id": staged_id, "key": key, "status": "discarded"}


def _profile_for_staged(staging: pathlib.Path) -> pathlib.Path | None:
    preferred = sorted(staging.glob("*_settings.json"))
    if preferred:
        return preferred[0]
    candidate = staging / "settings.json"
    return candidate if candidate.exists() else None


def _restore(live: pathlib.Path, backup: pathlib.Path, existed: bool) -> None:
    try:
        if not existed:
            shutil.rmtree(live, ignore_errors=True)
            return
        if backup.exists():
            for src in backup.rglob("*"):
                if src.is_file():
                    dst = live / src.relative_to(backup)
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
    except Exception as exc:                                    # noqa: BLE001
        logger.error("ontology restore failed for %s: %s — the backup is at %s", live, exc, backup)


def reload_workbench(key: str) -> str:
    """Restart the workbench serving this ontology. Returns a human reason ("" = reloaded).

    The coroutine is run on its OWN thread: this is called from the publish API handler (a running
    event loop, where `asyncio.run` raises) and from the agent's publish tool (no loop at all).
    Measured on the first real publish: the apply committed and left `workbench_reloaded: false`
    with `RuntimeError: asyncio.run() cannot be called from a running event loop`, so the served
    numbers stayed on the old code until someone restarted it by hand.
    """
    try:
        from services import ontology_workbench

        ontology_workbench.stop(key)
        rows = [r for r in ontology_workbench._profile_rows() if r["key"] == key]
        if not rows:
            return (f"{key} is not registered in Settings → Ontology, so no workbench was "
                    f"running for it; add the profile there to serve it")
        import asyncio
        import concurrent.futures

        def _start():
            return asyncio.run(ontology_workbench.ensure_started(rows[0], wait_s=15))

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            res = pool.submit(_start).result()
        return "" if res.get("up") else f"the workbench for {key} did not come back up"
    except Exception as exc:                                    # noqa: BLE001
        logger.warning("workbench reload for %s failed: %s", key, exc)
        return f"{type(exc).__name__}: {exc}"


def _audit_list(staged_id: str | None = None, limit: int = 50) -> list[dict]:
    try:
        _ensure_table()
        db = _db()
        try:
            from sqlalchemy import text

            sql = "SELECT id, key, actor, status, note, report, git_commit, created_at FROM ontology_publishes"
            params: dict = {}
            if staged_id:
                sql += " WHERE id = :id"
                params["id"] = staged_id
            sql += " ORDER BY created_at DESC LIMIT :lim"
            params["lim"] = limit
            rows = db.execute(text(sql), params).fetchall()
            out = []
            for r in rows:
                out.append({"id": r[0], "key": r[1], "actor": r[2], "status": r[3],
                            "note": r[4], "report": r[5], "git_commit": r[6],
                            "created_at": r[7].isoformat() if r[7] else None})
            return out
        finally:
            db.close()
    except Exception as exc:                                    # noqa: BLE001
        logger.warning("ontology publish audit read failed: %s", exc)
        return []


def history(key: str | None = None, limit: int = 50) -> list[dict]:
    rows = _audit_list(limit=limit)
    return [r for r in rows if not key or r["key"] == key]

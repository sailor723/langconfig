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
import datetime
import threading
import time
import uuid

logger = logging.getLogger(__name__)

#: Where the LIVE ontologies live: the ontology FEATURE (backend/features/ontology). Its
#: profiles/ holds the declarations, its gates/ holds the checks, its compiler/ the compiler.
#: The ontology repository stays as a learning mirror of the same material — it is not a runtime
#: dependency, because a publish that edits the mirror while the app reads the feature is exactly
#: the "two copies of the truth" failure this feature was created to end.
FEATURE = pathlib.Path(__file__).resolve().parents[1] / "features" / "ontology"
ONTOLOGIES = FEATURE / "profiles"
GATES = FEATURE / "gates"
#: The COMPILER, in the app: a child script that compiles a staged declaration must use THIS one, not a
#: copy — a publish that validated against the learning mirror would be validating a different compiler
#: than the one that serves the numbers.
COMPILER = FEATURE / "compiler"
#: Interpreter with rdflib + psycopg2. The feature lives INSIDE the app, so the app's own
#: interpreter already has them; ONTOLOGY_PYTHON still overrides it.
PYTHON = os.environ.get("ONTOLOGY_PYTHON") or __import__("sys").executable

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

            # `applied` is FINAL. A late writer (a double-click's second apply, whose gate run saw a
            # staging tree the first call was deleting) used to overwrite the outcome with "refused",
            # so a successful install read as a failure in the ledger while its commit sat in git.
            # Measured on new_coldchain_v6: commit baaa1a88 at 19:07:26, status "refused" four seconds
            # later. History may be appended to, never rewritten.
            db.execute(text("""
                INSERT INTO ontology_publishes (id, key, actor, status, note, files, report, git_commit)
                VALUES (:id, :key, :actor, :status, :note, CAST(:files AS jsonb),
                        CAST(:report AS jsonb), :sha)
                ON CONFLICT (id) DO UPDATE SET status = :status, note = :note,
                    report = CAST(:report AS jsonb), git_commit = :sha, updated_at = now()
                WHERE ontology_publishes.status <> 'applied'
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


#: Which gate FAMILIES hold for which ontology — the same declaration `scripts/ontology_gates.py` reads.
DECLARATION = FEATURE / "gates.json"


def declared_families(key: str | None) -> list[str]:
    """The gate families `gates.json` declares for this key (empty when the key declares none)."""
    if not key:
        return []
    try:
        spec = json.loads(DECLARATION.read_text(encoding="utf-8")).get(key) or {}
    except Exception as exc:                                    # noqa: BLE001
        logger.warning("gates.json unreadable (%s); falling back to the generic gate", exc)
        return []
    return [name for name in (spec.get("profile") or []) if isinstance(name, str)]


def _run_gates(profile_path: pathlib.Path, truth: pathlib.Path | None = None,
               key: str | None = None) -> dict:
    """Run EVERY gate family `gates.json` declares for this key. Never raises: a failure is a result.

    This used to run `check_ontology_generic` only, and the omission was invisible: the declaration
    said `sunhing_v1` also holds check_structure / check_samples / check_dashboard, the runner showed
    check_dashboard red, and a publish still reported "gates: PASS" — a gate that does not run is not
    a gate that passed. The families come from the declaration, so an ontology that declares fewer
    families is not silently held to more.
    """
    families = declared_families(key) or ["check_ontology_generic"]
    fails: list[str] = []
    notrun: list[str] = []
    texts: list[str] = []
    ran: list[str] = []
    for name in families:
        script = GATES / f"{name}.py"
        if not script.is_file():
            fails.append(f"[FAIL] declared gate script missing: {script.name}")
            continue
        args = [PYTHON, str(script), "--profile", str(profile_path)]
        if name == "check_ontology_generic" and truth and truth.exists():
            args += ["--truth", str(truth)]
        try:
            p = subprocess.run(args, capture_output=True, text=True, timeout=900,
                               cwd=str(GATES))
        except Exception as exc:                                # noqa: BLE001
            fails.append(f"[FAIL] {name}: {type(exc).__name__}: {exc}")
            continue
        text_out = (p.stdout or "") + (p.stderr or "")
        ran.append(name)
        this_fails = [ln.strip() for ln in text_out.splitlines() if "[FAIL]" in ln]
        if p.returncode != 0 and not this_fails:
            # a crash or a bare non-zero exit is still a failure, quoted so it cannot hide
            tail = next((ln.strip() for ln in reversed(text_out.splitlines()) if ln.strip()), "")
            this_fails = [f"[FAIL] {name} exited {p.returncode}: {tail[:200]}"]
        fails += this_fails
        notrun += [f"{name}: {ln.strip()}" for ln in text_out.splitlines() if "[NOT RUN]" in ln]
        texts.append(f"=== {name} ===\n{text_out}")
    return {"ok": not fails, "fails": fails, "not_run": notrun, "families": ran,
            "text": "\n".join(texts)[-12000:]}


def _compile_report(profile_path: pathlib.Path) -> dict:
    """Compile every metric/definition once, as a compact report (refusals by name)."""
    import textwrap
    script = textwrap.dedent('''
        import json, sys
        sys.path.insert(0, {compiler!r})
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
    src = script.format(compiler=str(COMPILER), profile=str(profile_path))
    try:
        p = subprocess.run([PYTHON, "-c", src], capture_output=True, text=True, timeout=300)
        out = (p.stdout or "").strip()
        if not out:
            # A compile child that prints nothing says nothing useful: report what it DID say
            # (its stderr) instead of an IndexError from taking the last line of "".
            err = (p.stderr or "").strip().splitlines()
            return {"error": "the compiler printed nothing"
                             + (f": {err[-1]}" if err else f" (exit {p.returncode})")}
        return json.loads(out.splitlines()[-1])
    except Exception as exc:                                    # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def _git(key: str, message: str) -> tuple[str | None, str | None]:
    """Commit the ontology directory. Returns (short sha, error) — one of them is always None.

    It used to return a bare sha/None, so a commit that FAILED looked exactly like a publish made
    with git switched off. Measured on the deployment: every apply since v4 logged "Author identity
    unknown" in the journal, recorded `git_commit: null`, and still read as a clean publish — while
    the ontology's files piled up STAGED in the repo. The error now travels with the result.
    """
    try:
        # A publish keeps its staging and backup under the ontology dir; committing those
        # would put a second copy of every file in history (measured on the first publish:
        # 900 lines of .backup in the commit). The ignore file is part of the ontology now.
        ignore = ONTOLOGIES / key / ".gitignore"
        if not ignore.exists():
            ignore.write_text(".staging/\n.backup/\n", encoding="utf-8")
        # the commit lands in the repository that HOLDS the feature now (the app's), because that is
        # where the published declarations live; the learning mirror keeps its own history
        app_repo = pathlib.Path(__file__).resolve().parents[2]
        rel = (ONTOLOGIES / key).relative_to(app_repo)
        subprocess.run(["git", "-C", str(app_repo), "add", "-A", str(rel)],
                       capture_output=True, text=True, timeout=60, check=True)
        p = subprocess.run(["git", "-C", str(app_repo), "commit", "-m", message],
                           capture_output=True, text=True, timeout=120)
        if p.returncode != 0:
            err = " ".join(((p.stdout or "") + " " + (p.stderr or "")).split())[:300]
            logger.warning("git commit for %s failed: %s", key, err)
            return None, (err or f"git commit exited {p.returncode}")
        sha = subprocess.run(["git", "-C", str(app_repo), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=30).stdout.strip()
        return (sha or None), None
    except Exception as exc:                                    # noqa: BLE001
        logger.warning("git commit for %s failed: %s", key, exc)
        return None, str(exc)


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
    if not ok:
        # A refused staging can never be applied, so its tree is only disk: keep `.staging/` meaning
        # "waiting for a human" (measured on this instance: 9 trees from refusals sat next to the one
        # real pending publish, and the pending list is built from the ledger, so nothing told the two
        # apart). The report above already carries the text a reader needs.
        shutil.rmtree(staging, ignore_errors=True)
    return {"ok": ok, "staged_id": staged_id, "key": key, "report": report,
            "profile": str(staged_profile)}


# ─────────────────────────────────────────────────────────────── apply
#: One apply at a time, per staged id. A double-click used to run two of them: the second's gate
#: re-check read a staging tree the first was already deleting, produced 20 "empty menu" refusals, and
#: recorded the publish as refused AFTER it had installed and committed. Serialising also makes the
#: status re-read meaningful (see the second check inside the lock).
_APPLY_LOCKS: dict[str, "threading.Lock"] = {}
_APPLY_LOCKS_GUARD = None


def _apply_lock(staged_id: str):
    global _APPLY_LOCKS_GUARD
    if _APPLY_LOCKS_GUARD is None:
        _APPLY_LOCKS_GUARD = threading.Lock()
    with _APPLY_LOCKS_GUARD:
        lock = _APPLY_LOCKS.get(staged_id)
        if lock is None:
            lock = _APPLY_LOCKS[staged_id] = threading.Lock()
        return lock


def apply(staged_id: str, *, actor: str | None = None, confirmed: bool = False,
          git_commit: bool = True) -> dict:
    """Install a staged publish. Requires confirmation; reverts on any failure.

    Serialised per staged id: the second caller waits, then finds the row no longer `staged` and is told
    what it became ("already applied at …"), instead of racing the first one's cleanup.
    """
    if not confirmed:
        return {"ok": False, "error": "not confirmed: a publish lands only after a human says so"}

    with _apply_lock(staged_id):
        return _apply_locked(staged_id, actor=actor, git_commit=git_commit)


def _apply_locked(staged_id: str, *, actor: str | None, git_commit: bool) -> dict:
    """The body of `apply`, under the per-id lock. Reads the row ITSELF, so a queued second caller
    sees the state the first one left."""
    rows = _audit_list(staged_id)
    if not rows:
        return {"ok": False, "error": f"no staged publish {staged_id!r}"}
    row = rows[0]
    if row.get("status") != "staged":
        status = row.get("status")
        if status == "applied":
            return {"ok": False, "already_applied": True,
                    "error": (f"publish {staged_id} was already applied"
                              + (f" at {row.get('updated_at')}" if row.get("updated_at") else "")
                              + " — nothing to do (a second click does not reinstall it)")}
        why = "refused at stage time (see its report)" if status == "refused" else status
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
    gates = _run_gates(staged_profile, key=key)
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
    final_gates = _run_gates(installed_profile, key=key)
    if final_gates.get("fails") or not final_compile.get("compiled"):
        _restore(live, backup, existed)
        _audit_row(staged_id, key, actor, "reverted", note="post-install gates failed",
                   report={"compile": final_compile, "gates_fails": final_gates.get("fails", []),
                           "gates_text": final_gates.get("text", "")[-6000:]})
        return {"ok": False, "error": "post-install gates failed; reverted byte-for-byte",
                "report": final_gates}

    sha, git_error = None, None
    if git_commit:
        body = (f"ontology({key}): publish {staged_id}\n\n"
                f"metrics {final_compile.get('compiled', 0)} compiled, "
                f"{len(final_compile.get('refused', []))} refused by name; gates: "
                f"{'PASS' if final_gates.get('ok') else 'FAIL'}"
                + (f"; not run: {len(final_gates.get('not_run', []))}" if final_gates.get('not_run') else ""))
        sha, git_error = _git(key, body)

    # WHEN it landed. `created_at` is when it was STAGED, and the two are hours apart in practice
    # (v5 was staged twice before a working apply), so a reader asking "when did this ontology
    # publish?" cannot answer it from created_at. `updated_at` moves on every status change and would
    # be overwritten the moment the row is superseded, so the moment is written into the report too.
    applied_at = datetime.datetime.now(datetime.timezone.utc)
    _audit_row(staged_id, key, actor, "applied",
               note=("installed" if not git_error
                     else f"installed, NOT committed: {git_error}"),
               report={"compile": final_compile, "gates_ok": final_gates.get("ok"),
                       "git_commit": sha, "git_error": git_error,
                       "applied_at": applied_at.isoformat(),
                       "gates_text": final_gates.get("text", "")[-6000:]},
               git_commit=sha)
    shutil.rmtree(staging, ignore_errors=True)

    # Older staged publishes for THIS key are superseded the moment this one installs: they would
    # overlay an ALREADY INSTALLED tree with an old candidate, and until now nothing said so — the
    # settings panel kept offering every staging ever made as "waiting to be applied" (measured on
    # the deployment: 10 such rows across three ontologies, all of them stale). Record the decision
    # and drop the trees, so "pending" means exactly one thing.
    superseded = _supersede_older(key, staged_id)
    if superseded:
        logger.info("superseded %d older staged publish(es) for %s: %s", len(superseded), key, superseded)

    # 4. the running workbench keeps serving old code until it reloads
    reload_note = reload_workbench(key)
    return {"ok": True, "staged_id": staged_id, "key": key, "git_commit": sha,
            "git_error": git_error,
            "applied_at": applied_at.isoformat(),
            "workbench_reloaded": reload_note == "", "reload_note": reload_note,
            "report": {"compile": final_compile, "gates_ok": final_gates.get("ok"),
                       "gates_fails": final_gates.get("fails", []),
                       "gates_not_run": final_gates.get("not_run", [])}}


def _supersede_older(key: str, keep: str) -> list[str]:
    """Mark every staged publish for `key` older than `keep` as superseded and drop its tree.

    The ledger is the record, the tree is the candidate: both have to move together, or a stale
    candidate outlives the decision that made it stale.
    """
    done: list[str] = []
    staging = _staging_dir(key)
    for row in history(key=key, limit=200):
        sid = row.get("id")
        if not sid or sid == keep or row.get("status") != "staged":
            continue
        shutil.rmtree(staging / sid, ignore_errors=True)
        _audit_row(sid, key, row.get("actor"), "superseded", note="superseded by a newer publish",
                   report=row.get("report") or {})
        done.append(sid)
    return done


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


def diff(staged_id: str, max_chars: int = 20000) -> dict:
    """What this publish would CHANGE: a per-file unified diff, installed vs staged.

    A publish report says "gates PASS, 20 compiled, 3 carried refusals" — true and useless to a
    reviewer who has to decide whether a number's meaning changes. The unit is the file, because
    that is the unit a publish installs; each file comes back with its own diff so a reviewer can
    read the one that matters and skip the build report that came along.

    Read-only, and it works for refused publishes too (a candidate that will not install is
    exactly what someone wants to look at). Nothing here runs the compiler or the database.
    """
    import difflib

    rows = _audit_list(staged_id)
    if not rows:
        return {"ok": False, "error": f"no publish {staged_id!r}"}
    row = rows[0]
    key = row["key"]
    staging = _staging_dir(key) / staged_id
    live = ONTOLOGIES / key
    if not staging.is_dir():
        return {"ok": False, "error": f"the staging dir for {staged_id} is gone "
                                      f"(applied, discarded, or cleaned up)",
                "files": [], "staged_id": staged_id, "key": key}

    files: list[dict] = []
    budget = max_chars
    for staged_file in sorted(staging.rglob("*")):
        if not staged_file.is_file():
            continue
        rel = staged_file.relative_to(staging)
        if rel.parts and rel.parts[0] in (".staging", ".backup"):
            continue
        rel_str = str(rel).replace("\\", "/")
        live_file = live / rel
        try:
            new_text = staged_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            files.append({"path": rel_str, "status": "binary", "diff": ""})
            continue
        old_text = ""
        existed = live_file.is_file()
        if existed:
            try:
                old_text = live_file.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                files.append({"path": rel_str, "status": "binary", "diff": ""})
                continue
        if existed and old_text == new_text:
            files.append({"path": rel_str, "status": "unchanged", "added": 0, "removed": 0,
                          "diff": ""})
            continue
        old_lines = old_text.splitlines(keepends=True)
        new_lines = new_text.splitlines(keepends=True)
        text = "".join(difflib.unified_diff(
            old_lines, new_lines,
            fromfile=f"a/{rel_str}" if existed else "/dev/null",
            tofile=f"b/{rel_str}",
            n=3,
        ))
        added = sum(1 for line in text.splitlines() if line.startswith("+") and not line.startswith("+++"))
        removed = sum(1 for line in text.splitlines() if line.startswith("-") and not line.startswith("---"))
        status = "added" if not existed else "changed"
        if budget > 0:
            clipped = text[:budget]
            budget -= len(clipped)
            if len(clipped) < len(text):
                clipped += "\n… diff truncated (open the file in the staging tree to see the rest)\n"
            text_out = clipped
        else:
            text_out = "… diff omitted (this publish is larger than the diff budget; read the files)"
        files.append({"path": rel_str, "status": status, "added": added, "removed": removed,
                      "diff": text_out})

    # files the publish does not carry can no longer be deleted by it: the staging tree starts as
    # a copy, so a missing live file is a file the installed ontology never had — report both
    # directions honestly rather than implying a full-tree sync.
    removed_paths = []
    if live.is_dir():
        for live_file in sorted(live.rglob("*")):
            if not live_file.is_file():
                continue
            rel = live_file.relative_to(live)
            if rel.parts and rel.parts[0] in (".staging", ".backup"):
                continue
            if not (staging / rel).exists():
                removed_paths.append(str(rel).replace("\\", "/"))

    return {"ok": True, "staged_id": staged_id, "key": key, "status": row.get("status"),
            "files": files, "not_in_staging": removed_paths,
            "changed": [f["path"] for f in files if f["status"] in ("added", "changed")]}


# ────────────────────────────────────────────── what the numbers do
def _values_script() -> str:
    """Compile every metric of ONE profile and run it under that profile's guardrails."""
    return r"""
import json, os, pathlib, sys
sys.path.insert(0, os.environ["ONTOLOGY_COMPILER"])
prof_path = pathlib.Path(os.environ["APP_SETTINGS"])
import sqlgen, guard, actions

prof = json.loads(prof_path.read_text())
root = prof_path.resolve().parent
sqlgen.reconfigure(ns=prof.get("ns"),
                   ontology_dir=str((root / (prof.get("ontology_dir") or "ontology")).resolve()),
                   overlay=str((root / prof["overlay"]).resolve()) if prof.get("overlay") else "",
                   drop_overlay=not prof.get("overlay"))
g = sqlgen.load()
cfg = guard.config()
if isinstance(prof.get("guard"), dict):
    cfg.update({k: v for k, v in prof["guard"].items() if v is not None})

out = {}
import psycopg2
conn = psycopg2.connect(**actions.DSN)
conn.autocommit = True
for name in sorted(sqlgen.metrics(g)):
    try:
        c = sqlgen.compile_metric(g, name)
    except Exception as exc:
        out[name] = {"refused": str(exc).splitlines()[0]}
        continue
    try:
        with conn.cursor() as cur:
            r = guard.run(cur, c.sql, cfg=cfg, mode="declared")
            rows = r.get("rows") or []
            cols = r.get("cols") or []
            if rows and len(cols) > 1:
                # a GROUP BY metric has no single number: the last column of the first row plus the
                # ROW COUNT is the comparable fact. Without the count, "before None -> after 'v2'"
                # was reported for a metric whose real change was two new rows.
                out[name] = {"value": str(rows[0][-1]), "rows": len(rows), "grouped": True}
            else:
                out[name] = {"value": str(rows[0][0]) if rows and rows[0] else None}
    except Exception as exc:
        out[name] = {"error": str(exc).splitlines()[0]}
conn.close()
print(json.dumps(out, ensure_ascii=False))
"""


def _values_for(profile_path: pathlib.Path) -> dict:
    import subprocess

    env = dict(os.environ, ONTOLOGY_COMPILER=str(COMPILER), APP_SETTINGS=str(profile_path))
    try:
        p = subprocess.run([PYTHON, "-c", _values_script()], capture_output=True, text=True,
                           timeout=240, cwd=str(COMPILER), env=env)
    except Exception as exc:                                    # noqa: BLE001
        return {"__error__": f"{type(exc).__name__}: {exc}"}
    lines = (p.stdout or "").strip().splitlines()
    if not lines:
        tail = (p.stderr or "").strip().splitlines()
        return {"__error__": "the value run printed nothing"
                              + (": " + tail[-1] if tail else f" (exit {p.returncode})")}
    try:
        return json.loads(lines[-1])
    except Exception:                                           # noqa: BLE001
        return {"__error__": "the value run did not return JSON: " + lines[-1][:300]}


def value_delta(staged_id: str) -> dict:
    """Which NUMBERS this publish would move: every metric's value before and after.

    The report says gates PASS and the diff says which declarations changed — neither answers the
    question a reviewer actually has: "does the number I report change?" This runs both sides and
    diffs the values. Only metrics whose value (or refusal/error) differs are returned, with the
    rest counted, so a 23-metric ontology does not bury the one line that matters.

    Read-only: it compiles and runs SELECTs under the profile's guardrails (mode=declared, so a
    definition is never windowed). Both sides are read-only runs; nothing is written.
    """
    rows = _audit_list(staged_id)
    if not rows:
        return {"ok": False, "error": f"no publish {staged_id!r}"}
    row = rows[0]
    key = row["key"]
    staging = _staging_dir(key) / staged_id
    installed_profile = _profile_for(key)
    if not staging.is_dir():
        return {"ok": False, "error": f"the staging dir for {staged_id} is gone", "changes": []}
    staged_profile = _profile_for_staged(staging)
    if staged_profile is None:
        return {"ok": False, "error": "the staged ontology has no profile", "changes": []}
    if installed_profile is None:
        return {"ok": False, "error": "the installed ontology has no profile", "changes": []}

    before = _values_for(installed_profile)
    after = _values_for(staged_profile)
    if "__error__" in before or "__error__" in after:
        return {"ok": False, "changes": [],
                "error": before.get("__error__") or after.get("__error__")}

    changes = []
    for name in sorted(set(before) | set(after)):
        b = before.get(name) or {}
        a = after.get(name) or {}
        bv = b.get("value", b.get("refused") or b.get("error"))
        av = a.get("value", a.get("refused") or a.get("error"))
        if bv == av and b.get("rows") == a.get("rows"):
            continue
        changes.append({
            "metric": name,
            "before": bv,
            "after": av,
            "before_rows": b.get("rows"),
            "after_rows": a.get("rows"),
            "before_state": ("value" if "value" in b else
                             "refused" if "refused" in b else "error" if "error" in b else None),
            "after_state": ("value" if "value" in a else
                            "refused" if "refused" in a else "error" if "error" in a else None),
        })
    return {"ok": True, "staged_id": staged_id, "key": key,
            "metrics": len(set(before) | set(after)),
            "changed": changes, "unchanged": len(set(before) | set(after)) - len(changes)}


def _audit_list(staged_id: str | None = None, limit: int = 50) -> list[dict]:
    try:
        _ensure_table()
        db = _db()
        try:
            from sqlalchemy import text

            sql = ("SELECT id, key, actor, status, note, report, git_commit, created_at, updated_at "
                   "FROM ontology_publishes")
            params: dict = {}
            if staged_id:
                sql += " WHERE id = :id"
                params["id"] = staged_id
            sql += " ORDER BY created_at DESC LIMIT :lim"
            params["lim"] = limit
            rows = db.execute(text(sql), params).fetchall()
            out = []
            for r in rows:
                rep = r[5] if isinstance(r[5], dict) else {}
                staged_at = r[7].isoformat() if r[7] else None
                updated_at = r[8].isoformat() if r[8] else None
                # an apply is the only status change that means "this is now what readers get"
                # only a landed publish has an apply time: a reverted one never became what readers get
                applied_at = (rep.get("applied_at") or updated_at) if r[3] == "applied" else None
                out.append({"id": r[0], "key": r[1], "actor": r[2], "status": r[3],
                            "note": r[4], "report": rep, "git_commit": r[6],
                            "created_at": staged_at, "staged_at": staged_at,
                            "updated_at": updated_at, "applied_at": applied_at})
            return out
        finally:
            db.close()
    except Exception as exc:                                    # noqa: BLE001
        logger.warning("ontology publish audit read failed: %s", exc)
        return []


def history(key: str | None = None, limit: int = 50) -> list[dict]:
    rows = _audit_list(limit=limit)
    return [r for r in rows if not key or r["key"] == key]

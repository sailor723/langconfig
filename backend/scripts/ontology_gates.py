#!/usr/bin/env python3
"""Run every ontology gate, for every ontology, and say what holds.

    python -m scripts.ontology_gates                 # all profiles, all gates
    python -m scripts.ontology_gates --key logistics --key clinic
    python -m scripts.ontology_gates --quick         # skip the DSL/slow families
    python -m scripts.ontology_gates --json          # machine-readable

Why one entry point. The gates are thirteen separate scripts, each written for a question
("does every metric compile", "does every tutorial step prove itself", "does the API layer answer the
same as the compiler"). Run by hand they are easy to forget and impossible to run on a deployed box
where nobody remembers the paths. This runs them all and reports ONE verdict — the same verdict a
deploy check and a CI job can both ask for.

A gate that reports `NOT RUN` is NOT a failure: the house rule is that an unrun gate is named, never
counted as green. Such a family is printed as `NOT RUN` and does not fail the run. What fails is
`SOME CHECKS FAILED` or a crash — and the failing check's own words are carried through, because a
summary that says "gate red" without the sentence is a summary nobody can act on.

Exit: 0 everything that ran held; 1 something failed; 2 the runner itself could not start.
"""
from __future__ import annotations

import argparse
import re
import json
import os
import pathlib
import subprocess
import sys
import time

BACKEND = pathlib.Path(__file__).resolve().parents[1]
FEATURE = BACKEND / "features" / "ontology"
GATES = FEATURE / "gates"
PROFILES = FEATURE / "profiles"
#: A family that needs the SERVED app rather than the checkout lives in `scripts/` (`check_chapters` reads
#: the endpoints out of the chapter pages themselves, so it must talk to the running app). Both dirs are
#: searched, so a declaration can name either kind of gate.
SCRIPT_DIRS = (GATES, BACKEND / "scripts")

#: Which gate families hold for which ontology is a DECLARATION (features/ontology/gates.json), not a
#: convention in this file: retail's expectations are not the build track's, and a family that does not
#: apply must be absent from the declaration rather than silently skipped here.
DECLARATION = FEATURE / "gates.json"


def _declaration() -> dict:
    try:
        return json.loads(DECLARATION.read_text(encoding="utf-8"))
    except Exception:                                          # noqa: BLE001
        return {}


def _profile_of(key: str) -> pathlib.Path | None:
    for name in (f"{key}_settings.json", "settings.json"):
        candidate = PROFILES / key / name
        if candidate.is_file():
            return candidate
    return None


def _keys() -> list[str]:
    """Every key the suite has to speak about: the installed ones, plus the DECLARED ones.

    A declaration claims that a key is covered, so a declared key with no profile must not be
    silently absent from the run — that is the same failure as an installed key with no
    declaration, seen from the other side. Measured on `new_coldchain_v7` (declared, no profile yet):
    the suite printed nothing about it at all, which also made the `pending_install` branch below
    unreachable and therefore dead.
    """
    installed = {d.name for d in PROFILES.iterdir()
                 if d.is_dir() and _profile_of(d.name) is not None}
    declared = {k for k, v in _declaration().items()
                if not k.startswith("_") and isinstance(v, dict)}
    return sorted(installed | declared)


def _script(name: str) -> pathlib.Path | None:
    for d in SCRIPT_DIRS:
        candidate = d / f"{name}.py"
        if candidate.is_file():
            return candidate
    return None


def _python() -> str:
    """The interpreter that has rdflib + psycopg2: this one, unless told otherwise."""
    return os.environ.get("ONTOLOGY_PYTHON") or sys.executable


def _verdict(text: str, code: int) -> str:
    """pass | notrun | fail — decided by the gate's own words, not by its exit code.

    `check_clinic` exits 1 because its SPARQL lane is NOT RUN (no R2RML mapping for that dataset):
    the family passed, the lane is named, and calling that a deployment failure would teach people to
    ignore the runner.
    """
    if "SOME CHECKS FAILED" in text or "GATES FAILED" in text or code not in (0, 1):
        return "fail"
    # A gate that reports its own score can fail WITHOUT that sentence: `check_dashboard` prints
    # "98 checks, 8 failed" and nothing else, so "NOT RUN" anywhere in its output used to decide the
    # verdict — a gate with eight real failures was filed as `notrun` and the suite exited 0. Measured
    # on new_coldchain_v6 after a publish added KPI cards for bare-ratio metrics.
    if re.search(r"\b[1-9][0-9]* failed\b", text):
        return "fail"
    if "NOT RUN" in text:
        return "notrun"
    if code == 0 or "ALL PASS" in text or "GATES PASS" in text:
        return "pass"
    return "fail"


def _database_state(profile: pathlib.Path) -> tuple[str, str]:
    """(dbname, "") when this profile's database answers, else (dbname, why-not).

    An ontology whose database is not on this box cannot be gated, and that is a NAMED `NOT RUN` —
    not a red. Measured on the ECS migration: the box hosts langconfig/new_coldchain/tpch, so
    `check_abc` and `check_clinic` both failed with "database does not exist", which reads as "this
    deploy is broken" about two ontologies that simply live on another machine. The suite must say
    which database is missing; the refusal to guess is the product, the mis-attributed red is not.
    """
    try:
        import json as _json
        settings = _json.loads(profile.read_text(encoding="utf-8"))
    except Exception as exc:                                     # noqa: BLE001
        return ("", f"the profile cannot be read: {exc}")
    sys.path.insert(0, str(GATES.parent / "compiler"))
    try:
        import dsn as _dsn                                       # noqa: PLC0415
        conn_args = _dsn.resolved(settings)
    except Exception as exc:                                     # noqa: BLE001
        return ("", f"the profile's DSN cannot be resolved: {exc}")
    dbname = str(conn_args.get("dbname") or "")
    try:
        import psycopg2                                          # noqa: PLC0415
        conn = psycopg2.connect(connect_timeout=5, **conn_args)
        try:
            cur = conn.cursor()
            cur.execute("select 1")
            cur.fetchone()
        finally:
            conn.close()
        return (dbname, "")
    except Exception as exc:                                     # noqa: BLE001
        first = str(exc).strip().splitlines()[0][:160] if str(exc).strip() else type(exc).__name__
        return (dbname, first)


def _run(script: pathlib.Path, args: list[str], timeout: int = 900) -> dict:
    started = time.time()
    try:
        p = subprocess.run([_python(), str(script), *args], capture_output=True, text=True,
                           timeout=timeout, cwd=str(GATES))
    except subprocess.TimeoutExpired:
        return {"gate": script.stem, "verdict": "fail", "ms": timeout * 1000,
                "reason": f"did not finish in {timeout}s", "lines": []}
    text = (p.stdout or "") + (p.stderr or "")
    verdict = _verdict(text, p.returncode)
    failures = [ln.strip() for ln in text.splitlines() if "[FAIL]" in ln]
    not_run = [ln.strip() for ln in text.splitlines() if "NOT RUN" in ln]
    summary = next((ln.strip() for ln in reversed(text.splitlines())
                    if "checks," in ln or "ALL PASS" in ln or "GATES PASS" in ln
                    or "SOME CHECKS FAILED" in ln), "")
    return {"gate": script.stem, "args": args, "verdict": verdict,
            "ms": round((time.time() - started) * 1000), "summary": summary,
            "failures": failures[:6], "not_run": not_run[:4],
            "reason": "" if verdict != "fail" else (failures[0] if failures else summary[-300:])}


def _load_deployment_env() -> None:
    """Give the gates the same environment the SERVICE has.

    Measured on the ECS deploy: `check_tpch` compared against retail's database and failed with
    "port 15432 refused" while the running app was fine — because the app's systemd unit loads
    `/root/langconfig/.env` (which sets ONTOLOGY_DB_PORT=5432) and a CLI gate did not. A suite that
    measures a different environment than the app is measuring the wrong thing.
    """
    env = GATES.parents[3] / ".env"          # backend/features/ontology/gates → <repo>/.env
    if not env.is_file():
        return
    try:
        for raw in env.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key and key not in os.environ:
                os.environ[key] = value.strip().strip('"').strip("'")
    except Exception:                                            # noqa: BLE001
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--key", action="append", help="only these ontologies (repeatable)")
    ap.add_argument("--quick", action="store_true", help="skip the slow families (NL + samples)")
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--only", action="append", help="only these gate scripts (repeatable)")
    args = ap.parse_args()

    if not GATES.is_dir():
        print(f"no gates at {GATES}", file=sys.stderr)
        return 2
    keys = args.key or _keys()
    if not keys:
        print(f"no ontology profiles under {PROFILES}", file=sys.stderr)
        return 2

    _load_deployment_env()
    declaration = _declaration()
    runs: list[dict] = []
    for key in keys:
        spec = declaration.get(key)
        if not isinstance(spec, dict):
            runs.append({"gate": f"{key}:declaration", "verdict": "fail",
                         "reason": f"{key} has no gate declaration in {DECLARATION.name} — a family "
                                   f"that is not declared is not one that passed"})
            continue
        profile = _profile_of(key)
        # The ontology's DATABASE decides whether anything here can be gated at all.
        db_missing = ""
        if profile is not None:
            dbname, why = _database_state(profile)
            if why:
                db_missing = (f"{key}: its database {dbname or '(unresolved)'} does not answer on this "
                              f"host — {why}. The ontology is installed but its data is elsewhere, so "
                              f"its gates are NOT RUN here rather than red.")
        if db_missing:
            for name in (spec.get("standalone") or []) + (spec.get("profile") or []):
                if args.only and name not in args.only:
                    continue
                runs.append({"gate": f"{key}:{name}", "verdict": "notrun", "reason": db_missing})
            continue
        for name in spec.get("standalone") or []:
            if args.only and name not in args.only:
                continue
            script = _script(name)
            if script is not None:
                runs.append(_run(script, []))
            else:
                runs.append({"gate": f"{key}:{name}", "verdict": "fail",
                             "reason": f"declared gate script missing: {name}.py"})
        for name in spec.get("profile") or []:
            if args.only and name not in args.only:
                continue
            if args.quick and name in ("check_samples", "check_nl"):
                continue
            if profile is None:
                # A key that is STAGED BUT NOT INSTALLED has no profile to gate yet. That is a
                # named NOT RUN, not a failure: the staged publish already re-ran the suite on its
                # staging copy and reported the verdict (see gates.json `pending_install`).
                if spec.get("pending_install"):
                    runs.append({"gate": f"{key}:{name}", "verdict": "notrun",
                                 "reason": f"{key} is staged, not installed — {spec['pending_install']}"})
                else:
                    runs.append({"gate": f"{key}:{name}", "verdict": "fail",
                                 "reason": f"{key} declares {name} but has no profile file"})
                continue
            script = _script(name)
            if script is None:
                runs.append({"gate": f"{key}:{name}", "verdict": "fail",
                             "reason": f"declared gate script missing: {name}.py"})
                continue
            runs.append(_run(script, ["--profile", str(profile)]))

    failed = [r for r in runs if r["verdict"] == "fail"]
    notrun = [r for r in runs if r["verdict"] == "notrun"]

    if args.as_json:
        print(json.dumps({"ok": not failed, "ontologies": keys, "runs": runs,
                          "failed": len(failed), "not_run": len(notrun)}, ensure_ascii=False,
                         indent=1))
    else:
        print(f"ONTOLOGY GATES · {len(keys)} ontolog{'y' if len(keys) == 1 else 'ies'} · "
              f"{len(runs)} gate runs\n")
        for r in runs:
            mark = {"pass": "PASS  ", "notrun": "NOTRUN", "fail": "FAIL  "}[r["verdict"]]
            label = r["gate"] + ("" if not r.get("args") else " · " + " ".join(
                a for a in r["args"] if not a.endswith(".json")))
            print(f"  {mark} {label:44s} {r.get('summary', r.get('reason', ''))[:60]}")
            for line in r.get("failures") or []:
                print(f"         {line[:150]}")
            for line in r.get("not_run") or []:
                print(f"         · {line[:140]}")
        print(f"\n{len(runs)} runs · {len(failed)} failed · {len(notrun)} with NOT RUN items")
        known = [(key, note) for key, spec in declaration.items()
                 if isinstance(spec, dict) for note in (spec.get("known_failures") or [])]
        if known:
            print("\nKNOWN FAILURES (declared, so they cannot hide as green):")
            for key, note in known:
                print(f"  {key}: {note[:200]}")
        if failed:
            print("\nFAILED (a deploy must not pass):")
            for r in failed:
                print(f"  {r['gate']}: {r.get('reason', '')[:200]}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())

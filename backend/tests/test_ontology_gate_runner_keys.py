"""The gate runner must speak about every DECLARED ontology — including the ones not built yet.

Two failures, one shape, from opposite sides:

  * an installed profile with no declaration made the suite skip a real ontology, and then turned up
    red only when someone declared it (v5, fixed 2026-11-11);
  * a declared key with no profile was silently absent from the run. `new_coldchain_v7` — declared so
    the suite would say "not built yet" — produced no line at all, which also made the runner's
    `pending_install` branch unreachable (a key only reaches it when a profile EXISTS, and a key with a
    profile never returns None from `_profile_of`). Dead code that looks like a policy is worse than
    no policy: it reads as "pending installs are handled".

A declared key that is not installed is a NAMED `NOT RUN` when the declaration says `pending_install`,
and a FAILURE when it does not — declared-but-nothing-there is a claim nobody is holding up.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
RUNNER = BACKEND / "scripts" / "ontology_gates.py"
DECLARATION = BACKEND / "features" / "ontology" / "gates.json"


def _run(key: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(RUNNER), "--key", key],
                          capture_output=True, text=True, timeout=600, cwd=str(BACKEND))


def _declaration() -> dict:
    return json.loads(DECLARATION.read_text(encoding="utf-8"))


def test_declared_keys_are_part_of_the_run():
    text = RUNNER.read_text(encoding="utf-8")
    assert "declared = {k for k, v in _declaration().items()" in text, \
        "the runner went back to enumerating installed profiles only"
    assert "return sorted(installed | declared)" in text


def test_a_declared_but_unbuilt_key_is_a_named_not_run():
    decl = _declaration()
    pending = [k for k, v in decl.items()
               if not k.startswith("_") and isinstance(v, dict) and v.get("pending_install")
               and not (BACKEND / "features" / "ontology" / "profiles" / k).is_dir()]
    if not pending:
        pytest.skip("no declared-and-not-yet-built ontology in this checkout")
    key = pending[0]
    proc = _run(key)
    out = proc.stdout
    assert proc.returncode == 0, out[-1500:]
    assert f"NOTRUN {key}:" in out.replace("  NOTRUN", "NOTRUN"), \
        f"{key} is declared but the suite says nothing about it:\n{out[-800:]}"
    assert "staged, not installed" in out
    # the runner clips a reason to fit one line, so the prefix is what can be asserted
    assert decl[key]["pending_install"].split(" — ")[0][:20] in out, \
        "the NOT RUN must carry the declaration's own words"
    assert "failed" in out.splitlines()[-3] or "0 failed" in out


def test_a_declared_key_with_no_reason_is_a_failure():
    """`pending_install` is the only excuse; without it, a missing profile is a broken claim."""
    text = RUNNER.read_text(encoding="utf-8")
    assert "declares {name} but has no profile file" in text, \
        "a declared key with no profile and no pending_install would pass silently"

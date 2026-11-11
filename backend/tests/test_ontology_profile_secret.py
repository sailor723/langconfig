"""A declaration may not carry a credential — and the gate that reads it may not print one.

Measured on `retail`: `profiles/retail/settings.json` said

    "dsn": {"host": "…", "port": 15432, "dbname": "retail_db", "user": "postgres",
            "password": "postgres"}

in plain text, committed, while every gate stayed green — X1 only scanned for machine PATHS, because a
path was the failure that had already bitten (a laptop venv on the ECS box). A password is the same
disease with a worse prognosis: it travels in git and is in every clone.

The same gate then printed the resolved dsn back into its own output, so the credential also landed in
build reports and agent transcripts.

Both are guarded here: X2 refuses a literal and X2b proves the scanner can fail; the printed dsn is
masked while the real string still connects.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
GATE = BACKEND / "features" / "ontology" / "gates" / "check_ontology_generic.py"
PROFILES = BACKEND / "features" / "ontology" / "profiles"


def _x_family(profile: Path) -> str:
    proc = subprocess.run(
        [sys.executable, str(GATE), "--profile", str(profile), "--family", "X"],
        capture_output=True, text=True, timeout=300, cwd=str(BACKEND))
    return proc.stdout + proc.stderr


SOURCE = PROFILES / "logistics" / "logistics_settings.json"


def _profile_with(tmp: Path, **dsn_overrides) -> Path:
    """A real profile with one field changed.

    A synthetic three-line profile cannot run this family: the gate connects to the database before it
    gets to portability, so the probe has to be an ontology that actually connects on this box. Cloning
    logistics and changing only `dsn` keeps the rest of the run honest.
    """
    if not SOURCE.is_file():
        pytest.skip("no logistics profile to clone")
    doc = json.loads(SOURCE.read_text(encoding="utf-8"))
    doc["dsn"] = {**(doc.get("dsn") or {}), **dsn_overrides}
    (tmp / "ontology").mkdir(parents=True, exist_ok=True)
    for ttl in (SOURCE.parent / "ontology").glob("*.ttl"):
        (tmp / "ontology" / ttl.name).write_bytes(ttl.read_bytes())
    path = tmp / "probe_settings.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


# ── the rule ────────────────────────────────────────────────────────────────

def test_x2_is_declared_in_the_gate():
    text = GATE.read_text(encoding="utf-8")
    assert "X2 no declaration carries a literal password" in text
    assert "X2b the credential scanner fails on a literal" in text, \
        "a scanner nobody proved can fail is decoration"
    assert "def masked_dsn" in text, "the gate prints the dsn; the password must not be in it"


# ── behaviour ───────────────────────────────────────────────────────────────

def test_a_literal_password_is_refused(tmp_path):
    profile = _profile_with(tmp_path, password="hunter2")
    out = _x_family(profile)
    if "cannot connect" in out or "OperationalError" in out:
        pytest.skip("the logistics database is not reachable from this checkout")
    assert "[FAIL] X2" in out, out[-1200:]
    assert "literal password" in out


def test_an_env_reference_is_accepted(tmp_path):
    profile = _profile_with(tmp_path, password="${ONTOLOGY_DB_PASSWORD:-}")
    out = _x_family(profile)
    if "cannot connect" in out or "OperationalError" in out:
        pytest.skip("the logistics database is not reachable from this checkout")
    assert "[PASS] X2" in out, out[-1200:]
    assert "[PASS] X2b" in out


def test_no_installed_profile_prints_its_password():
    """Every profile the repo ships must answer X2 green, and its printed dsn must be masked."""
    if not PROFILES.is_dir():
        pytest.skip("no ontology profiles in this checkout")
    offenders, printed = [], []
    for profile in sorted(PROFILES.glob("*/settings.json")) + sorted(PROFILES.glob("*/*_settings.json")):
        out = _x_family(profile)
        if "[FAIL] X2" in out:
            offenders.append(profile.parent.name)
        for line in out.splitlines():
            if line.startswith("dsn:") and "password=" in line and "password=<set>" not in line:
                printed.append(f"{profile.parent.name}: {line.strip()}")
    assert not offenders, f"these profiles carry a literal password: {offenders}"
    assert not printed, "a gate printed the password it read:\n" + "\n".join(printed)

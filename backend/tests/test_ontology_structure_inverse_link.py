"""A link may be declared on its INVERSE edge — and only when the inverse is fully declared.

The structure gate demanded `:physicalColumn` + `:references` on every object property. logistics'
`:decisionsOf` (the readable direction, `Trip → DispatchDecision`) correctly names neither: the foreign
key is `dispatch_decisions.trip_id`, so the column cannot exist on `trips`. The declaration says so —
`owl:inverseOf :decidedTripOf`, and THAT property carries `:physicalColumn "trip_id" ; :references :Trip`.

Refusing it made a true declaration red for days. Accepting it unconditionally would be worse: rule 2 of
the skill ("a link is declared, never inferred") is exactly what this gate protects, so the exemption is
only allowed when the inverse itself names a column that really exists on the read table. Both halves are
checked here: the pass, and the refusal when the inverse is incomplete.

The live tests need the logistics profile's database (`abc_coldchain` on this machine); they skip
elsewhere rather than pretending.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
GATE = BACKEND / "features" / "ontology" / "gates" / "check_structure.py"
LOGISTICS = BACKEND / "features" / "ontology" / "profiles" / "logistics"


def _run(profile: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(GATE), "--profile", str(profile)],
                          capture_output=True, text=True, timeout=300, cwd=str(BACKEND))


def _db_reachable() -> bool:
    """The gate prints `cannot connect` and exits 2 when the database is not there."""
    if not (LOGISTICS / "logistics_settings.json").is_file():
        return False
    proc = _run(LOGISTICS / "logistics_settings.json")
    return proc.returncode != 2


# ── the rule in the source ─────────────────────────────────────────────────

def test_the_gate_reads_owl_inverse_of():
    text = GATE.read_text(encoding="utf-8")
    assert "OWL.inverseOf" in text, "the inverse-edge rule is gone"
    assert "is declared on its inverse edge" in text, "the pass is not named, so nobody can grep for it"


def test_the_exemption_requires_the_inverse_to_be_complete():
    """A property with neither a column nor a complete inverse must still be refused."""
    text = GATE.read_text(encoding="utf-8")
    block = text[text.index("A LINK MAY BE DECLARED ON ITS INVERSE EDGE"):]
    block = block[:block.index("# ── S1b2")]
    assert "pcol is not None and pref is not None" in block, \
        "the exemption no longer checks that the inverse declares both halves"
    assert "names :physicalColumn and :references" in block, \
        "the refusal for an undeclared link disappeared"


# ── behaviour, against the real profile and a mutated copy ─────────────────

def test_logistics_structure_is_green_and_the_inverse_edge_passes():
    if not _db_reachable():
        pytest.skip("the logistics database is not reachable from this checkout")
    proc = _run(LOGISTICS / "logistics_settings.json")
    out = proc.stdout
    assert proc.returncode == 0, out[-2000:]
    assert "[PASS] :decisionsOf is declared on its inverse edge" in out
    assert "0 failed" in out.splitlines()[-1] or "0 failed" in out
    assert "FAILED" not in out, out[-2000:]


def test_an_undeclared_link_is_still_refused(tmp_path):
    """Break the inverse and the gate must go red: the exemption is not a blanket allow."""
    if not _db_reachable():
        pytest.skip("the logistics database is not reachable from this checkout")

    profile_dir = tmp_path / "logistics_copy"
    (profile_dir / "ontology").mkdir(parents=True)
    shutil.copy2(LOGISTICS / "logistics_settings.json", profile_dir / "logistics_settings.json")
    for name in ("01-structure.ttl", "02-meaning.ttl"):
        shutil.copy2(LOGISTICS / "ontology" / name, profile_dir / "ontology" / name)

    structure = profile_dir / "ontology" / "01-structure.ttl"
    text = structure.read_text(encoding="utf-8")
    # remove the column from the INVERSE (`:decidedTripOf`), leaving `:decisionsOf` with nothing to
    # fall back on — the exact state the exemption must not cover
    marker = ":decidedTripOf a owl:ObjectProperty"
    start = text.index(marker)
    end = text.index(":", text.index(':businessDescription', start) + 1)
    block = text[start:end].replace(':physicalColumn "trip_id" ;', "")
    structure.write_text(text[:start] + block + text[end:], encoding="utf-8")

    proc = _run(profile_dir / "logistics_settings.json")
    out = proc.stdout
    assert proc.returncode != 0, "an incomplete inverse still passed the gate:\n" + out[-1500:]
    assert ":decisionsOf names :physicalColumn and :references" in out, out[-1500:]
    assert "incomplete too" in out, "the refusal should name the inverse it also looked at"
    assert json.loads((profile_dir / "logistics_settings.json").read_text())["dsn"]

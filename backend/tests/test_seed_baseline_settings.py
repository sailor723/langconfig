"""The baseline check must be able to say FRESH — otherwise nobody reads it.

`export_baseline.py --check` is the only thing that tells a teammate "your seed is up to date".
Its settings leg compared a hardcoded six-namespace SQL against a snapshot file that holds eight
namespaces, so every machine reported `settings 6 8 STALE: -2` forever. A check that is always
red is worse than no check: people learn to skip it, and the day it means something it is ignored.

What these tests pin down:

* the settings leg compares the snapshot's OWN namespace set (no hardcoded subset);
* it compares namespace **presence**, not row counts — one namespace may hold several documents
  (this machine has three `models` documents) while the snapshot keeps one key per namespace.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = BACKEND / "scripts/seeds/out/export_baseline.py"
SETTINGS_SEED = BACKEND / "scripts/seeds/in/settings_seed.json"


def _module():
    # the script imports its sibling `_secretscan`, so its folder must be importable
    sys.path.insert(0, str(SCRIPT.parent))
    try:
        spec = importlib.util.spec_from_file_location("export_baseline", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.path.remove(str(SCRIPT.parent))


def test_snapshot_namespaces_are_read_from_the_file():
    mod = _module()
    nss = mod.settings_namespaces(SETTINGS_SEED)
    assert nss, "settings_seed.json should declare namespaces"
    assert "agents" in nss and "models" in nss and "ontology" in nss
    assert all(not n.startswith("__") for n in nss), "__meta__ is not a namespace"


def test_settings_leg_does_not_hardcode_a_subset():
    src = SCRIPT.read_text(encoding="utf-8")
    assert "settings_namespaces(" in src, (
        "the settings leg must derive its namespace set from the snapshot")
    assert "ns IN ('agents'" not in src, (
        "a hardcoded namespace list next to a snapshot that holds more is a permanent false STALE")


def test_settings_leg_reports_missing_namespaces_by_name():
    src = SCRIPT.read_text(encoding="utf-8")
    assert "SETTINGS_MISSING" in src, (
        "a missing namespace should be named, not expressed as a row-count delta")

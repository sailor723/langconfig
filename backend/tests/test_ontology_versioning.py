"""Gates for ontology version numbering (decided 2026-11-12, option A of the builder review).

The rule a customer agreed to: they say a NAME, the platform assigns the version, and a new build
is never written over an old one. Everything below is a property that keeps that promise honest:

* the next number is one past the highest one that exists ANYWHERE — registry, `profiles/`
  directory, or a gates.json declaration — so a key registered by a hand edit still gets a free
  number;
* a number is never reused: after v3 the next build is v4, even if v3's directory was deleted;
* exactly one build per family is `latest`, and older builds point at the build that replaced
  them (v1→v2 survives the arrival of v3), so "which build is the customer running?" and "what did
  this replace?" are both a lookup;
* a key is a NAME, not a path: `../x`, `Sun Hing`, `_x` and `9abc` are refused before anything is
  created, and the profile path is contained under `profiles/`;
* recording is idempotent, because a re-run of a registration must not create v2 of nothing.

The registry file in the assertions is a temp file; the repository's own registry is only READ, by
one test that guards the real numbering stays coherent (a backfilled family whose latest build is
not its highest number would make every future `--base` registration wrong).

Run: cd backend && .venv/bin/python -m pytest tests/test_ontology_versioning.py -v
"""
from __future__ import annotations

import json
import pathlib

import pytest

from features.ontology import versioning as V

BACKEND = pathlib.Path(__file__).resolve().parents[1]
PROFILES = BACKEND / "features" / "ontology" / "profiles"


# ───────────────────────────────────────────────────────── numbering
def test_next_version_counts_directories_not_only_the_registry(tmp_path):
    """A key built before the registry existed still occupies its number."""
    for name in ("chinook_v1", "chinook_v2", "chinook_v3"):
        (tmp_path / name).mkdir()
    reg = {"families": {}}
    assert V.next_version("chinook", registry=reg, known=V.existing_keys(tmp_path)) == 4
    assert V.key_for("chinook", registry=reg, known=V.existing_keys(tmp_path)) == ("chinook_v4", 4)


def test_next_version_counts_gate_declarations(tmp_path):
    """`gates.json` names keys before their directory exists — v7 was declared and not built."""
    reg = {"families": {}}
    known = V.existing_keys(tmp_path, gate_keys={"tpe", "tpe_v7"})
    assert V.next_version("tpe", registry=reg, known=known) == 8


def test_a_number_is_never_reused_after_a_delete(tmp_path):
    """v3 removed from disk must not make the next build v3 — that is how history is rewritten."""
    (tmp_path / "sunhing_v1").mkdir()
    reg = {"families": {}}
    V.record(reg, key="sunhing_v1", kind="customer")
    assert V.key_for("sunhing", registry=reg, known=V.existing_keys(tmp_path))[0] == "sunhing_v2"
    (tmp_path / "sunhing_v2").mkdir()
    V.record(reg, key="sunhing_v2", kind="customer")       # what a registration does at build time
    # the v2 directory is deleted, but the registry remembers it
    (tmp_path / "sunhing_v2").rmdir()
    assert V.key_for("sunhing", registry=reg, known=V.existing_keys(tmp_path))[0] == "sunhing_v3"


def test_an_unversioned_key_is_version_one(tmp_path):
    """Legacy keys (`abc`, `tpch`) parse as v1 so their successor is _v2, not the same name."""
    assert V.parse_key("abc") == ("abc", 1)
    assert V.parse_key("abc_v2") == ("abc", 2)
    assert V.next_version("abc", registry={"families": {}}, known={"abc"}) == 2


# ───────────────────────────────────────────────────────── the chain
def test_a_new_version_becomes_latest_and_the_old_one_names_its_successor():
    reg = {"families": {}}
    V.record(reg, key="new_coldchain_v3", kind="customer", theme="新冷鏈")
    V.record(reg, key="new_coldchain_v4", kind="customer")
    fam = reg["families"]["new_coldchain"]
    assert fam["latest"] == "new_coldchain_v4"
    assert [v["superseded_by"] for v in fam["versions"]] == ["new_coldchain_v4", None]

    V.record(reg, key="new_coldchain_v5", kind="customer")
    by_key = {v["key"]: v for v in reg["families"]["new_coldchain"]["versions"]}
    # v3 keeps pointing at v4 (the build that replaced IT), v4 now points at v5
    assert by_key["new_coldchain_v3"]["superseded_by"] == "new_coldchain_v4"
    assert by_key["new_coldchain_v4"]["superseded_by"] == "new_coldchain_v5"
    assert by_key["new_coldchain_v5"]["superseded_by"] is None
    assert V.latest_of("new_coldchain", registry=reg) == "new_coldchain_v5"
    assert V.chain("new_coldchain_v1", registry=reg) == [
        "new_coldchain_v3", "new_coldchain_v4", "new_coldchain_v5"]


def test_re_recording_the_same_key_is_idempotent_but_refreshes_the_label():
    reg = {"families": {}}
    V.record(reg, key="sunhing_v1", kind="customer", theme="新鴻")
    V.record(reg, key="sunhing_v1", kind="customer", theme="新鴻冷鏈", datasource="sunhing_db")
    fam = reg["families"]["sunhing"]
    assert len(fam["versions"]) == 1
    assert fam["versions"][0]["theme"] == "新鴻冷鏈"
    assert fam["versions"][0]["datasource"] == "sunhing_db"
    assert fam["latest"] == "sunhing_v1"


def test_a_first_build_has_no_superseded_by():
    reg = {"families": {}}
    entry = V.record(reg, key="probe_key", kind="trial")
    assert entry["superseded_by"] is None
    assert reg["families"]["probe_key"]["latest"] == "probe_key"


# ───────────────────────────────────────────────────────── refusals
@pytest.mark.parametrize("kind", ["Customer", "temp", "", "demo "])
def test_kind_must_be_one_of_the_four(kind):
    with pytest.raises(V.VersionError):
        V.record({"families": {}}, key="x_v1", kind=kind)


@pytest.mark.parametrize("key", ["../evil", "a/b", "Sun Hing", "_x", "9abc", "", "x_v",
                                 "x_v0", "sunhing_1", "sunhing_v01"])
def test_a_key_that_is_not_a_name_is_refused(key):
    with pytest.raises(V.VersionError):
        V.parse_key(key)


def test_a_key_is_stripped_but_not_reinterpreted():
    """Whitespace around a pasted name is a typo, not a second family: strip it and move on."""
    assert V.parse_key("  sunhing_v1\n") == ("sunhing", 1)


def test_recording_refuses_a_key_that_would_start_a_second_family():
    """`sunhing_1` looks like a version and is not one; recording it splits the history in two."""
    with pytest.raises(V.VersionError):
        V.record({"families": {}}, key="sunhing_1", kind="customer")


def test_profile_dir_stays_under_profiles(tmp_path):
    assert V.profile_dir("sunhing_v1", root=tmp_path) == (tmp_path / "sunhing_v1").resolve()
    for bad in ("..", "../etc", "a/../../b", "/etc/passwd"):
        with pytest.raises(V.VersionError):
            V.profile_dir(bad, root=tmp_path)


def test_publish_refuses_a_file_that_escapes_the_ontology():
    """The builder writes through a tool whose paths come from a conversation — so does this guard."""
    from services import ontology_publish as pub  # noqa: PLC0415

    for rel in ("../outside.ttl", "/etc/passwd", "a/../../b.ttl"):
        res = pub.stage("clinic", {rel: "@prefix x: <y> ."})
        assert res["ok"] is False, rel
        assert "outside" in res["error"] or "invalid" in str(res["error"]).lower(), res


def test_registry_round_trips_and_tolerates_a_missing_file(tmp_path):
    path = tmp_path / "_versions.json"
    reg = V.load(path)
    assert reg["families"] == {}
    V.record(reg, key="sunhing_v1", kind="customer")
    V.save(reg, path)
    again = V.load(path)
    assert again["families"]["sunhing"]["latest"] == "sunhing_v1"
    # a corrupt registry is an error, not silently an empty history
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(V.VersionError):
        V.load(path)


# ───────────────────────────────────────────────────────── the repository's own numbering
def test_the_repository_registry_matches_its_directories():
    """The real backfill stays coherent: every family's `latest` is its highest version."""
    reg = V.load(PROFILES / V.REGISTRY_NAME)
    present = V.existing_keys(PROFILES)
    for base, fam in (reg.get("families") or {}).items():
        versions = fam.get("versions") or []
        assert versions, f"{base} recorded with no versions"
        top = max(int(v["version"]) for v in versions)
        if fam.get("latest") is None:
            # A family whose every build was RETIRED has no current build — `scripts/retire_ontology.py`
            # clears `latest` rather than pointing it at something that no longer exists on disk.
            # That is a state, not an inconsistency: assert the shape retirement is supposed to leave.
            assert all(v.get("retired") for v in versions), (
                f"{base}: latest is null but not every version is retired "
                f"({[v['key'] for v in versions if not v.get('retired')]})")
            continue
        latest_version = next((v for v in versions if v["key"] == fam["latest"]), None)
        assert latest_version is not None, f"{base}: latest {fam['latest']!r} is not a recorded version"
        assert int(latest_version["version"]) == top, base
        for v in versions:
            if v.get("retired"):
                continue                      # retired builds are history, not the current one
            if int(v["version"]) != top:
                assert v.get("superseded_by"), f"{base}:{v['key']} does not name its successor"
            else:
                assert not v.get("superseded_by"), f"{base}:{v['key']} is latest but superseded"
            # a recorded customer/tutorial key must still exist on disk (nothing deletes them)
            if v.get("kind") in {"customer", "tutorial"}:
                assert v["key"] in present, f"{v['key']} is {v['kind']} but has no profile directory"


def test_the_next_number_for_every_existing_family_is_free():
    """Registering any existing family again must not land on a key that is already taken."""
    reg = V.load(PROFILES / V.REGISTRY_NAME)
    known = V.existing_keys(PROFILES) | {str(k) for k in
                                         json.loads((PROFILES.parent / "gates.json")
                                                    .read_text(encoding="utf-8"))
                                         if V.KEY_RE.fullmatch(str(k))}
    for base in {V.parse_key(k)[0] for k in known}:
        key, n = V.key_for(base, registry=reg, known=known)
        assert key not in known, f"{base}: next key {key} is already taken"
        assert n >= 2, f"{base}: a family with an existing build cannot start at v1"


# ───────────────────────────────────────────────────────── the registration script itself
def _script():
    """Import `add_ontology_builder.py` by path — it is a script, not an importable module."""
    import importlib.util  # noqa: PLC0415

    path = BACKEND / "scripts" / "seeds" / "in" / "add_ontology_builder.py"
    spec = importlib.util.spec_from_file_location("add_ontology_builder_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_script_asks_for_a_name_or_a_key_but_not_both():
    """`--base` assigns a version; `--key` names one. Both or neither is a guess, so it exits 2."""
    import subprocess  # noqa: PLC0415
    import sys  # noqa: PLC0415

    script = BACKEND / "scripts" / "seeds" / "in" / "add_ontology_builder.py"
    for args in ([], ["--base", "chinook", "--key", "chinook_v1"]):
        p = subprocess.run([sys.executable, str(script), *args, "--datasource", "chinook",
                            "--skip-db-probe"], capture_output=True, text=True, cwd=str(BACKEND))
        assert p.returncode == 2, (args, p.stdout, p.stderr)
        assert "exactly one of --base" in p.stderr, p.stderr


def test_a_rebuild_of_a_family_reuses_its_password_variable():
    """A v2 reads the same database, so it must not invent SUNHING_V2_DB_PASSWORD."""
    mod = _script()
    assert mod._family_password_var("sunhing") == "SUNHING_DB_PASSWORD"
    assert mod._family_password_var("no_such_family") is None
    assert mod._env_var_for("chinook_v1") == "CHINOOK_V1_DB_PASSWORD"


def test_the_preview_agrees_with_what_the_registry_would_write(tmp_path):
    """The Settings row must not claim a version the registry does not record."""
    mod = _script()
    reg = {"families": {}}
    V.record(reg, key="chinook_v1", kind="customer")
    meta = mod._preview_version("chinook_v2", base="chinook", kind="customer", theme="音乐",
                                datasource="chinook")
    assert meta == {"version": 2, "kind": "customer", "latest": True, "superseded_by": ""}


def test_a_bad_kind_fails_the_preview_instead_of_inventing_one():
    mod = _script()
    assert mod._preview_version("chinook_v1", base="chinook", kind="Customer", theme="",
                                datasource="chinook") == {}

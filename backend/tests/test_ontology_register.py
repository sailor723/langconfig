"""Gates for `ontology_register` — the rung that turns 「这是我们的 Excel」 into a registered key.

Until this existed, the four-rung flow (file → database → ontology → dashboard) always needed a person at
a shell: a key needs a profile directory, a `gates.json` declaration, a Settings row and a version, and an
agent may not write the repository. Everything below is a failure that would put a customer's data into the
wrong ontology, or an empty one, without anyone noticing:

* the version is the platform's to assign and is never reused;
* a RETRY before the first build returns the same key — minting v2 there leaves an empty v1 forever;
* a name that is not a slug, a database that does not answer, a kind nobody defined, and a profile
  directory that already holds a build are all refused BY NAME (a silent success here is a wrong ontology);
* the skeleton does not invent decisions (no `guard.big_tables`, no `default_window_days` — those are S0/S4
  facts) and carries no literal credential (gate X2 refuses one);
* `_brief.md` records what the caller said, so a later build does not re-ask settled questions.

The repository paths are redirected to a temp tree; the Settings row is stubbed, since writing the
workbench document is not what this file is about.

Run: cd backend && .venv/bin/python -m pytest tests/test_ontology_register.py -v
"""
from __future__ import annotations

import json
import pathlib

import pytest

from services import ontology_register as R


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    """A throwaway repository tree: profiles/, gates.json, and a stubbed Settings write."""
    feature = tmp_path / "backend" / "features" / "ontology"
    (feature / "profiles").mkdir(parents=True)
    (feature / "gates.json").write_text(json.dumps({"_doc": "test"}), encoding="utf-8")
    monkeypatch.setattr(R, "FEATURE", feature)
    monkeypatch.setattr(R, "PROFILES", feature / "profiles")
    monkeypatch.setattr(R, "GATES", feature / "gates.json")
    monkeypatch.setattr(R, "REPO", tmp_path)
    monkeypatch.setattr(R, "_register_in_settings", lambda *a, **k: (True, "stubbed"))
    return tmp_path


def _register(repo, name="chinook", ds="chinook_xlsx", **kw):
    return R.register(name, ds, probe=False, **kw)


def test_the_first_registration_takes_version_one_and_writes_the_three_artefacts(repo):
    out = _register(repo)
    assert out["ok"] is True and out["key"] == "chinook_v1" and out["version"] == 1
    assert out["in_progress"] is False
    profile = repo / "backend/features/ontology/profiles/chinook_v1/chinook_v1_settings.json"
    brief = repo / "backend/features/ontology/profiles/chinook_v1/_brief.md"
    assert profile.is_file() and brief.is_file()
    gates = json.loads((repo / "backend/features/ontology/gates.json").read_text())
    assert "pending_install" in gates["chinook_v1"]
    assert gates["chinook_v1"]["profile"] == R._GATE_FAMILIES
    reg = json.loads((repo / "backend/features/ontology/profiles/_versions.json").read_text())
    assert reg["families"]["chinook"]["latest"] == "chinook_v1"
    assert reg["families"]["chinook"]["versions"][0]["kind"] == "customer"


def test_the_skeleton_carries_no_secret_and_invents_no_decisions(repo):
    _register(repo, theme="音乐零售")
    prof = json.loads((repo / "backend/features/ontology/profiles/chinook_v1/"
                       "chinook_v1_settings.json").read_text())
    assert prof["dsn"]["dbname"] == "chinook_xlsx"
    # gate X2: a profile may not carry a literal credential — the host injects ONTOLOGY_DB_*
    assert prof["dsn"]["password"] == "${ONTOLOGY_DB_PASSWORD}"
    assert prof["dsn"]["user"] == "${ONTOLOGY_DB_USER}"
    # these are DECISIONS from the build (S0/S4), not registration facts
    assert "big_tables" not in prof["guard"]
    assert "default_window_days" not in prof["guard"]
    assert prof["title"] == "音乐零售"


def test_a_retry_before_the_first_build_returns_the_same_key_not_v2(repo):
    first = _register(repo)
    again = _register(repo)
    assert again["key"] == first["key"] == "chinook_v1"
    assert again["in_progress"] is True
    assert again["wrote"] == []
    # and no v2 was minted behind the scenes
    reg = json.loads((repo / "backend/features/ontology/profiles/_versions.json").read_text())
    assert [v["key"] for v in reg["families"]["chinook"]["versions"]] == ["chinook_v1"]


def test_after_the_build_exists_the_next_registration_is_v2_and_v1_is_superseded(repo):
    first = _register(repo)
    profile_dir = repo / "backend/features/ontology/profiles" / first["key"]
    (profile_dir / "01-structure.ttl").write_text("@prefix x: <y> .\n", encoding="utf-8")
    second = _register(repo)
    assert second["key"] == "chinook_v2" and second["version"] == 2
    reg = json.loads((repo / "backend/features/ontology/profiles/_versions.json").read_text())
    by_key = {v["key"]: v for v in reg["families"]["chinook"]["versions"]}
    assert by_key["chinook_v1"]["superseded_by"] == "chinook_v2"
    assert reg["families"]["chinook"]["latest"] == "chinook_v2"


@pytest.mark.parametrize("name", ["ch inook", "chinook-1", "9chinook", "", "chinook/../x", "新鸿",
                                  "sun.hing"])
def test_a_name_that_cannot_be_a_key_is_refused_by_name(repo, name):
    """A hyphen or a Chinese name must go back to the user, not be translated into a plausible key."""
    with pytest.raises(R.RegisterError) as exc:
        _register(repo, name=name)
    assert "name" in str(exc.value).lower()


def test_case_is_normalised_because_it_is_only_a_typing_habit(repo):
    out = _register(repo, name="SunHing")
    assert out["key"] == "sunhing_v1"
    assert (repo / "backend/features/ontology/profiles/sunhing_v1").is_dir()


@pytest.mark.parametrize("ds", ["", "chinook xlsx", "../postgres", "chinook;drop"])
def test_a_datasource_that_is_not_a_database_name_is_refused(repo, ds):
    with pytest.raises(R.RegisterError):
        _register(repo, ds=ds)


def test_an_unknown_kind_is_refused(repo):
    with pytest.raises(R.RegisterError) as exc:
        _register(repo, kind="Customer")
    assert "kind" in str(exc.value)


def test_a_profile_directory_with_content_is_never_overwritten(repo):
    """A key with files belongs to a build that ran; re-registering over it would rewrite its history."""
    target = repo / "backend/features/ontology/profiles/chinook_v1"
    target.mkdir(parents=True)
    (target / "01-structure.ttl").write_text("@prefix x: <y> .\n", encoding="utf-8")
    # pretend the registry does not know about it (the case a hand-made directory can produce)
    (repo / "backend/features/ontology/profiles/_versions.json").write_text(
        json.dumps({"families": {}}), encoding="utf-8")
    out = _register(repo)
    assert out["key"] == "chinook_v2", out


def test_a_database_that_does_not_answer_is_refused(repo):
    with pytest.raises(R.RegisterError) as exc:
        R.register("chinook", "definitely_not_a_database_xyz", probe=True)
    assert "does not answer" in str(exc.value)


def test_the_brief_records_what_the_caller_said(repo):
    _register(repo, theme="音乐零售", actor="agent 393")
    brief = (repo / "backend/features/ontology/profiles/chinook_v1/_brief.md").read_text()
    assert "音楽" not in brief and "音乐零售" in brief
    assert "chinook_xlsx" in brief and "agent 393" in brief
    # it says plainly that it is an input, not a declaration
    assert "输入" in brief


def test_a_settings_failure_is_reported_but_the_files_still_count(repo, monkeypatch):
    monkeypatch.setattr(R, "_register_in_settings",
                        lambda *a, **k: (False, "Settings row NOT written (boom)"))
    out = _register(repo)
    assert out["ok"] is True and out["settings_written"] is False
    assert "NOT written" in out["settings"]
    assert out["wrote"], "the file artefacts are the record"

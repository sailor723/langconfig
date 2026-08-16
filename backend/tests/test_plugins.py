# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for the LangChain-style declarative plugin system (core/plugins)."""

import json
import tempfile
from pathlib import Path

import pytest

from core.plugins import get_plugin_loader
from core.plugins.loader import PluginLoader


def _make_plugin(root: Path, name: str, with_scripts: bool = True) -> Path:
    """Create a minimal plugin directory under `root`."""
    pdir = root / name
    (pdir / "skills" / name).mkdir(parents=True)
    (pdir / "plugin.json").write_text(json.dumps({
        "name": name,
        "version": "1.0.0",
        "description": f"{name} test plugin",
        "skills": "./skills",
    }), encoding="utf-8")
    (pdir / "skills" / name / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Test skill\n---\n\n# {name}\n",
        encoding="utf-8",
    )
    if with_scripts:
        (pdir / "skills" / name / "scripts").mkdir()
        (pdir / "skills" / name / "scripts" / "helper.py").write_text(
            "print('hi')\n", encoding="utf-8",
        )
    return pdir


def test_loader_discovers_plugin_and_marketplace(tmp_path):
    _make_plugin(tmp_path, "demo")
    (tmp_path / "marketplace.json").write_text(json.dumps({
        "name": "test-market",
        "plugins": [{"name": "demo", "source": "./demo"}],
    }), encoding="utf-8")

    loader = PluginLoader(root=str(tmp_path))
    plugins = loader.list_plugins()
    assert len(plugins) == 1
    assert plugins[0]["name"] == "demo"
    assert plugins[0]["plugin_id"] == "demo@test-market"
    assert plugins[0]["components"]["skills"] == ["demo"]

    plugin = loader.get_plugin("demo")
    assert plugin is not None
    assert plugin.skill_dirs[0].name == "demo"
    # scripts bundled
    assert (plugin.skill_dirs[0] / "scripts" / "helper.py").is_file()


def test_loader_resolves_namespaced_id(tmp_path):
    _make_plugin(tmp_path, "demo")
    (tmp_path / "marketplace.json").write_text(json.dumps({
        "name": "test-market",
        "plugins": [{"name": "demo", "source": "./demo"}],
    }), encoding="utf-8")

    loader = PluginLoader(root=str(tmp_path))
    assert loader.get_plugin("demo@test-market") is not None
    assert loader.get_plugin("missing") is None
    assert loader.get_plugin("demo@other-market") is None


def test_stage_plugin_skills_namespaced(tmp_path):
    _make_plugin(tmp_path, "demo")
    loader = PluginLoader(root=str(tmp_path))
    plugin = loader.get_plugin("demo")

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "skills"
        staged = loader.stage_plugin_skills([plugin], target, namespace="plugins")
        assert staged == ["plugins/demo/demo"]
        staged_skill = target / "plugins" / "demo" / "demo"
        assert (staged_skill / "SKILL.md").is_file()
        assert (staged_skill / "scripts" / "helper.py").is_file()


def test_manifest_rejects_path_escape(tmp_path):
    pdir = _make_plugin(tmp_path, "demo")
    (pdir / "plugin.json").write_text(json.dumps({
        "name": "demo",
        "skills": "../outside",
    }), encoding="utf-8")
    loader = PluginLoader(root=str(tmp_path))
    plugin = loader.get_plugin("demo")
    # Escaping path resolves to None (safe), not outside the root.
    assert plugin.skills_dir is None or plugin.skills_dir.is_relative_to(pdir.resolve())


def test_manifest_rejects_bad_name(tmp_path):
    pdir = tmp_path / "bad name"
    pdir.mkdir()
    (pdir / "plugin.json").write_text(json.dumps({"name": "bad name"}), encoding="utf-8")
    loader = PluginLoader(root=str(tmp_path))
    assert loader.list_plugins() == []


def test_get_plugin_loader_singleton():
    loader1 = get_plugin_loader()
    loader2 = get_plugin_loader()
    assert loader1 is loader2

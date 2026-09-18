# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Plugin loader — discovers, parses, and stages LangChain-style plugins.

A plugin is a directory under a plugins root (``backend/plugins`` by default)
containing ``plugin.json`` and optional ``skills/``, ``.mcp.json``, and
``hooks`` components. The loader:

- discovers plugin directories and parses their manifests,
- validates component paths stay inside the plugin root,
- stages a plugin's skills into a target skills directory (namespaced under
  the plugin name, matching Deep Agents Code's ``plugin:skill`` namespacing),
- exposes MCP server configs and hook configs for the agent assembly seams.

Plugins contribute NO UI and NO endpoint — they are capability capsules
mounted into agents at build time (the LangConfig analog of
``PluginSkillsMiddleware`` / ``plugin_mcp_server_entries`` in deepagents-code).
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import MANIFEST_CANDIDATES, MARKETPLACE_CANDIDATES, PluginManifest

logger = logging.getLogger(__name__)

# Default plugin roots (checked in order; the first existing one wins).
DEFAULT_PLUGIN_ROOTS = [
    Path(__file__).resolve().parents[3] / "plugins",          # backend/plugins
    Path(__file__).resolve().parents[2] / "plugins",          # core/../plugins
]


def _resolve_plugins_root(configured: Optional[str] = None) -> Optional[Path]:
    """Return the plugin root directory (first existing candidate)."""
    if configured:
        p = Path(configured)
        return p if p.is_dir() else None
    for cand in DEFAULT_PLUGIN_ROOTS:
        if cand.is_dir():
            return cand
    return None


class Plugin:
    """A loaded, validated plugin directory."""

    def __init__(self, root: Path, manifest: PluginManifest, marketplace: Optional[str] = None):
        self.root = root
        self.manifest = manifest
        self.marketplace = marketplace

    # ── identity ────────────────────────────────────────────────────────
    @property
    def name(self) -> str:
        return self.manifest.name

    @property
    def version(self) -> str:
        return self.manifest.version

    @property
    def description(self) -> str:
        return self.manifest.description

    @property
    def plugin_id(self) -> str:
        """Canonical id: name@marketplace (or bare name without a marketplace)."""
        if self.marketplace:
            return f"{self.name}@{self.marketplace}"
        return self.name

    # ── components ──────────────────────────────────────────────────────
    @property
    def skills_dir(self) -> Optional[Path]:
        """The plugin's skills/ directory (None when not present)."""
        declared = self.manifest.skills_path
        if declared:
            return self._safe_path(declared)
        root_skills = self.root / "skills"
        return root_skills if root_skills.is_dir() else None

    @property
    def skill_dirs(self) -> List[Path]:
        """Skill directories (each containing SKILL.md) inside this plugin."""
        base = self.skills_dir
        if base is None or not base.is_dir():
            return []
        found = []
        for child in sorted(base.iterdir()):
            if child.is_dir() and (child / "SKILL.md").is_file():
                found.append(child)
        return found

    @property
    def mcp_config(self) -> Optional[Dict[str, Any]]:
        """MCP server definitions: inline manifest config, else .mcp.json."""
        declared = self.manifest.mcp_servers
        if isinstance(declared, dict):
            return declared
        if isinstance(declared, str):
            path = self._safe_path(declared)
            if path is not None and path.is_file():
                return self._read_json(path)
            return None
        dot_mcp = self.root / ".mcp.json"
        if dot_mcp.is_file():
            return self._read_json(dot_mcp)
        return None

    @property
    def hooks_config(self) -> Optional[Dict[str, Any]]:
        """Hook definitions: inline manifest config, else hooks/hooks.json."""
        declared = self.manifest.hooks
        if isinstance(declared, dict):
            return declared
        if isinstance(declared, str):
            path = self._safe_path(declared)
            if path is not None and path.is_file():
                return self._read_json(path)
            return None
        hooks_json = self.root / "hooks" / "hooks.json"
        if hooks_json.is_file():
            return self._read_json(hooks_json)
        return None

    # ── helpers ─────────────────────────────────────────────────────────
    def _safe_path(self, rel: str) -> Optional[Path]:
        """Resolve a component path that must stay inside the plugin root."""
        p = (self.root / rel).resolve()
        if p.is_relative_to(self.root.resolve()):
            return p
        logger.warning(
            "plugin %s: component path %r escapes plugin root — ignored",
            self.name, rel,
        )
        return None

    @staticmethod
    def _read_json(path: Path) -> Optional[Dict[str, Any]]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 — malformed config must not crash
            logger.warning("plugin: failed to parse %s: %s", path, exc)
            return None

    def to_dict(self) -> Dict[str, Any]:
        """Serializable summary (for the plugin manager API/UI)."""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.manifest.author,
            "display_name": self.manifest.display_name,
            "plugin_id": self.plugin_id,
            "marketplace": self.marketplace,
            "path": str(self.root),
            "components": {
                "skills": [d.name for d in self.skill_dirs],
                "mcp_servers": bool(self.mcp_config),
                "hooks": bool(self.hooks_config),
            },
        }

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Plugin {self.plugin_id} v{self.version}>"


class PluginLoader:
    """Discover, parse, and stage plugins from a plugins root."""

    def __init__(self, root: Optional[str] = None):
        self.root = _resolve_plugins_root(root)
        self._plugins: Dict[str, Plugin] = {}
        self._marketplace: Optional[str] = None
        if self.root is not None:
            self._scan()

    # ── discovery ───────────────────────────────────────────────────────
    def _scan(self) -> None:
        """Load plugin.json manifests from the plugins root."""
        assert self.root is not None
        self._marketplace = self._find_marketplace_name()
        for child in sorted(self.root.iterdir()):
            if not child.is_dir():
                continue
            manifest_path = self._find_manifest(child)
            if manifest_path is None:
                continue
            try:
                manifest = PluginManifest.model_validate(
                    json.loads(manifest_path.read_text(encoding="utf-8"))
                )
                plugin = Plugin(child, manifest, marketplace=self._marketplace)
                self._plugins[plugin.name] = plugin
                logger.info(
                    "plugin: loaded %s v%s (%s)",
                    plugin.name, plugin.version, child,
                )
            except Exception as exc:  # noqa: BLE001 — one bad plugin must not kill the scan
                logger.warning("plugin: failed to load %s: %s", child, exc)

    def _find_manifest(self, plugin_dir: Path) -> Optional[Path]:
        for rel in MANIFEST_CANDIDATES:
            cand = plugin_dir / rel
            if cand.is_file():
                return cand
        return None

    def _find_marketplace_name(self) -> Optional[str]:
        assert self.root is not None
        for rel in MARKETPLACE_CANDIDATES:
            cand = self.root / rel
            if cand.is_file():
                try:
                    data = json.loads(cand.read_text(encoding="utf-8"))
                    name = data.get("name")
                    if name:
                        logger.info("plugin: marketplace %r at %s", name, cand)
                        return str(name)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("plugin: failed to parse marketplace %s: %s", cand, exc)
        return None

    # ── queries ─────────────────────────────────────────────────────────
    def list_plugins(self) -> List[Dict[str, Any]]:
        """All discovered plugins, as serializable summaries."""
        return [p.to_dict() for p in self._plugins.values()]

    def get_plugin(self, name: str) -> Optional[Plugin]:
        """Look up a plugin by bare name (or name@marketplace)."""
        if "@" in name:
            bare, mkt = name.split("@", 1)
            plugin = self._plugins.get(bare)
            if plugin is not None and mkt == plugin.marketplace:
                return plugin
            return None
        return self._plugins.get(name)

    def resolve_many(self, names: Optional[List[str]]) -> List[Plugin]:
        """Resolve a list of plugin names/ids; unknown names are skipped."""
        if not names:
            return []
        resolved = []
        for n in names:
            plugin = self.get_plugin(n)
            if plugin is None:
                logger.warning("plugin: requested %r not found in %s", n, self.root)
                continue
            resolved.append(plugin)
        return resolved

    # ── staging ─────────────────────────────────────────────────────────
    def stage_plugin_skills(
        self,
        plugins: List[Plugin],
        target_skills_dir: Path,
        namespace: str = "plugins",
    ) -> List[str]:
        """Copy each plugin's skill dirs into ``target_skills_dir``.

        Skill dirs are namespaced ``<namespace>/<plugin_name>/<skill_name>``
        (e.g. ``skills/plugins/meeting-minutes/agenda``) so different plugins
        cannot collide — the same namespacing Deep Agents Code uses.

        Returns the list of staged skill directories (relative paths).
        """
        target_skills_dir.mkdir(parents=True, exist_ok=True)
        staged: List[str] = []
        for plugin in plugins:
            for skill_dir in plugin.skill_dirs:
                dst = target_skills_dir / namespace / plugin.name / skill_dir.name
                try:
                    shutil.copytree(skill_dir, dst, dirs_exist_ok=True)
                    staged.append(str(dst.relative_to(target_skills_dir)))
                    logger.info(
                        "plugin: staged skill %s/%s -> %s",
                        plugin.name, skill_dir.name, dst,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("plugin: failed to stage %s: %s", skill_dir, exc)
        return staged


_loader: Optional[PluginLoader] = None


def get_plugin_loader(root: Optional[str] = None) -> PluginLoader:
    """Process-wide PluginLoader singleton."""
    global _loader
    if _loader is None or root is not None:
        _loader = PluginLoader(root=root)
    return _loader

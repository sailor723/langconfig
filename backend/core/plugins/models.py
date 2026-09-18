# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Plugin manifest models — LangChain-style declarative plugins.

Mirrors the Deep Agents Code plugin format (docs.langchain.com/oss/deepagents/
code/plugins): a plugin is a directory whose ``plugin.json`` (under
``.claude-plugin/`` or ``.codex-plugin/``, or at the root) declares the
components it contributes. LangConfig supports the same component kinds:

- ``skills`` — SKILL.md directories (progressive disclosure, identical format
  to standalone skills; the plugin name becomes the skill namespace)
- ``mcpServers`` — MCP server definitions (``.mcp.json`` or inline)
- ``hooks`` — lifecycle event handlers (declarative; LangConfig maps hook
  types onto its middleware seams)

A plugin has NO UI and NO endpoint — it is a capability capsule mounted into
agents. ``agents/`` and ``commands/`` components are intentionally unsupported
(the same restriction as Deep Agents Code).

Marketplaces are JSON catalogs (``marketplace.json``) listing plugins by
name/source, so a plugin directory can be discovered and installed.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

# Manifest file locations, in priority order (root-level first for
# LangConfig-authored plugins; the Claude/Codex subdirs for portability).
MANIFEST_CANDIDATES = [
    "plugin.json",
    ".claude-plugin/plugin.json",
    ".codex-plugin/plugin.json",
]

# Marketplace catalog locations, in priority order.
MARKETPLACE_CANDIDATES = [
    "marketplace.json",
    ".claude-plugin/marketplace.json",
    ".agents/plugins/marketplace.json",
]


class PluginManifest(BaseModel):
    """Declarative plugin manifest (plugin.json).

    Only ``name`` is required; every component path is optional. Component
    paths must stay inside the plugin root (no ``..`` escapes) — enforced by
    :meth:`PluginLoader._resolve_component_path`.
    """

    name: str = Field(..., description="Unique plugin identifier (kebab-case)")
    version: str = Field(default="1.0.0", description="Semver version string")
    description: str = Field(default="", description="One-line plugin description")
    author: Optional[str] = Field(default=None)
    display_name: Optional[str] = Field(
        default=None, description="Human-readable name for UIs"
    )

    # Component paths (relative to the plugin root) or inline configs.
    skills: Optional[str] = Field(
        default=None, description="Path to the skills/ directory"
    )
    mcp_servers: Optional[Any] = Field(
        default=None,
        description="Path to .mcp.json OR inline MCP server config dict",
    )
    hooks: Optional[Any] = Field(
        default=None,
        description="Path to hooks.json OR inline hooks config dict",
    )

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        name = (v or "").strip().lower()
        if not name or any(c in name for c in "/\\ "):
            raise ValueError(
                f"plugin name must be a simple kebab-case identifier, got {v!r}"
            )
        return name

    @property
    def skills_path(self) -> Optional[str]:
        """Resolved skills component path (or None when not declared)."""
        if not self.skills:
            return None
        if isinstance(self.skills, str):
            return self.skills
        return None


class MarketplaceManifest(BaseModel):
    """Marketplace catalog (marketplace.json).

    A marketplace is a named collection of plugins. Each entry requires
    ``name`` and ``source`` (a relative path inside the marketplace root for
    LangConfig-authored plugins; git/url sources are supported by Deep Agents
    Code but out of scope for local LangConfig marketplaces).
    """

    name: str = Field(..., description="Marketplace identifier")
    description: str = Field(default="")
    plugins: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="[{name, source, description?}] plugin entries",
    )

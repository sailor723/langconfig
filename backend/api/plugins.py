# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Plugin manager API — discover LangChain-style plugins (LangConfig analog of
the Deep Agents Code /plugins manager).

Endpoints:
- GET    /api/plugins              list plugins + marketplace
- GET    /api/plugins/{name}       one plugin's detail (components)
- GET    /api/plugins/{name}/skills/{skill}/SKILL.md  raw skill body
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/plugins", tags=["plugins"])


def _loader():
    from core.plugins import get_plugin_loader
    return get_plugin_loader()


@router.get("")
async def list_plugins() -> Dict[str, Any]:
    """List all discovered plugins plus the marketplace name."""
    loader = _loader()
    return {
        "marketplace": getattr(loader, "_marketplace", None),
        "root": str(loader.root) if loader.root else None,
        "plugins": loader.list_plugins(),
        "total": len(loader.list_plugins()),
    }


@router.get("/{name}")
async def get_plugin(name: str) -> Dict[str, Any]:
    """One plugin's detail, including its skill directories."""
    plugin = _loader().get_plugin(name)
    if plugin is None:
        raise HTTPException(404, f"plugin '{name}' not found")
    detail = plugin.to_dict()
    detail["skill_dirs"] = [str(s) for s in plugin.skill_dirs]
    detail["mcp_config"] = plugin.mcp_config
    detail["hooks_config"] = plugin.hooks_config
    return detail


@router.get("/{name}/skills/{skill_name}/SKILL.md")
async def get_plugin_skill(name: str, skill_name: str) -> Dict[str, str]:
    """Raw SKILL.md body of one plugin skill."""
    plugin = _loader().get_plugin(name)
    if plugin is None:
        raise HTTPException(404, f"plugin '{name}' not found")
    for skill_dir in plugin.skill_dirs:
        if skill_dir.name == skill_name:
            md = skill_dir / "SKILL.md"
            if md.is_file():
                return {"name": skill_name, "plugin": name, "content": md.read_text(encoding="utf-8")}
    raise HTTPException(404, f"skill '{skill_name}' not found in plugin '{name}'")

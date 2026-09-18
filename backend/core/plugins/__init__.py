# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""LangChain-style declarative plugins for LangConfig.

A plugin is a directory with a ``plugin.json`` manifest plus optional
``skills/``, MCP server config, and hooks — a capability capsule with no UI
and no endpoint, mounted into agents at build time (mirrors Deep Agents Code
plugin format: docs.langchain.com/oss/deepagents/code/plugins).
"""

from .loader import Plugin, PluginLoader, get_plugin_loader
from .models import PluginManifest, MarketplaceManifest

__all__ = [
    "Plugin",
    "PluginLoader",
    "PluginManifest",
    "MarketplaceManifest",
    "get_plugin_loader",
]

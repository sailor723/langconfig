# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Shared logging and artifact store for the tool factory.

Extracted from the former monolithic factory.py so the mixin modules
(base, builders) share one logger and artifact store without importing
the package ``__init__`` (which would create a circular import).
"""

import logging
import threading
from typing import Any, Dict, List

# Preserve the original logger identity so log filters keyed on
# "core.tools.factory" keep working after the split.
logger = logging.getLogger("core.tools.factory")

# Thread-safe artifact storage using a module-level dict
# ContextVar doesn't work across async boundaries in LangChain callbacks
_artifact_lock = threading.Lock()
_pending_artifacts: List[Dict[str, Any]] = []


def get_pending_artifacts() -> List[Dict[str, Any]]:
    """Get and clear any pending artifacts from the last tool execution."""
    global _pending_artifacts
    with _artifact_lock:
        artifacts = _pending_artifacts.copy()
        _pending_artifacts = []
        return artifacts


def store_artifact(artifact: Dict[str, Any]) -> None:
    """Store an artifact from a tool execution for later retrieval."""
    global _pending_artifacts
    with _artifact_lock:
        _pending_artifacts.append(artifact)
        logger.info(f"Artifact stored, pending count: {len(_pending_artifacts)}")

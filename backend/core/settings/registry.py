# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Settings namespace registry (DSH ``SettingsRegisterOptions`` analog).

Pure module — no DB, no config, no lazy imports. Registering a namespace just
associates a name with a pydantic schema and an optional cross-field validator;
resolution and persistence live in ``resolve.py`` / ``store.py``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)

NAMESPACE_PATTERN = r"^[a-z][a-z0-9-]*$"
import re as _re

_NAMESPACE_RE = _re.compile(NAMESPACE_PATTERN)


@dataclass
class NamespaceSpec:
    """One registered settings namespace."""

    ns: str
    schema: type[BaseModel]
    # Optional cross-field validator: raise ValueError to refuse a write whose
    # resolved section the owner could not act on (DSH `validate` analog).
    validate: Optional[Callable[[dict], None]] = None


_REGISTRY: dict[str, NamespaceSpec] = {}


def register(
    ns: str,
    schema: type[BaseModel],
    validate: Optional[Callable[[dict], None]] = None,
) -> NamespaceSpec:
    """Register (or replace) a namespace's schema and optional validator.

    ``ns`` must match lowercase kebab-case, mirroring DSH's namespace brand.
    """
    if not _NAMESPACE_RE.match(ns):
        raise TypeError(f'settings namespace "{ns}" must match {NAMESPACE_PATTERN}')
    spec = NamespaceSpec(ns=ns, schema=schema, validate=validate)
    _REGISTRY[ns] = spec
    logger.debug("registered settings namespace %r", ns)
    return spec


def get(ns: str) -> NamespaceSpec:
    """Return the spec for a registered namespace (raises KeyError)."""
    try:
        return _REGISTRY[ns]
    except KeyError:
        raise KeyError(f"settings namespace {ns!r} is not registered") from None


def is_registered(ns: str) -> bool:
    return ns in _REGISTRY


def namespaces() -> list[str]:
    """Registered namespace ids, in registration order."""
    return list(_REGISTRY)


def specs() -> list[NamespaceSpec]:
    return list(_REGISTRY.values())


# Test hook: clear the registry so a test can exercise a controlled set.
def _reset() -> None:
    _REGISTRY.clear()

"""Harness-profile registration for LangConfig.

deepagents 0.7 supports *harness profiles*: per provider/model overrides that
``create_deep_agent`` applies when a matching model is selected
(https://docs.langchain.com/oss/python/deepagents/profiles). LangConfig uses one
to hide the SDK's ``read_file`` from deep agents.

Why hide it: deepagents' ``FilesystemMiddleware.read_file`` returns images as
``[{"type": "image", "base64": …}]`` so a vision model can see them. That only
works in a *user* message — inside a **tool** message the base64 is tokenised per
character, so a 1.5 MB PNG became 2,113,084 chars ≈ 1,465,119 tokens and the
request 400'd against the 1,048,576-token window. With ``read_file`` excluded the
model reads files through LangConfig's own ``read_any_file`` builtin instead,
which returns text (OCR + one vision call) and cannot overflow the context.

Notes
-----
* Registration is process-global and keyed ``provider`` or ``provider:model``
  (``deepagents/profiles/_keys.py``). Registrations merge and excluded sets
  union, so calling this repeatedly is safe.
* ``excluded_middleware`` intentionally cannot drop ``FilesystemMiddleware``
  ("required scaffolding") — ``excluded_tools`` is the supported surface.
* The key for LangConfig's DeepSeek models resolves as ``deepseek:<model>``
  (provider from ``_get_ls_params``, identifier from the model dump).

Configure with environment variables (both comma-separated):

    LANGCONFIG_HARNESS_PROFILE_KEYS     default "deepseek:deepseek-flash"
    LANGCONFIG_HARNESS_EXCLUDED_TOOLS   default "read_file"

Leave either empty to disable registration entirely.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

DEFAULT_PROFILE_KEYS = "deepseek:deepseek-flash"
DEFAULT_EXCLUDED_TOOLS = "read_file"

_registered: dict[str, frozenset[str]] = {}


def _split_env(name: str, default: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


def register_langconfig_harness_profiles(
    keys: list[str] | None = None,
    excluded_tools: set[str] | None = None,
) -> dict[str, frozenset[str]]:
    """Register the harness profiles LangConfig depends on.

    Args:
        keys: Profile keys (``provider`` or ``provider:model``). Defaults to
            ``LANGCONFIG_HARNESS_PROFILE_KEYS``.
        excluded_tools: Tool names to hide from the model. Defaults to
            ``LANGCONFIG_HARNESS_EXCLUDED_TOOLS``.

    Returns:
        Mapping of registered key -> frozen excluded-tool set (empty when
        profiles are disabled or unavailable).
    """
    keys = keys if keys is not None else _split_env("LANGCONFIG_HARNESS_PROFILE_KEYS", DEFAULT_PROFILE_KEYS)
    excluded = (
        excluded_tools
        if excluded_tools is not None
        else set(_split_env("LANGCONFIG_HARNESS_EXCLUDED_TOOLS", DEFAULT_EXCLUDED_TOOLS))
    )

    if not keys or not excluded:
        logger.info(
            "Harness profiles disabled (keys=%s, excluded=%s)", keys, sorted(excluded)
        )
        return {}

    try:
        from deepagents import HarnessProfile, register_harness_profile
    except Exception as e:  # deepagents missing/older than profiles
        logger.warning("Harness profiles unavailable, skipping registration: %s", e)
        return {}

    profile = HarnessProfile(excluded_tools=frozenset(excluded))
    for key in keys:
        try:
            register_harness_profile(key, profile)
            _registered[key] = frozenset(excluded)
            logger.info(
                "Harness profile registered: %s excludes %s", key, sorted(excluded)
            )
        except Exception as e:
            logger.warning("Could not register harness profile for %r: %s", key, e)

    return dict(_registered)


def registered_profiles() -> dict[str, frozenset[str]]:
    """Profiles registered by this module in the current process."""
    return dict(_registered)


def excluded_tool_names() -> frozenset[str]:
    """Tool names to hide, from ``LANGCONFIG_HARNESS_EXCLUDED_TOOLS``."""
    return frozenset(_split_env("LANGCONFIG_HARNESS_EXCLUDED_TOOLS", DEFAULT_EXCLUDED_TOOLS))


def build_tool_exclusion_middleware():
    """Middleware that strips the excluded tools — for the normal-agent path.

    ``register_harness_profile`` only takes effect inside
    ``deepagents.create_deep_agent``. LangConfig's normal agents are built with
    ``langchain.agents.create_agent`` (``core/agents/factory/assembly.py``), so
    they need the very same filter applied directly. Returns ``None`` when
    nothing is configured or the SDK helper is unavailable.
    """
    excluded = excluded_tool_names()
    if not excluded:
        return None
    try:
        from deepagents.middleware._tool_exclusion import _ToolExclusionMiddleware
    except Exception as e:
        logger.warning("Tool-exclusion middleware unavailable: %s", e)
        return None
    return _ToolExclusionMiddleware(excluded=excluded)

"""
Context occupancy for a chat session.

Answers one question, for the composer's context ring and for the enforcement
that acts on it: how full is this agent's context, against the size it is
actually summarised at?

The denominator is a PER-AGENT setting — ``guardrails.token_limits.
summarization_threshold`` — not a model constant. That is the point: the number
already tells the agent when to compact its history, so an agent whose threshold
is 20k "fills up" at 20k whether it runs on a 128k or a 1M-token model, and the
meter cannot disagree with the behaviour it is describing. ``max_total_tokens``
is reported alongside as the ceiling, but the percentage is measured against the
summarisation threshold, which is the first limit an agent reaches.

Both figures come from one counter so the display and the enforcement can never
drift: ``count_context_tokens`` prices the system prompt and every message with
tiktoken's cl100k_base (the encoding ContextWindowManager already uses), falling
back to a 4-chars-per-token estimate when the encoder is unavailable. Tool
schemas are deliberately NOT counted: they are assembled by the agent factory at
run time and are not on the session row, and inventing them here would produce a
number that looks precise and is not.

That makes the figure an estimate of the message context, not a provider's
billing figure. It is anchored to the same message list the summarisation
middleware counts, which is what the meter needs to be true to.
"""

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Sequence, Union

import tiktoken

# Fallbacks used when an agent carries no guardrails document at all. They match
# the `agents` settings namespace defaults in core/settings/defaults.py, so a
# session whose agent predates those settings still reports sensible numbers.
DEFAULT_SUMMARIZATION_THRESHOLD = 60_000
DEFAULT_EVICTION_THRESHOLD = 80_000
DEFAULT_MAX_TOTAL_TOKENS = 100_000
DEFAULT_KEEP_LAST_MESSAGES = 20

# Per-message framing overhead (role field, separators). Mirrors the ROLE_OVERHEAD
# idea in DeepSeek Harness' token meter: small, but it keeps a long transcript of
# short messages from being priced as if the roles were free.
ROLE_OVERHEAD_TOKENS = 4

_encoder = None


def _get_encoder():
    """cl100k_base, or None when tiktoken has no cached encoding to give."""
    global _encoder
    if _encoder is None:
        try:
            _encoder = tiktoken.get_encoding("cl100k_base")
        except Exception:
            _encoder = False          # sentinel: tried and unavailable
    return _encoder or None


def count_tokens(text: str) -> int:
    """Tokens in one string, by tiktoken when available else 4 chars/token."""
    if not text:
        return 0
    encoder = _get_encoder()
    if encoder is None:
        return max(1, len(text) // 4)
    try:
        return len(encoder.encode(text))
    except Exception:
        return max(1, len(text) // 4)


def _content_tokens(content: Any) -> int:
    """Tokens of a message body: a string, or a list of content blocks."""
    if content is None:
        return 0
    if isinstance(content, str):
        return count_tokens(content)
    if isinstance(content, list):
        total = 0
        for block in content:
            if isinstance(block, str):
                total += count_tokens(block)
            elif isinstance(block, dict):
                # text/reasoning blocks carry `text`; tool blocks carry
                # `content` or `args`. Price whatever text is present.
                for key in ("text", "content", "arguments", "args"):
                    value = block.get(key)
                    if isinstance(value, str):
                        total += count_tokens(value)
                    elif isinstance(value, (dict, list)):
                        total += count_tokens(_stringify(value))
        return total
    if isinstance(content, dict):
        return count_tokens(_stringify(content))
    return count_tokens(str(content))


def _stringify(value: Any) -> str:
    """JSON for dicts/lists, str() otherwise — never raises on odd payloads."""
    if isinstance(value, (dict, list)):
        try:
            import json
            return json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            return str(value)
    return str(value)


def count_message_tokens(message: Union[dict, Any]) -> int:
    """One message: its content plus per-message framing."""
    if isinstance(message, dict):
        content = message.get("content")
        return _content_tokens(content) + ROLE_OVERHEAD_TOKENS
    return _content_tokens(getattr(message, "content", None)) + ROLE_OVERHEAD_TOKENS


def count_context_tokens(
    messages: Optional[Sequence[Union[dict, Any]]] = None,
    system_prompt: str = "",
) -> int:
    """
    Tokens of the context a chat request would carry: the system prompt plus
    every message, counted the way the summarisation trigger counts them.
    """
    total = count_tokens(system_prompt) if system_prompt else 0
    for message in messages or []:
        total += count_message_tokens(message)
    return total


def resolve_limits(
    guardrails: Optional[Dict[str, Any]] = None,
    use_deepagents: bool = True,
) -> Dict[str, Any]:
    """
    The agent's own context limits, falling back to the per-kind Settings
    defaults where the agent carries none.

    Read through the same helper the create endpoints use, so an agent saved
    before the `agents` settings existed resolves to the same numbers a new one
    would be created with.
    """
    from models.deep_agent import _agent_limits

    defaults = _agent_limits(use_deepagents)
    limits = ((guardrails or {}).get("token_limits") or {}) if isinstance(guardrails, dict) else {}

    def pick(key: str, fallback: Any) -> int:
        value = limits.get(key)
        if value is None:
            value = defaults.get(key, fallback)
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(fallback)

    return {
        "summarization_threshold": pick("summarization_threshold", DEFAULT_SUMMARIZATION_THRESHOLD),
        "eviction_threshold": pick("eviction_threshold", DEFAULT_EVICTION_THRESHOLD),
        "max_total_tokens": pick("max_total_tokens", DEFAULT_MAX_TOTAL_TOKENS),
        "keep_last_messages": pick("keep_last_messages", DEFAULT_KEEP_LAST_MESSAGES),
        "enable_summarization": bool(
            (guardrails or {}).get("enable_summarization", defaults.get("enable_summarization", True))
        ) if isinstance(guardrails, dict) else True,
    }


@dataclass(frozen=True)
class ContextOccupancy:
    """
    How full a session's context is, against the agent's own thresholds.

    ``percent`` is measured against ``summarization_threshold`` because that is
    the first limit the agent reaches; ``max_total_tokens`` is carried as the
    ceiling the same meter can show. ``percent_of_max`` is the equivalent figure
    against that ceiling, for a caller that wants the wider view.
    """

    used_tokens: int
    summarization_threshold: int
    eviction_threshold: int
    max_total_tokens: int
    keep_last_messages: int
    enable_summarization: bool
    percent: int
    percent_of_max: int

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def occupancy(
    messages: Optional[Sequence[Union[dict, Any]]] = None,
    guardrails: Optional[Dict[str, Any]] = None,
    system_prompt: str = "",
    use_deepagents: bool = True,
) -> ContextOccupancy:
    """Occupancy for one context: the count, the limits, and the percentages."""
    limits = resolve_limits(guardrails, use_deepagents)
    used = count_context_tokens(messages, system_prompt)
    threshold = max(1, limits["summarization_threshold"])
    ceiling = max(1, limits["max_total_tokens"])

    return ContextOccupancy(
        used_tokens=used,
        summarization_threshold=limits["summarization_threshold"],
        eviction_threshold=limits["eviction_threshold"],
        max_total_tokens=limits["max_total_tokens"],
        keep_last_messages=limits["keep_last_messages"],
        enable_summarization=limits["enable_summarization"],
        # Capped at 100: a session can sit above its threshold waiting for the
        # next turn to compact it, and the meter should read "full", not "137%".
        percent=min(100, round(used / threshold * 100)),
        percent_of_max=min(100, round(used / ceiling * 100)),
    )


def agent_context_config(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    The guardrails document of an agent config, for either kind.

    Standard agents and DeepAgents are both rows in ``deep_agent_templates`` and
    both keep this under ``guardrails``; a template saved before that existed has
    ``guardrails_config`` on the row instead, which the caller can pass here.
    """
    if not isinstance(config, dict):
        return {}
    guardrails = config.get("guardrails")
    return guardrails if isinstance(guardrails, dict) else {}

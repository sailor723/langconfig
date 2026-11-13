"""Keep a chat thread's checkpointed history inside the model's context window.

Why this exists. The deep-agent chat path resumes a conversation by `thread_id`, so LangGraph
replays **every message of that thread** into the provider call. Nothing trims it: the thread's own
history is the only thing that grows without a ceiling. Measured on ECS, 2026-11-13, agent 379:

    Error code: 400 — "This model's maximum context length is 1048576 tokens. However, you
    requested 1384340 tokens (1367956 in the messages, 16384 in the completion)."

The same agent ran fine from the CLI seconds earlier, because a fresh run carries no history. So the
defect is the *thread*, not the agent — and the answer is not "start a new chat", it is to keep the
thread inside the window without lying about it.

Two levers, in this order, because the first one loses the least:

  1. **truncate individual oversized messages** — one `read_file` of a 1.1 MB HTML is ~300k tokens
     on its own, and its head is what the agent needs (the tail is markup). Truncation keeps the
     head and the tail and names the endpoint that still has the whole thing.
  2. **drop the oldest whole turns** — only when truncation is not enough. A dropped turn is
     reported, never implied; `/api/chat/{session_id}/history` still returns every turn.

Both are applied to the checkpointed state (so the state really shrinks, and the next turn starts
small), not to the outgoing payload (which would keep re-sending the same megabytes).

The budget is a POLICY, not a technical limit: `HISTORY_BUDGET_TOKENS` (200k) is roughly six
full-size turns of evidence. Beyond that a model's attention is worse than the transcript it can
still fetch, and the identity block already tells the agent where to fetch it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

#: Message tokens we are willing to carry into a turn (policy, overridable per call).
HISTORY_BUDGET_TOKENS = 200_000
#: A single message longer than this is truncated even when the total is under budget: it is one
#: tool result, and no turn needs 20k characters of a file when the head and tail are enough.
MESSAGE_TRUNCATE_ABOVE_CHARS = 20_000
#: What survives a truncated message: the head (where the structure is) + a short tail.
TRUNCATE_KEEP_HEAD = 4_000
TRUNCATE_KEEP_TAIL = 1_000
#: Always keep this many of the newest messages, whatever the budget says — the newest human turn
#: is the question being answered, and a guard that eats it turns a big thread into a broken turn.
ALWAYS_KEEP_NEWEST = 6


@dataclass
class Compaction:
    """What was done to a thread, in numbers a user can check."""

    tokens_before: int
    tokens_after: int
    truncated: list[tuple[str, int, int]] = field(default_factory=list)   # (id, before, after)
    dropped_ids: list[str] = field(default_factory=list)
    dropped_turns: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.truncated or self.dropped_ids)

    def describe(self) -> str:
        bits = []
        if self.truncated:
            saved = sum(b - a for _, b, a in self.truncated)
            bits.append(f"截断 {len(self.truncated)} 条过大的工具输出（省 {saved:,} 字符）")
        if self.dropped_turns:
            bits.append(f"移除最早的 {self.dropped_turns} 轮对话（原文仍在 /history）")
        if not bits:
            return ""
        return (f"上下文已压缩：{'；'.join(bits)}。"
                f"约 {self.tokens_before:,} → {self.tokens_after:,} tokens。"
                "这条记录本身不算证据——需要细节时去读 transcript。")


def estimate_tokens(messages) -> int:
    """Rough token count for a message list.

    Deliberately not a tokenizer: this guard only needs the right order of magnitude, it runs on
    every turn (a tokenizer call per message is slower than the check is worth) and being 20% off
    cannot cause the failure it prevents. CJK text is denser than English per character, so the
    divisor is conservative for English and about right for Chinese.
    """
    total = 0
    for message in messages or []:
        content = getattr(message, "content", "") or ""
        if isinstance(content, list):        # multimodal / block content
            content = " ".join(
                str(part.get("text", "")) if isinstance(part, dict) else str(part) for part in content
            )
        total += len(str(content))
        for call in (getattr(message, "tool_calls", None) or []):
            total += len(str(call.get("args") or "")) + len(str(call.get("name") or ""))
    return total // 3


def _truncate_text(text: str, limit_head: int = TRUNCATE_KEEP_HEAD,
                   limit_tail: int = TRUNCATE_KEEP_TAIL) -> str:
    if len(text) <= limit_head + limit_tail + 200:
        return text
    removed = len(text) - limit_head - limit_tail
    return (text[:limit_head]
            + f"\n\n…[truncated {removed:,} characters to fit the context window; the full result is "
              "in this session's transcript — GET /api/chat/{session_id}/history]…\n\n"
            + text[-limit_tail:])


def plan_compaction(messages, budget_tokens: int = HISTORY_BUDGET_TOKENS) -> Compaction:
    """What to truncate / drop so this thread fits `budget_tokens`.

    Pure: takes the message list, returns the plan. Applying it is the caller's job, so the rule
    can be tested without a checkpointer, a model or a database.

    Order of work:
      1. truncate any single oversized message (keeping the newest ones intact),
      2. if still over budget, drop from the OLDEST end, always in whole turns: an AIMessage with
         `tool_calls` and the ToolMessages that answer it leave together, because a tool result
         without its call is exactly the 400 this file exists to prevent.
    """
    messages = list(messages or [])
    result = Compaction(tokens_before=estimate_tokens(messages), tokens_after=0)
    if not messages:
        result.tokens_after = 0
        return result

    working = []
    newest_start = max(0, len(messages) - ALWAYS_KEEP_NEWEST)
    for index, message in enumerate(messages):
        content = getattr(message, "content", "") or ""
        too_big = isinstance(content, str) and len(content) > MESSAGE_TRUNCATE_ABOVE_CHARS
        # Truncation is allowed on ANY message, including the newest: 20k characters of head is
        # plenty even for the tool result this turn just produced, and truncating it is strictly
        # better than dropping an older turn to make room. Measured in the first version of this
        # rule: a 900k-character read_file result from the PREVIOUS turn was not truncated (it sat
        # inside the "newest 6" window) and a whole turn was dropped instead.
        if too_big:
            smaller = _truncate_text(content)
            result.truncated.append((str(getattr(message, "id", index)), len(content), len(smaller)))
            working.append(message.model_copy(update={"content": smaller}))
        else:
            working.append(message)

    total = estimate_tokens(working)
    if total > budget_tokens:
        # Grow the kept window from the newest end until it fits, never going below the floor:
        # the last ALWAYS_KEEP_NEWEST messages stay even when they alone exceed the budget, because
        # dropping the question being asked would turn a big thread into a broken turn.
        cut = newest_start
        while cut < len(working) and estimate_tokens(working[cut:]) > budget_tokens:
            cut += 1
        # Never begin the kept window on a ToolMessage: its AIMessage.tool_calls would be gone and
        # the provider rejects that pairing with the very 400 this file exists to prevent.
        while 0 < cut < len(working) and getattr(working[cut], "type", "") == "tool":
            cut -= 1
        if cut > 0:
            dropped = working[:cut]
            result.dropped_ids = [str(getattr(m, "id", i)) for i, m in enumerate(dropped)]
            result.dropped_turns = sum(1 for m in dropped if getattr(m, "type", "") == "human")
            working = working[cut:]

    result.tokens_after = estimate_tokens(working)
    return result


async def shrink_thread(graph, thread_id: str,
                        budget_tokens: int = HISTORY_BUDGET_TOKENS) -> Compaction:
    """Apply `plan_compaction` to a thread's checkpointed state. Never raises.

    Shrinking the STATE (not the payload) is what makes the next turn cheap as well: the checkpointer
    keeps what we leave behind, so a thread that once blew past the window stays small afterwards.
    """
    empty = Compaction(tokens_before=0, tokens_after=0)
    try:
        checkpointer = getattr(graph, "checkpointer", graph)
        if checkpointer is None or not hasattr(checkpointer, "aget_state"):
            return empty
        config = {"configurable": {"thread_id": thread_id}}
        state = await checkpointer.aget_state(config)
        values = getattr(state, "values", None) or {}
        messages = list(values.get("messages") or [])
        if not messages:
            return empty
        plan = plan_compaction(messages, budget_tokens)
        if not plan.changed:
            return plan

        from langchain_core.messages import RemoveMessage

        updates = []
        for message_id, _before, after in plan.truncated:
            original = next((m for m in messages if str(getattr(m, "id", "")) == message_id), None)
            if original is not None:
                updates.append(original.model_copy(
                    update={"content": _truncate_text(str(original.content or ""))}
                ))
        updates += [RemoveMessage(id=message_id) for message_id in plan.dropped_ids]
        if updates and hasattr(checkpointer, "aupdate_state"):
            await checkpointer.aupdate_state(config, {"messages": updates})
            logger.info(
                "thread %s compacted: %s → %s tokens (%s truncated, %s dropped)",
                thread_id, plan.tokens_before, plan.tokens_after,
                len(plan.truncated), len(plan.dropped_ids),
            )
        return plan
    except Exception as exc:                                   # noqa: BLE001 — never fail a turn
        logger.warning("thread compaction failed (non-fatal): %s", exc)
        return empty

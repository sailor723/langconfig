"""
Stateful streaming filter for `<think>...</think>` and `<tool_call>...</tool_call>`
XML blocks emitted by Minimax M3 as raw text in message content.

Why this exists: the provider puts thinking/tool-call XML inside the
visible content string. We strip it at the chat-model boundary so the
rest of the pipeline (SSE, frontend) only ever sees clean text.

Handles:
  - Blocks split across chunks (e.g. "thi" in chunk 1, "nk...rest" in chunk 2)
  - Nested tags (<tool_call> inside <think>) — the outer block wins
  - Open blocks at end of stream (no close tag) — content is dropped

Algorithm: char-by-char streaming with a sliding candidate window. In
visible state the window is the longest possible open tag; once it
overflows without matching, the first char is confirmed safe and
emitted. In hidden states the window is the matching close tag; chars
that don't form the close are dropped (they're hidden content).
"""
from __future__ import annotations


_OPEN_THINK = "<think>"
_CLOSE_THINK = "</think>"
_OPEN_TC = "<tool_call>"
_CLOSE_TC = "</tool_call>"

# Longest open tag = "<tool_call>" (11 chars); longest close = "</tool_call>" (12).
_MAX_OPEN = max(len(_OPEN_THINK), len(_OPEN_TC))    # 11
_MAX_CLOSE = max(len(_CLOSE_THINK), len(_CLOSE_TC))  # 12


class ThinkFilter:
    """Consumes a stream of text chunks and yields the visible portion.

    Usage:
        f = ThinkFilter()
        for chunk_text in upstream:
            visible = f.feed(chunk_text)
            if visible:
                downstream.send(visible)
        visible = f.flush()  # emit anything left in a final hidden state
    """

    def __init__(self) -> None:
        # "visible" | "think" | "tool_call"
        self._state = "visible"
        # Sliding candidate window. In visible mode, looking for an
        # open tag. In hidden modes, looking for the matching close.
        # In hidden modes the candidate is the unhidden (i.e.
        # pre-close) text we still need to scan.
        self._buf = ""

    def feed(self, text: str) -> str:
        """Consume `text`. Return the visible portion to emit."""
        if not text:
            return ""
        out: list = []
        for ch in text:
            self._buf += ch
            if self._state == "visible":
                # Match longest open tag at the END of the buffer.
                # We only care about the suffix, not earlier content.
                if self._buf.endswith(_OPEN_THINK):
                    # Emit everything before the open tag (confirmed
                    # visible), then enter think state.
                    out.append(self._buf[: -len(_OPEN_THINK)])
                    self._state = "think"
                    self._buf = ""
                elif self._buf.endswith(_OPEN_TC):
                    out.append(self._buf[: -len(_OPEN_TC)])
                    self._state = "tool_call"
                    self._buf = ""
                elif len(self._buf) > _MAX_OPEN:
                    # Buffer is wider than any possible open tag and
                    # we still haven't matched — the first char is
                    # definitely not the start of a tag. Emit it and
                    # slide the window.
                    out.append(self._buf[0])
                    self._buf = self._buf[1:]
            elif self._state == "think":
                if self._buf.endswith(_CLOSE_THINK):
                    # Close tag matched. Drop everything in the
                    # buffer (it's hidden content). Return to visible.
                    self._state = "visible"
                    self._buf = ""
                elif len(self._buf) > len(_CLOSE_THINK):
                    # Still scanning for </think>. Drop oldest char
                    # to keep the window bounded.
                    self._buf = self._buf[1:]
            elif self._state == "tool_call":
                if self._buf.endswith(_CLOSE_TC):
                    self._state = "visible"
                    self._buf = ""
                elif len(self._buf) > len(_CLOSE_TC):
                    self._buf = self._buf[1:]
        return "".join(out)

    def flush(self) -> str:
        """Emit any trailing visible text. Call once at end of stream."""
        if self._state == "visible":
            out, self._buf = self._buf, ""
            return out
        # Hidden state with no close: drop the remainder.
        self._buf = ""
        return ""

#!/usr/bin/env python3
"""Deterministic meeting-minutes draft extractor (bundled with the
meeting-minutes plugin).

Reads a raw transcript from stdin and emits a JSON draft with decisions,
action items, open questions, and a summary hint. The agent (not this
script) writes the final minutes markdown, so this only needs to be
deterministic and fast — no LLM calls.

Usage:
    python minutes.py < transcript.txt
    cat transcript.txt | python minutes.py
"""

import json
import re
import sys

# Lines that typically start an action item / decision / open question.
_ACTION_RE = re.compile(
    r"^\s*[-*]?\s*(?:action|todo|to[- ]do|will|follow[- ]up|owner|"
    r"someone (?:needs|should)|we (?:need|should|will))",
    re.IGNORECASE,
)
_DECISION_RE = re.compile(
    r"^\s*[-*]?\s*(?:decision|agreed|decided|approved|we (?:agreed|decided|"
    r"approved|will go with))",
    re.IGNORECASE,
)
_QUESTION_RE = re.compile(
    r"^\s*[-*]?\s*(?:question|open question|tbd|to be decided|need to "
    r"decide|what about|should we)",
    re.IGNORECASE,
)


def _classify(line: str) -> str | None:
    """Return 'action' | 'decision' | 'question' | None for a line."""
    stripped = line.strip()
    if not stripped:
        return None
    if _ACTION_RE.match(stripped):
        return "action"
    if _DECISION_RE.match(stripped):
        return "decision"
    if _QUESTION_RE.match(stripped):
        return "question"
    return None


def extract(transcript: str) -> dict:
    decisions: list[str] = []
    action_items: list[str] = []
    open_questions: list[str] = []
    summary_hint_lines: list[str] = []

    for raw in transcript.splitlines():
        kind = _classify(raw)
        text = raw.strip().lstrip("-* ")
        if kind == "action":
            action_items.append(text)
        elif kind == "decision":
            decisions.append(text)
        elif kind == "question":
            open_questions.append(text)
        elif text and len(summary_hint_lines) < 3:
            # First few non-classified lines are likely the meeting's purpose.
            summary_hint_lines.append(text)

    return {
        "decisions": decisions,
        "action_items": action_items,
        "open_questions": open_questions,
        "summary_hint": " ".join(summary_hint_lines),
        "stats": {
            "total_lines": len(transcript.splitlines()),
            "decisions": len(decisions),
            "action_items": len(action_items),
            "open_questions": len(open_questions),
        },
    }


def main() -> int:
    transcript = sys.stdin.read()
    if not transcript.strip():
        print(json.dumps({"error": "empty transcript on stdin"}, ensure_ascii=False))
        return 1
    print(json.dumps(extract(transcript), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

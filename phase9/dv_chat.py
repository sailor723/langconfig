#!/usr/bin/env python3
"""
Phase 9 — Step 1: DV (Doc-Viewer) chat with cache-friendly prompts.

Design:
  - Simple llm.invoke loop (no deepagents — direct control over message shape).
  - System message is the document + rules (STABLE across all turns).
  - User message carries the current question + recent history.
  - This way, the system message prefix is identical every turn → MiniMax
    can hit its automatic prompt cache when the same question is repeated.

Per rules.md:
  - No truncation, no chunking, no embeddings.
  - MiniMax M3 via init_chat_model.
  - Standalone script.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List

from dotenv import load_dotenv

# --- .env resolution (works as script AND in REPL) ---------------------------
try:
    _env_path = Path(__file__).resolve().parent.parent / ".env"
except NameError:
    _env_path = Path(os.getcwd()) / ".env"
if not _env_path.exists():
    _alt = Path(os.getcwd()).parent / ".env"
    if _alt.exists():
        _env_path = _alt
load_dotenv(_env_path)

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_core.language_models.chat_models import BaseChatModel
import fitz

# --- Constants ---------------------------------------------------------------

MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
MINIMAX_BASE_URL = os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1")
MODEL = "minimax-m3"
WARN_CHARS = 800_000

DEFAULT_DOC = "/Users/weiping/dev/Learn/langchain-ai/langconfig/backend/data/documents/project_1/31042021_nke-10k-2023.pdf"
DEFAULT_MEMORY_DIR = str(Path(__file__).resolve().parent / ".dv_memory")
DEFAULT_MEMORY_FILE = "AGENTS.md"
SUPPORTED_EXTS = {".pdf", ".md", ".markdown", ".txt"}

# History compression: how many recent Q/A pairs to inline into the user msg
# (more = better multi-turn context, less = more cache hit probability)
HISTORY_TURNS = 3

# MiniMax M3 pricing
PRICING = {
    "standard": {"input": 0.60, "output": 2.40},
    "long_ctx": {"input": 1.20, "output": 4.80},
}
TIER_THRESHOLD = 512_000
SESSION_START = time.time()


# --- Text extraction ---------------------------------------------------------

def _extract_text(file_path: Path) -> tuple[str, int]:
    ext = file_path.suffix.lower()
    if ext == ".pdf":
        doc = fitz.open(str(file_path))
        parts: List[str] = []
        for i in range(len(doc)):
            text = doc[i].get_text("text").strip()
            if text:
                parts.append(f"--- Page {i+1}/{len(doc)} ---\n{text}")
            else:
                parts.append(f"--- Page {i+1}/{len(doc)} ---\n(no extractable text)")
        doc.close()
        return "\n\n".join(parts), len(parts)
    return file_path.read_text(encoding="utf-8"), 1


# --- System message (stable, minimal) ---------------------------------------

def _build_system_prompt() -> str:
    """Short system message — the doc lives in the conversation history instead."""
    return (
        "You are answering questions about a document the user provides.\n"
        "The first user message in this conversation contains the full document "
        "text with --- Page N --- markers. Subsequent user messages are questions.\n\n"
        "Rules:\n"
        "1. Answer ONLY from the document. If the answer is not there, say so.\n"
        "2. Cite page numbers, e.g. \"(page 3)\"."
    )


# --- Initial user message carrying the document ------------------------------

def _build_doc_message(doc_name: str, full_text: str) -> str:
    """First user message = the document. Acts as a one-shot KV context."""
    return f"Document: {doc_name}\n\n--- FULL DOCUMENT TEXT ---\n\n{full_text}"


# --- LLM ---------------------------------------------------------------------

def _make_llm() -> BaseChatModel:
    if not MINIMAX_API_KEY:
        sys.stderr.write("FATAL: MINIMAX_API_KEY not set in .env\n")
        sys.exit(1)
    return init_chat_model(
        model=MODEL,
        model_provider="openai",
        api_key=MINIMAX_API_KEY,
        base_url=MINIMAX_BASE_URL,
        temperature=0.2,
        max_tokens=8192,
    )


# --- Conversation meta -------------------------------------------------------

@dataclass
class Turn:
    question: str
    answer: str
    in_tokens: int
    out_tokens: int
    cache_read: int           # MiniMax returns this in input_token_details
    elapsed: float
    started_at: float


class Conversation:
    def __init__(self, model: str):
        self.model = model
        self.turns: List[Turn] = []
        self.total_in = 0
        self.total_out = 0
        self.total_cache_read = 0
        self.total_elapsed = 0.0

    def add(self, turn: Turn) -> None:
        self.turns.append(turn)
        self.total_in += turn.in_tokens
        self.total_out += turn.out_tokens
        self.total_cache_read += turn.cache_read
        self.total_elapsed += turn.elapsed

    def _cost(self, in_tok: int, out_tok: int, cached: int) -> float:
        """MiniMax charges less for cached tokens. Verify exact discount in docs."""
        tier = "long_ctx" if in_tok > TIER_THRESHOLD else "standard"
        p = PRICING[tier]
        # Assume cached tokens are ~90% off (matches OpenAI pricing pattern).
        # Override here when we get actual MiniMax cached-token pricing.
        cached_discount = 0.10
        billable = in_tok - cached
        return (billable / 1_000_000) * p["input"] + (cached / 1_000_000) * p["input"] * cached_discount + \
               (out_tok / 1_000_000) * p["output"]

    def turn_cost(self, turn: Turn) -> float:
        return self._cost(turn.in_tokens, turn.out_tokens, turn.cache_read)

    def cumulative_cost(self) -> float:
        return sum(self.turn_cost(t) for t in self.turns)


def _format_session_footer(turn: Turn, conv: Conversation) -> str:
    tier = "long-ctx" if turn.in_tokens > TIER_THRESHOLD else "standard"
    cum_cost = conv.cumulative_cost()
    wall = time.time() - SESSION_START
    cache_pct = 100 * turn.cache_read / turn.in_tokens if turn.in_tokens else 0
    return (
        f"   ├─ tokens:  in={turn.in_tokens:>7,}  out={turn.out_tokens:>5,}  ({tier})\n"
        f"   │           cache_read={turn.cache_read:>6,}  ({cache_pct:.1f}% cached)\n"
        f"   ├─ latency: {turn.elapsed:5.1f}s  (cum LLM: {conv.total_elapsed:5.1f}s, wall: {wall:5.1f}s)\n"
        f"   └─ cost:    ${conv.turn_cost(turn):.4f}  "
        f"(session: ${cum_cost:.4f} over {len(conv.turns)} turn{'s' if len(conv.turns) != 1 else ''})"
    )


def _print_session_summary(conv: Conversation) -> None:
    if not conv.turns:
        print("   (no turns yet)")
        return
    wall = time.time() - SESSION_START
    cum_cost = conv.cumulative_cost()
    avg_tps = conv.total_out / conv.total_elapsed if conv.total_elapsed > 0 else 0
    cache_pct = 100 * conv.total_cache_read / conv.total_in if conv.total_in else 0
    print(f"\n   ┌─ session summary")
    print(f"   ├─ turns:        {len(conv.turns)}")
    print(f"   ├─ tokens:       in={conv.total_in:,}  out={conv.total_out:,}  "
          f"total={conv.total_in + conv.total_out:,}")
    print(f"   ├─ cache:        {conv.total_cache_read:,} tokens read from cache "
          f"({cache_pct:.1f}%)")
    print(f"   ├─ time:         LLM={conv.total_elapsed:.1f}s  wall={wall:.1f}s  "
          f"({avg_tps:.0f} tok/s output)")
    print(f"   └─ cost:         ${cum_cost:.4f}")


# --- REPL --------------------------------------------------------------------

HELP_TEXT = """\
Commands:
  /doc               Print document stats
  /stats             Show conversation totals (tokens, time, cache, cost)
  /help              Show this help
  /quit              Exit
"""


def _repl(llm: BaseChatModel, system_message: SystemMessage, doc_message: HumanMessage, conv: Conversation) -> None:
    print(f"\n{'='*60}")
    print(f"📄 System prompt: {len(system_message.content):,} chars")
    print(f"📄 Doc (first user msg): {len(doc_message.content):,} chars")
    print(f"   Type /help for commands\n")

    # Conversation history — doc + all turns, sent as-is to the LLM.
    # The doc message stays in place at index 1; we append Q/A pairs after it.
    messages: list = [system_message, doc_message]

    while True:
        try:
            raw = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            _print_session_summary(conv)
            print("\nbye.")
            return

        if not raw:
            continue
        low = raw.lower()

        if low in ("/quit", "/exit", "/q"):
            _print_session_summary(conv)
            print("bye.")
            return
        if low == "/help":
            print(HELP_TEXT)
            continue
        if low == "/doc":
            print(f"system: {len(system_message.content):,} chars  "
                  f"doc: {len(doc_message.content):,} chars")
            continue
        if low == "/stats":
            _print_session_summary(conv)
            continue

        # Append the user's question to the running history
        messages.append(HumanMessage(content=raw))
        t0 = time.time()
        try:
            resp = llm.invoke(messages)
        except Exception as e:
            messages.pop()  # don't keep the failed question
            print(f"  ✗ error: {e}")
            continue
        elapsed = time.time() - t0

        # Extract answer + usage
        answer = resp.content if isinstance(resp.content, str) else str(resp.content)
        usage = getattr(resp, "usage_metadata", None) or {}
        details = usage.get("input_token_details", {}) or {}
        in_tok = int(usage.get("input_tokens", 0))
        out_tok = int(usage.get("output_tokens", 0))
        # MiniMax's field name is "cache_read" (not OpenAI's "cached_tokens")
        cache_read = int(details.get("cache_read", 0) or details.get("cached_tokens", 0))

        # Record the AI reply in history so the next turn keeps context
        messages.append(AIMessage(content=answer))

        # Record turn
        turn = Turn(
            question=raw, answer=answer,
            in_tokens=in_tok, out_tokens=out_tok, cache_read=cache_read,
            elapsed=elapsed, started_at=t0,
        )
        conv.add(turn)

        print(f"\n🤖 {answer}")
        print(_format_session_footer(turn, conv))


# --- Entry point -------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 9 / Step 1 — DV chat with cache-friendly prompts.",
    )
    parser.add_argument(
        "path", nargs="?", default=DEFAULT_DOC,
        help=f"Path to PDF / MD / TXT. Default: {DEFAULT_DOC}",
    )
    args = parser.parse_args()

    # 1. Resolve file
    file_path = Path(args.path).expanduser().resolve()
    if not file_path.exists():
        sys.stderr.write(f"FATAL: file not found: {file_path}\n")
        return 1
    if file_path.suffix.lower() not in SUPPORTED_EXTS:
        sys.stderr.write(f"FATAL: unsupported file: {file_path.suffix}\n")
        return 1

    # 2. Extract text
    print(f"📖 Reading {file_path.name} ...")
    full_text, page_count = _extract_text(file_path)
    print(f"   {page_count} pages, ~{len(full_text):,} chars")

    if len(full_text) < 500 and page_count > 1:
        print(f"⚠️  Very little text extracted — likely scanned PDF")

    # 3. Build system message + initial doc message (the conversation seed)
    system_message = SystemMessage(content=_build_system_prompt())
    doc_message = HumanMessage(content=_build_doc_message(file_path.stem, full_text))
    print(f"System prompt: {len(system_message.content):,} chars")
    print(f"Doc message:   {len(doc_message.content):,} chars (sealed at index 1 of history)")

    # 4. Build LLM
    llm = _make_llm()
    print(f"LLM: {MODEL}")

    # 5. REPL
    conv = Conversation(MODEL)
    _repl(llm, system_message, doc_message, conv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
Phase 9 — MiniMax M3 prompt-cache probe.

Hypothesis: MiniMax's OpenAI-compatible API inherits OpenAI's automatic
prompt caching — if the prompt prefix matches a recent request, the server
reuses KV cache. We test by:
  1. Sending the same system message + same/similar user message twice
  2. Reading `usage.prompt_tokens_details.cached_tokens` from the response
  3. Comparing wall-clock latency for the second call

If cached_tokens > 0 on the second call → MiniMax supports it → use scheme C.
If cached_tokens == 0 → no cache → fall back to scheme B (message history).
"""
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from dotenv import load_dotenv
load_dotenv(REPO_ROOT / ".env")

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage
import fitz

# Use a real chunk of the Nike 10-K — this is what the real chat would send.
DOC = REPO_ROOT / "backend/data/documents/project_1/31042021_nke-10k-2023.pdf"


def extract_text(path: Path, max_chars: int = 500_000) -> str:
    """First N chars of the doc — enough to exceed the 1024-token cache threshold."""
    doc = fitz.open(str(path))
    parts = []
    total = 0
    for i in range(len(doc)):
        text = doc[i].get_text("text").strip()
        if not text:
            continue
        chunk = f"--- Page {i+1} ---\n{text}\n\n"
        if total + len(chunk) > max_chars:
            break
        parts.append(chunk)
        total += len(chunk)
    doc.close()
    return "".join(parts)


def inspect_usage(resp, label: str) -> dict:
    """Pull every cache-related field from the response."""
    usage = getattr(resp, "usage_metadata", None) or {}
    details = usage.get("input_token_details", {}) or {}
    print(f"  [{label}] usage_metadata = {usage}")
    print(f"  [{label}] input_token_details = {details}")
    return {"usage": usage, "details": details}


def main() -> int:
    if not os.environ.get("MINIMAX_API_KEY"):
        print("FATAL: MINIMAX_API_KEY not set")
        return 1

    print(f"📖 Extracting ~100K chars from {DOC.name} ...")
    doc_text = extract_text(DOC)
    print(f"   extracted: {len(doc_text):,} chars")

    system = SystemMessage(content=(
        "You are answering questions about a Nike 10-K filing. "
        "Use the document below.\n\n"
        f"{doc_text}"
    ))

    llm = init_chat_model(
        model="minimax-m3",
        model_provider="openai",
        api_key=os.environ["MINIMAX_API_KEY"],
        base_url=os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1"),
        temperature=0.0,    # cache requires deterministic
        max_tokens=512,
    )

    # --- Trial 1: cold start (should be slow, no cache) ---
    print(f"\n=== Trial 1: cold start ===")
    t0 = time.time()
    r1 = llm.invoke([system, HumanMessage(content="What year was this 10-K filed?")])
    t1 = time.time()
    print(f"  answer: {r1.content[:200]}")
    inspect_usage(r1, "T1")

    # --- Trial 2: same prefix, new question (cache hit candidate) ---
    print(f"\n=== Trial 2: same prefix, different question ===")
    t2 = time.time()
    r2 = llm.invoke([system, HumanMessage(content="What was Nike's revenue?")])
    t3 = time.time()
    print(f"  answer: {r2.content[:200]}")
    inspect_usage(r2, "T2")

    # --- Trial 3: identical request (strongest cache signal) ---
    print(f"\n=== Trial 3: identical to T1 ===")
    t4 = time.time()
    r3 = llm.invoke([system, HumanMessage(content="What year was this 10-K filed?")])
    t5 = time.time()
    print(f"  answer: {r3.content[:200]}")
    inspect_usage(r3, "T3")

    print(f"\n=== Latency ===")
    print(f"  T1 (cold):   {t1-t0:.2f}s")
    print(f"  T2 (warm):   {t3-t2:.2f}s")
    print(f"  T3 (warm):   {t5-t4:.2f}s")

    # --- Verdict ---
    print(f"\n=== Verdict ===")
    cached_seen = False
    for label, r in [("T1", r1), ("T2", r2), ("T3", r3)]:
        usage = getattr(r, "usage_metadata", None) or {}
        details = usage.get("input_token_details", {}) or {}
        # MiniMax's actual field name is "cache_read" — different from OpenAI's "cached_tokens"
        cached = details.get("cache_read", 0) or details.get("cached_tokens", 0)
        if cached and cached > 0:
            cached_seen = True
            total_in = usage.get("input_tokens", 0)
            pct = 100 * cached / total_in if total_in else 0
            print(f"  [{label}] CACHE HIT — cache_read = {cached:,} / {total_in:,} ({pct:.1f}%)")
        else:
            print(f"  [{label}] no cache signal in metadata")

    if cached_seen:
        print(f"\n  ✓ MiniMax supports prompt cache → use scheme C (cache-friendly messages)")
    else:
        print(f"\n  ✗ No cache signal → fall back to scheme B (message history)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

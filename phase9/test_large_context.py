#!/usr/bin/env python3
"""
Stress test: stuff multiple PDFs into one prompt and verify MiniMax M3
handles a large context (target: 200K+ tokens, well within 1M limit).
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

try:
    import tiktoken
    enc = tiktoken.get_encoding("cl100k_base")
except ImportError:
    enc = None


def count_tokens(text: str) -> int:
    return len(enc.encode(text)) if enc else len(text) // 4


def extract_pdf(file_path: Path) -> tuple[str, int]:
    doc = fitz.open(str(file_path))
    pages = []
    for i in range(len(doc)):
        text = doc[i].get_text("text").strip()
        if text:
            pages.append(f"--- Page {i+1}/{len(doc)} ---\n{text}")
    doc.close()
    return "\n\n".join(pages), len(pages)


def main() -> int:
    docs_dir = REPO_ROOT / "backend/data/documents/project_1"
    pdfs = sorted(docs_dir.rglob("*.pdf"))[:8]  # take 8 PDFs

    print(f"Combining {len(pdfs)} PDFs into one prompt...")
    combined_parts = []
    total_pages = 0
    for p in pdfs:
        text, n_pages = extract_pdf(p)
        if len(text) < 200:  # skip scanned
            print(f"  skip: {p.name} (scanned)")
            continue
        combined_parts.append(f"\n\n=== DOCUMENT: {p.stem} ===\n{text}")
        total_pages += n_pages

    combined = "\n".join(combined_parts)
    char_count = len(combined)
    token_count = count_tokens(combined)
    print(f"\n  total: {total_pages} pages, {char_count:,} chars, ~{token_count:,} tokens")
    print(f"  context usage: {(token_count/1_000_000)*100:.1f}% of 1M")

    if token_count > 1_000_000:
        print(f"\n  ⚠️  exceeds 1M — try fewer PDFs")
        return 0  # not a failure, just a benchmark

    # Build prompt
    system_prompt = (
        f"You have {len(pdfs)} documents below, each marked with === DOCUMENT: name ===.\n"
        f"Answer questions by finding the right document and citing its page.\n\n"
        f"{combined}"
    )

    # Ask about a specific doc
    query = (
        "From the Nike 10-K, what was total revenue in fiscal 2023? "
        "Also from any document, list the philosophers mentioned and their core ideas. "
        "Cite the document name and page for each answer."
    )

    llm = init_chat_model(
        model="minimax-m3",
        model_provider="openai",
        api_key=os.environ["MINIMAX_API_KEY"],
        base_url=os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1"),
        temperature=0.2,
        max_tokens=8192,
    )

    print(f"\n  ⏱  asking LLM with {token_count:,} tokens of context...")
    t0 = time.time()
    resp = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=query),
    ])
    elapsed = time.time() - t0

    usage = getattr(resp, "usage_metadata", None) or {}
    in_tok = usage.get("input_tokens", 0)
    out_tok = usage.get("output_tokens", 0)

    print(f"  ⏱  {elapsed:.1f}s   input_tokens={in_tok}  output_tokens={out_tok}")
    print(f"\n  📝 ANSWER (first 800 chars):\n  {resp.content[:800]}{'...' if len(resp.content) > 800 else ''}")

    # Verify
    if in_tok < token_count * 0.8:
        print(f"\n  ✗ FAIL: input_tokens ({in_tok}) << expected ({token_count}) — server truncated")
        return 1
    print(f"\n  ✓ PASS: input_tokens matches — no truncation, MiniMax M3 handled full context")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

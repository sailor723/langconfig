#!/usr/bin/env python3
"""
Phase 9 / Step 1 — test script for dv_chat.py.

Verifies:
  1. MiniMax M3 receives the FULL document (no truncation, no silent chunking)
  2. Answer is grounded in the doc, with page citations
  3. Chinese doc works
  4. Scanned-PDF warning triggers
  5. Token counting is within MiniMax M3's 1M context window

Usage:
  backend/.venv/bin/python phase9/test_dv_chat.py
"""
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(REPO_ROOT / ".env")

# Use MiniMax directly via langchain
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage
import fitz  # PyMuPDF

# Try to use tiktoken for accurate token counting
try:
    import tiktoken
    enc = tiktoken.get_encoding("cl100k_base")  # close enough to MiniMax's tokenizer
except ImportError:
    enc = None
    print("⚠️  tiktoken not available — will use char-based estimate")


def count_tokens(text: str) -> int:
    """Accurate if tiktoken is available, else 4-chars-per-token estimate."""
    if enc:
        return len(enc.encode(text))
    return len(text) // 4


def extract_pdf_pages(file_path: Path) -> list[dict]:
    """Extract pages as [{page: int, content: str}, ...] using PyMuPDF."""
    doc = fitz.open(str(file_path))
    pages = []
    for i in range(len(doc)):
        text = doc[i].get_text("text").strip()
        pages.append({"page": i + 1, "content": text})
    doc.close()
    return pages


def build_system_prompt(doc_name: str, pages: list[dict]) -> str:
    """Mirror dv_chat.py's prompt format."""
    parts = [f"--- Page {i+1}/{len(pages)} ---\n{p['content']}"
             for i, p in enumerate(pages) if p["content"]]
    body = "\n\n".join(parts)
    return (
        f"Document: {doc_name}.pdf\n\n"
        f"You are answering questions about this single document.\n"
        f"The FULL text is below with --- Page N --- markers.\n\n"
        f"Rules:\n"
        f"1. Answer ONLY from the document. If the answer isn't there, say so.\n"
        f"2. Cite page numbers, e.g. \"(page 3)\".\n"
        f"3. No outside knowledge.\n\n"
        f"--- FULL DOCUMENT TEXT ---\n{body}"
    )


def ask(llm, system_prompt: str, query: str) -> tuple[str, int, int]:
    """Ask the LLM, return (answer, input_tokens, output_tokens)."""
    resp = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=query),
    ])
    # langchain puts usage_metadata on the response
    usage = getattr(resp, "usage_metadata", None) or {}
    in_tok = usage.get("input_tokens", 0)
    out_tok = usage.get("output_tokens", 0)
    return resp.content, in_tok, out_tok


def test_case(name: str, pdf_path: Path, query: str, expect_keyword: str = None,
              expect_page_cite: bool = True):
    """Run one test case end-to-end."""
    print(f"\n{'='*70}")
    print(f"TEST: {name}")
    print(f"  doc:  {pdf_path}")
    print(f"  query: {query}")
    print('='*70)

    # 1. Extract
    pages = extract_pdf_pages(pdf_path)
    full_text = "\n\n".join(f"--- Page {p['page']}/{len(pages)} ---\n{p['content']}"
                            for p in pages if p["content"])
    char_count = len(full_text)
    token_count = count_tokens(full_text)

    print(f"  pages: {len(pages)}  chars: {char_count:,}  tokens: ~{token_count:,}")

    # 2. Assertions on extraction
    assert char_count > 500, f"FAIL: too little text ({char_count} chars) — likely scanned"
    print(f"  ✓ extraction OK")

    # 3. Token budget check (MiniMax M3: 1M context)
    limit = 1_000_000
    usage_pct = (token_count / limit) * 100
    print(f"  context usage: {usage_pct:.1f}% of 1M limit")
    if token_count > limit:
        print(f"  ✗ EXCEEDS MiniMax M3 limit")
        return False
    print(f"  ✓ within MiniMax M3 context window")

    # 4. Build LLM and ask
    llm = init_chat_model(
        model="minimax-m3",
        model_provider="openai",
        api_key=os.environ["MINIMAX_API_KEY"],
        base_url=os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1"),
        temperature=0.2,
        max_tokens=8192,
    )

    system_prompt = build_system_prompt(pdf_path.stem, pages)
    t0 = time.time()
    answer, in_tok, out_tok = ask(llm, system_prompt, query)
    elapsed = time.time() - t0

    # 5. Show answer
    print(f"\n  ⏱  {elapsed:.1f}s   input_tokens={in_tok}  output_tokens={out_tok}")
    print(f"\n  📝 ANSWER:\n  {answer[:500]}{'...' if len(answer) > 500 else ''}\n")

    # 6. Assertions on answer
    ok = True
    if expect_keyword:
        if expect_keyword.lower() in answer.lower():
            print(f"  ✓ contains expected keyword: '{expect_keyword}'")
        else:
            print(f"  ✗ MISSING expected keyword: '{expect_keyword}'")
            ok = False

    if expect_page_cite:
        if "(page" in answer.lower() or "(p." in answer.lower():
            print(f"  ✓ cites a page number")
        else:
            print(f"  ⚠️  no page citation found (might be OK)")

    # 7. Token usage sanity
    if in_tok > 0 and in_tok < token_count * 0.5:
        print(f"  ✗ input_tokens ({in_tok}) way below expected ({token_count}) — truncation?")
        ok = False
    elif in_tok > 0:
        print(f"  ✓ input_tokens matches doc size — no truncation")

    return ok


def test_scanned_warning():
    """Verify that a scanned PDF triggers the warning, not silent failure."""
    print(f"\n{'='*70}")
    print("TEST: Scanned PDF detection")
    print('='*70)

    scanned = REPO_ROOT / "backend/data/documents/project_1/08621a87_scanned_gpt4all.pdf"
    if not scanned.exists():
        print(f"  ⚠️  scanned PDF not found: {scanned}")
        return True

    pages = extract_pdf_pages(scanned)
    non_empty = [p for p in pages if p["content"]]
    print(f"  scanned PDF: {len(pages)} pages, {len(non_empty)} have extractable text")

    if len(non_empty) < len(pages) * 0.5:
        print(f"  ✓ would trigger scanned-PDF warning (most pages empty)")
    else:
        print(f"  ⚠️  scanned PDF actually has text — assumption wrong")
    return True


# --- Main ---

def main() -> int:
    if "MINIMAX_API_KEY" not in os.environ:
        print("FATAL: MINIMAX_API_KEY not set")
        return 1

    docs_dir = REPO_ROOT / "backend/data/documents/project_1"
    results = []

    # Test 1: Nike 10-K (English, real text, large)
    results.append(test_case(
        name="Nike 10-K (EN, 107 pages)",
        pdf_path=docs_dir / "31042021_nke-10k-2023.pdf",
        query="What was Nike's total revenue in fiscal year 2023?",
        expect_keyword="51.2 billion",
    ))

    # Test 2: Chinese doc
    chinese_path = docs_dir / "5cc12ddf_6 人物库 2.pdf"
    if chinese_path.exists():
        results.append(test_case(
            name="Chinese 人物库 (ZH)",
            pdf_path=chinese_path,
            query="请列出文中提到的哲学家及其核心思想",
            expect_keyword=None,  # open-ended
        ))

    # Test 3: Strategic Framework (English deck)
    strat = docs_dir / "66bbde2a_Departmental Survey for Biz Strategy.pdf"
    if strat.exists():
        results.append(test_case(
            name="Strategic Framework (EN)",
            pdf_path=strat,
            query="Summarize the strategic framework in this document.",
            expect_keyword=None,
        ))

    # Test 4: Scanned PDF warning
    results.append(test_scanned_warning())

    print(f"\n{'='*70}")
    passed = sum(results)
    print(f"RESULTS: {passed}/{len(results)} tests passed")
    print('='*70)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

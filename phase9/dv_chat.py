#!/usr/bin/env python3
"""
Phase 9 — Step 2: multi-doc multi-round DV chat.

Reuses the base project's `choose_best_document_match` (in
backend/services/neo4j_document_index.py) to pick the right document for
each user query, then loads that doc into a per-doc conversation session.

Each doc gets its own messages list (so history is isolated); switching
docs suspends the old history and resumes the new one.

Per rules.md:
  - No truncation, no chunking, no embeddings.
  - MiniMax M3 via init_chat_model.
  - Standalone script (no FastAPI / live Neo4j / DB).
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

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

# Reuse the base project's scoring function (no live Neo4j needed)
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))
from services.neo4j_document_index import (  # noqa: E402
    Neo4jDocumentRecord,
    choose_best_document_match,
)

from langchain.chat_models import init_chat_model  # noqa: E402
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage  # noqa: E402
from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402
import fitz  # noqa: E402

# --- Constants ---------------------------------------------------------------

MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
MINIMAX_BASE_URL = os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1")
MODEL = "minimax-m3"
PROJECT_ID = 1
DOCS_DIR = REPO_ROOT / "backend/data/documents/project_1"
SUPPORTED_EXTS = {".pdf", ".md", ".markdown", ".txt"}

PRICING = {
    "standard": {"input": 0.60, "output": 2.40},
    "long_ctx": {"input": 1.20, "output": 4.80},
}
TIER_THRESHOLD = 512_000
SESSION_START = time.time()


# --- Seed docs (used for routing — small set with rich metadata) -------------

SEED_DOCS: List[Neo4jDocumentRecord] = [
    Neo4jDocumentRecord(
        project_id=PROJECT_ID,
        name="nike-10k-2023",
        file_path=str(DOCS_DIR / "31042021_nke-10k-2023.pdf"),
        description="Nike Inc annual report 10-K filing fiscal year 2023 financial statements revenue profit",
        tags=["nike", "finance", "annual-report", "10-K", "财务", "年报"],
        what_this_document_is_about="nike inc 2023 10-K annual report revenue $51.2 billion risk factors strategy direct-to-consumer wholesale",
        supported_queries=["Nike revenue 2023", "Nike risk factors", "Nike strategy"],
        out_of_scope=["how to make shoes", "running training tips", "如何制造跑鞋"],
        search_terms=["nike", "revenue", "10-K", "annual report", "财务", "年报"],
        content_preview="NIKE INC 2023 ANNUAL REPORT ON FORM 10-K. Fiscal year ended May 31, 2023. Total revenues $51,217 million.",
    ),
    Neo4jDocumentRecord(
        project_id=PROJECT_ID,
        name="renwuku",
        file_path=str(DOCS_DIR / "5cc12ddf_6 人物库 2.pdf"),
        description="Chinese philosophers and historical figures database 哲学家 历史人物 思想家",
        tags=["人物", "哲学", "历史", "哲学家", "思想家", "philosopher", "history"],
        what_this_document_is_about="哲学家 思想家 企业家 古代 现代 简介 语录 苏格拉底 柏拉图 孔子 老子",
        supported_queries=["列出哲学家", "苏格拉底思想", "孔子语录", "list philosophers", "who is Socrates"],
        out_of_scope=["股票投资", "金融分析", "stock market"],
        search_terms=["哲学家", "思想家", "孔子", "苏格拉底", "philosopher", "Socrates"],
        content_preview="人物库 — 收录中外哲学家、文学家、企业家等历史人物的简介与核心思想。包含苏格拉底、柏拉图、孔子、老子等。",
    ),
    Neo4jDocumentRecord(
        project_id=PROJECT_ID,
        name="biz-strategy-survey",
        file_path=str(DOCS_DIR / "66bbde2a_Departmental Survey for Biz Strategy.pdf"),
        description="Departmental survey for business strategy framework 战略 框架 部门 调研",
        tags=["strategy", "business", "framework", "战略", "框架", "部门"],
        what_this_document_is_about="business strategy framework departmental survey goals objectives SWOT competitive analysis market positioning",
        supported_queries=["strategy framework", "SWOT analysis", "战略框架", "部门调研"],
        out_of_scope=["personal finance", "股票分析"],
        search_terms=["strategy", "framework", "SWOT", "战略", "框架"],
        content_preview="Departmental Survey for Business Strategy. Goals, objectives, and competitive analysis framework for FY24 planning.",
    ),
    Neo4jDocumentRecord(
        project_id=PROJECT_ID,
        name="shuoshuo-shuangxuan",
        file_path=str(DOCS_DIR / "08ce0b6f_25级专硕双选协议.pdf"),
        description="Master student dual selection agreement form 专硕 双选 协议 导师",
        tags=["合同", "协议", "双选", "专硕", "agreement", "form"],
        what_this_document_is_about="专硕 导师 双选 协议 签字 时间 流程 表格",
        supported_queries=["双选流程", "导师选择", "agreement deadline", "双选协议时间"],
        out_of_scope=["课程内容", "course content"],
        search_terms=["双选", "协议", "导师", "agreement"],
        content_preview="25级专硕双选协议 — 导师与学生的双向选择协议表格, 含签字栏与时间要求.",
    ),
    Neo4jDocumentRecord(
        project_id=PROJECT_ID,
        name="c2m1",
        file_path=str(DOCS_DIR / "2561d459_C2M1.pdf"),
        description="Course 2 module 1 lecture notes 课程 模块 讲义",
        tags=["course", "lecture", "课程", "讲义"],
        what_this_document_is_about="course 2 module 1 lecture notes programming algorithms data structures",
        supported_queries=["C2M1 讲义", "course 2 module 1"],
        out_of_scope=["non-technical content"],
        search_terms=["C2M1", "course 2", "module 1"],
        content_preview="Course 2 Module 1 — Lecture notes on programming, algorithms, and data structures.",
    ),
    Neo4jDocumentRecord(
        project_id=PROJECT_ID,
        name="winter-sports",
        file_path=str(DOCS_DIR / "2a55e555_winter-sports.pdf"),
        description="Winter sports catalog and pricing 冬季运动 目录 价格",
        tags=["sports", "winter", "catalog", "运动", "冬季"],
        what_this_document_is_about="winter sports equipment catalog pricing skis snowboards jackets",
        supported_queries=["winter sports prices", "ski catalog", "冬季运动目录"],
        out_of_scope=["summer sports", "stock analysis"],
        search_terms=["winter", "sports", "ski", "冬季运动"],
        content_preview="Winter sports catalog — skis, snowboards, jackets, boots. Pricing for the 2024 season.",
    ),
]


# --- Text extraction ---------------------------------------------------------

def _extract_text(file_path: Path) -> tuple[str, int]:
    if not file_path.exists():
        return f"(file not found: {file_path})", 0
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


# --- Doc routing -------------------------------------------------------------

def _route_doc(query: str, docs: List[Neo4jDocumentRecord]) -> Optional[Neo4jDocumentRecord]:
    """Pick the best doc for a query using base's scoring. None if no match."""
    return choose_best_document_match(query, docs)


def _find_doc_by_name(name: str, docs: List[Neo4jDocumentRecord]) -> Optional[Neo4jDocumentRecord]:
    """Exact name match (case-insensitive)."""
    n = name.strip().lower()
    for d in docs:
        if d.name.lower() == n:
            return d
    return None


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


def _build_system_prompt() -> str:
    return (
        "You are answering questions about a document the user provides.\n"
        "The first user message in this conversation contains the full document "
        "text with --- Page N --- markers. Subsequent user messages are questions.\n\n"
        "Rules:\n"
        "1. Answer ONLY from the document. If the answer is not there, say so.\n"
        "2. Cite page numbers, e.g. \"(page 3)\"."
    )


def _build_doc_message(doc: Neo4jDocumentRecord, full_text: str) -> HumanMessage:
    return HumanMessage(content=(
        f"Document: {doc.name}\n\n"
        f"Description: {doc.description}\n\n"
        f"--- FULL DOCUMENT TEXT ---\n\n{full_text}"
    ))


# --- Conversation meta -------------------------------------------------------

@dataclass
class Turn:
    doc: str
    question: str
    answer: str
    in_tokens: int
    out_tokens: int
    cache_read: int
    elapsed: float


class Conversation:
    def __init__(self):
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
        tier = "long_ctx" if in_tok > TIER_THRESHOLD else "standard"
        p = PRICING[tier]
        return (in_tok / 1_000_000) * p["input"] + (out_tok / 1_000_000) * p["output"]

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
        f"   ├─ doc:      {turn.doc}\n"
        f"   ├─ tokens:   in={turn.in_tokens:>7,}  out={turn.out_tokens:>5,}  ({tier})\n"
        f"   │            cache_read={turn.cache_read:>6,}  ({cache_pct:.1f}% cached)\n"
        f"   ├─ latency:  {turn.elapsed:5.1f}s  (cum LLM: {conv.total_elapsed:5.1f}s, wall: {wall:5.1f}s)\n"
        f"   └─ cost:     ${conv.turn_cost(turn):.4f}  "
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
    print(f"   ├─ tokens:       in={conv.total_in:,}  out={conv.total_out:,}")
    print(f"   ├─ cache:        {conv.total_cache_read:,} tokens ({cache_pct:.1f}%)")
    print(f"   ├─ time:         LLM={conv.total_elapsed:.1f}s  wall={wall:.1f}s  "
          f"({avg_tps:.0f} tok/s output)")
    print(f"   └─ cost:         ${cum_cost:.4f}")


# --- DocSession — per-doc conversation state ---------------------------------

class DocSession:
    """One conversation per doc. Messages seeded with system + doc content."""

    def __init__(self, doc: Neo4jDocumentRecord, system_message: SystemMessage):
        self.doc = doc
        full_text, _ = _extract_text(Path(doc.file_path))
        self.doc_message = _build_doc_message(doc, full_text)
        self.messages: list = [system_message, self.doc_message]
        self.turns = 0

    def ask(self, question: str, llm: BaseChatModel) -> tuple[str, int, int, int, float]:
        """Append Q, call LLM, append A. Returns (answer, in_tok, out_tok, cache_read, elapsed)."""
        self.messages.append(HumanMessage(content=question))
        t0 = time.time()
        resp = llm.invoke(self.messages)
        elapsed = time.time() - t0
        answer = resp.content if isinstance(resp.content, str) else str(resp.content)
        self.messages.append(AIMessage(content=answer))
        usage = getattr(resp, "usage_metadata", None) or {}
        details = usage.get("input_token_details", {}) or {}
        in_tok = int(usage.get("input_tokens", 0))
        out_tok = int(usage.get("output_tokens", 0))
        cache_read = int(details.get("cache_read", 0) or details.get("cached_tokens", 0))
        self.turns += 1
        return answer, in_tok, out_tok, cache_read, elapsed


# --- REPL --------------------------------------------------------------------

HELP_TEXT = """\
Commands:
  /docs              List all available documents
  /doc <name>        Switch to a specific document (manual override)
  /stats             Show conversation totals
  /help              Show this help
  /quit              Exit

Type any other text to ask a question — the system will route it
to the most relevant document (EN + ZH supported).
"""


def _list_docs(docs: List[Neo4jDocumentRecord]) -> str:
    lines = [f"   {len(docs)} documents available:"]
    for d in docs:
        lines.append(f"     - {d.name:<22}  {d.description[:60]}")
    return "\n".join(lines)


def _repl(
    llm: BaseChatModel,
    system_message: SystemMessage,
    docs: List[Neo4jDocumentRecord],
    conv: Conversation,
) -> None:
    print(f"\n{'='*60}")
    print(f"Multi-doc chat — {_list_docs(docs)}")
    print(f"\nType /help for commands\n")

    # Active doc + per-doc sessions
    active_doc: Optional[Neo4jDocumentRecord] = None
    sessions: Dict[str, DocSession] = {}

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
        if low == "/docs":
            print(_list_docs(docs))
            continue
        if low == "/stats":
            _print_session_summary(conv)
            continue
        if low.startswith("/doc "):
            name = raw[len("/doc "):].strip()
            doc = _find_doc_by_name(name, docs)
            if doc is None:
                print(f"  ✗ no doc named {name!r}. Try /docs to list.")
                continue
            active_doc = doc
            print(f"  → switched to '{doc.name}' (manual override)")
            continue

        # --- Normal question — route to a doc ---
        if active_doc is None:
            doc = _route_doc(raw, docs)
            if doc is None:
                print(f"  ✗ no doc matches query. Try /doc <name> to pick one, or /docs to list.")
                continue
            active_doc = doc
            print(f"  → routed to '{doc.name}'")

        # Get or create the per-doc session
        if active_doc.name not in sessions:
            sessions[active_doc.name] = DocSession(active_doc, system_message)
        session = sessions[active_doc.name]

        # Ask
        try:
            answer, in_tok, out_tok, cache_read, elapsed = session.ask(raw, llm)
        except Exception as e:
            print(f"  ✗ error: {e}")
            continue

        turn = Turn(
            doc=active_doc.name, question=raw, answer=answer,
            in_tokens=in_tok, out_tokens=out_tok, cache_read=cache_read,
            elapsed=elapsed,
        )
        conv.add(turn)

        print(f"\n🤖 {answer}")
        print(_format_session_footer(turn, conv))


# --- Entry point -------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 9 / Step 2 — multi-doc multi-round DV chat.",
    )
    args = parser.parse_args()

    # Use the seed docs (in production, this would be Neo4jDocumentIndex().list_documents(...))
    docs = SEED_DOCS
    print(f"📚 {len(docs)} documents loaded for routing")
    for d in docs:
        exists = Path(d.file_path).exists()
        flag = "✓" if exists else "✗ missing"
        print(f"   {flag}  {d.name}")

    # Build LLM
    llm = _make_llm()
    print(f"\nLLM: {MODEL}")

    # Stable system message
    system_message = SystemMessage(content=_build_system_prompt())

    # REPL
    conv = Conversation()
    _repl(llm, system_message, docs, conv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
Phase 9 — Step 2.10+: integrated DV chat with LLM semantic routing.

Wires phase9/route_semantic.py into the REPL:

  - Loads the real Neo4j catalog (no SEED_DOCS)
  - LLM semantic routing picks primary + supporting docs
  - String matching available as fallback (--route string)
  - Multi-doc load: primary (full) + each supporting (capped)
  - New commands: /route (llm|string), /docs, /doc <name>, /stats, /help

Per rules.md:
  - No truncation, no chunking, no embeddings.
  - MiniMax M3 via init_chat_model.
  - Standalone script (no FastAPI / live Neo4j / DB).

Run:
  python phase9/dv_chat.py --route llm        # default
  python phase9/dv_chat.py --route string
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv

# .env resolution (works as script AND in REPL)
try:
    _env_path = Path(__file__).resolve().parent.parent.parent / ".env"
except NameError:
    _env_path = Path(os.getcwd()) / ".env"
if not _env_path.exists():
    _alt = Path(os.getcwd()).parent / ".env"
    if _alt.exists():
        _env_path = _alt
load_dotenv(_env_path)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "phase9"))
sys.path.insert(0, str(REPO_ROOT / "backend"))

from services.neo4j_document_index import (  # noqa: E402
    Neo4jDocumentIndex,
    Neo4jDocumentRecord,
    choose_best_document_match,
)
from legacy.route_semantic import (  # noqa: E402
    SUPPORTING_MAX_CHARS,
    PRIMARY_MAX_CHARS,
    SupportingDoc,
    _file_path_for,
    _read_doc_text,
    fetch_catalog,
    make_llm as _make_routing_llm,
    route_by_llm,
    route_by_string,
)

from langchain.chat_models import init_chat_model  # noqa: E402
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage  # noqa: E402
from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402

# --- Constants ---------------------------------------------------------------

MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
MINIMAX_BASE_URL = os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1")
MODEL = "minimax-m3"
PROJECT_ID = 1
NEO4J_URL = os.getenv("NEO4J_URL", "http://localhost:7474")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")
DOCS_BASE = REPO_ROOT / "backend/data/documents"
PRICING = {
    "standard": {"input": 0.60, "output": 2.40},
    "long_ctx": {"input": 1.20, "output": 4.80},
}
TIER_THRESHOLD = 512_000
SESSION_START = time.time()


# --- Real Neo4j-backed document list ---------------------------------------

@dataclass
class DocEntry:
    """A real doc loaded from Neo4j + filesystem."""
    name: str
    file_path: str
    about: str
    supported: List[str]
    out_of_scope: List[str]
    page_count: int

    @classmethod
    def from_neo4j_row(cls, r: dict) -> "DocEntry":
        return cls(
            name=r["name"],
            file_path=r["fp"] or "",
            about=r["about"] or "",
            supported=list(r["supports"] or []),
            out_of_scope=[ex["name"] for ex in (r["excludes"] or []) if ex.get("name")],
            page_count=0,
        )


def load_real_catalog(idx: Neo4jDocumentIndex) -> List[DocEntry]:
    rows = fetch_catalog(idx, PROJECT_ID)
    return [DocEntry.from_neo4j_row(r) for r in rows]


# --- Routing ---------------------------------------------------------------

@dataclass
class RouteResult:
    primary: Optional[str]
    primary_domain: Optional[str]
    primary_confidence: float
    supporting: List[SupportingDoc]
    reasoning: str
    method: str             # "llm" or "string"
    latency_s: float
    cache_read: int = 0


def route_query(query: str, entries: List[DocEntry],
                rows: List[dict], llm: BaseChatModel,
                method: str) -> RouteResult:
    """Run either LLM semantic or string-matching routing on `query`."""
    t0 = time.time()
    if method == "llm":
        decision, cache_read = route_by_llm(query, rows, llm)
        latency = time.time() - t0
        return RouteResult(
            primary=decision.primary,
            primary_domain=decision.primary_domain,
            primary_confidence=decision.primary_confidence,
            supporting=list(decision.supporting),
            reasoning=decision.reasoning,
            method="llm",
            latency_s=latency,
            cache_read=cache_read,
        )
    # string fallback
    records = [_entry_to_record(e) for e in entries]
    best = choose_best_document_match(query, records)
    latency = time.time() - t0
    if best is None:
        return RouteResult(
            primary=None, primary_domain=None, primary_confidence=0.0,
            supporting=[], reasoning="no match", method="string",
            latency_s=latency,
        )
    return RouteResult(
        primary=best.name, primary_domain=None, primary_confidence=1.0,
        supporting=[], reasoning="string-match", method="string",
        latency_s=latency,
    )


def _entry_to_record(e: DocEntry) -> Neo4jDocumentRecord:
    """Convert a DocEntry into a Neo4jDocumentRecord for base's string scoring."""
    return Neo4jDocumentRecord(
        project_id=PROJECT_ID,
        name=e.name,
        file_path=e.file_path,
        description="",
        tags=[],
        what_this_document_is_about=e.about,
        supported_queries=list(e.supported),
        out_of_scope=list(e.out_of_scope),
        search_terms=[],
        content_preview="",
        doc_index_id=None,
        context_doc_id=0,
    )


# --- Multi-doc context loader ----------------------------------------------

def load_multi_doc_context(
    primary_name: str,
    supporting: List[SupportingDoc],
    idx: Neo4jDocumentIndex,
) -> str:
    """Concatenate primary + supporting docs into a single context string."""
    parts: List[str] = []
    primary_path = _file_path_for(idx, PROJECT_ID, primary_name)
    primary_text = _read_doc_text(primary_path, PRIMARY_MAX_CHARS)
    parts.append(
        f"=== Document 1 (PRIMARY): {primary_name} ===\n{primary_text}"
        if primary_text else
        f"=== Document 1 (PRIMARY): {primary_name} ===\n(no extractable text)"
    )
    for i, sup in enumerate(supporting, start=2):
        sup_path = _file_path_for(idx, PROJECT_ID, sup.name)
        sup_text = _read_doc_text(sup_path, SUPPORTING_MAX_CHARS)
        reason_line = f"\n[Reason: {sup.reason}]" if sup.reason else ""
        parts.append(
            f"=== Document {i} (SUPPORTING): {sup.name} ==={reason_line}\n{sup_text}"
            if sup_text else
            f"=== Document {i} (SUPPORTING): {sup.name} ==={reason_line}\n(no extractable text)"
        )
    return "\n\n".join(parts)


# --- LLM -------------------------------------------------------------------

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
        "You are answering questions about documents the user provides.\n"
        "The first user message in this conversation contains the full document "
        "text(s) with --- Page N --- markers. Subsequent user messages are questions.\n\n"
        "Rules:\n"
        "1. Answer ONLY from the documents. If the answer is not there, say so.\n"
        "2. Cite page numbers and document number, e.g. \"(Document 1, page 3)\".\n"
        "3. When multiple documents are provided, weave them together — note where "
        "they agree, disagree, or complement each other.\n"
        "4. If supporting documents don't add relevant context, ignore them and "
        "answer from the primary."
    )


# --- Conversation meta -----------------------------------------------------

@dataclass
class Turn:
    doc: str
    supporting: List[str]
    question: str
    answer: str
    in_tokens: int
    out_tokens: int
    cache_read: int
    elapsed: float
    routing_method: str
    routing_latency: float
    primary_domain: Optional[str]
    primary_confidence: float


class Conversation:
    def __init__(self):
        self.turns: List[Turn] = []
        self.total_in = 0
        self.total_out = 0
        self.total_cache_read = 0
        self.total_elapsed = 0.0
        self.total_routing_latency = 0.0

    def add(self, turn: Turn) -> None:
        self.turns.append(turn)
        self.total_in += turn.in_tokens
        self.total_out += turn.out_tokens
        self.total_cache_read += turn.cache_read
        self.total_elapsed += turn.elapsed
        self.total_routing_latency += turn.routing_latency

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
    supporting_str = ("+ " + ", ".join(turn.supporting)) if turn.supporting else ""
    domain_str = f" domain={turn.primary_domain}" if turn.primary_domain else ""
    return (
        f"   ├─ doc:      {turn.doc} {supporting_str}\n"
        f"   ├─ routed:   {turn.routing_method}"
        f"  ({turn.primary_confidence:.2f}{domain_str}, "
        f"{turn.routing_latency:.1f}s routing)\n"
        f"   ├─ tokens:   in={turn.in_tokens:>7,}  out={turn.out_tokens:>5,}  ({tier})\n"
        f"   │            cache_read={turn.cache_read:>6,}  ({cache_pct:.1f}% cached)\n"
        f"   ├─ latency:  {turn.elapsed:5.1f}s  "
        f"(cum LLM: {conv.total_elapsed:5.1f}s, wall: {wall:5.1f}s)\n"
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
    print(f"   ├─ time:         LLM={conv.total_elapsed:.1f}s  "
          f"routing={conv.total_routing_latency:.1f}s  wall={wall:.1f}s  "
          f"({avg_tps:.0f} tok/s output)")
    print(f"   └─ cost:         ${cum_cost:.4f}")


# --- MultiDocSession — per primary+supporting conversation -----------------

class MultiDocSession:
    """One conversation per primary doc (supporting are merged into context
    but identity is the primary's name)."""

    def __init__(self, primary_name: str, supporting: List[SupportingDoc],
                 system_message: SystemMessage, idx: Neo4jDocumentIndex):
        self.primary_name = primary_name
        self.supporting = list(supporting)
        # Stable doc header so cache hits across turns within same primary
        ctx = load_multi_doc_context(primary_name, supporting, idx)
        self.doc_message = HumanMessage(content=(
            f"=== Documents in this conversation ===\n{ctx}"
        ))
        self.messages: list = [system_message, self.doc_message]
        self.turns = 0

    def ask(self, question: str, llm: BaseChatModel
            ) -> tuple[str, int, int, int, float]:
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


# --- REPL ------------------------------------------------------------------

HELP_TEXT = """\
Commands:
  /docs                  List all available documents
  /doc <name>            Switch to a specific document (manual override)
  /route [llm|string]    Show or switch routing method (default: llm)
  /stats                 Show conversation totals
  /help                  Show this help
  /quit                  Exit

Type any other text to ask a question — the system routes it to the best
document (LLM semantic by default, or string matching as fallback).
"""


def _list_docs(entries: List[DocEntry]) -> str:
    lines = [f"   {len(entries)} documents:"]
    for d in entries:
        about_preview = d.about[:80] if d.about else "(no enrichment)"
        lines.append(f"     - {d.name:<46}  {about_preview}")
    return "\n".join(lines)


def _repl(
    llm: BaseChatModel,
    routing_llm: BaseChatModel,
    idx: Neo4jDocumentIndex,
    rows: List[dict],
    entries: List[DocEntry],
    system_message: SystemMessage,
    conv: Conversation,
    default_method: str,
) -> None:
    print(f"\n{'='*60}")
    print(f"Multi-doc chat (live Neo4j) — {len(entries)} docs available")
    print(f"Routing: {default_method} (use /route to change)")
    print(f"\nType /help for commands\n")

    active_doc: Optional[str] = None
    active_supporting: List[SupportingDoc] = []
    sessions: Dict[str, MultiDocSession] = {}
    method = default_method

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
            print(_list_docs(entries))
            continue
        if low == "/stats":
            _print_session_summary(conv)
            continue
        if low == "/route":
            print(f"  current routing: {method}  "
                  f"(options: llm, string)")
            continue
        if low.startswith("/route "):
            arg = raw[len("/route "):].strip().lower()
            if arg in ("llm", "string"):
                method = arg
                # Reset active doc when switching routing — the choice
                # might differ between methods
                active_doc = None
                active_supporting = []
                print(f"  → routing now: {method}  (active doc reset)")
            else:
                print(f"  ✗ unknown routing method: {arg!r}  (use llm or string)")
            continue
        if low.startswith("/doc "):
            name = raw[len("/doc "):].strip()
            match = next((e for e in entries
                          if e.name.lower() == name.lower()), None)
            if match is None:
                print(f"  ✗ no doc named {name!r}. Try /docs to list.")
                continue
            active_doc = match.name
            active_supporting = []
            print(f"  → switched to '{match.name}' (manual override)")
            continue

        # --- Normal question — route to a doc ---
        if active_doc is None:
            try:
                rr = route_query(raw, entries, rows, routing_llm, method)
            except Exception as e:
                print(f"  ✗ routing error: {e}")
                continue
            if rr.primary is None:
                print(f"  ✗ no doc matches. Try /doc <name> to pick one.")
                continue
            active_doc = rr.primary
            active_supporting = rr.supporting
            domain_str = f"  domain={rr.primary_domain}" if rr.primary_domain else ""
            sup_str = ""
            if rr.supporting:
                sup_str = f"  +{len(rr.supporting)} supporting"
            print(f"  → routed ({rr.method}, {rr.primary_confidence:.2f}"
                  f"{domain_str}, {rr.latency_s:.1f}s{sup_str}): "
                  f"{rr.primary}")
            if rr.supporting:
                for s in rr.supporting:
                    print(f"      + {s.name}")
            routing_latency = rr.latency_s
            routing_method = rr.method
            primary_domain = rr.primary_domain
            primary_confidence = rr.primary_confidence
        else:
            routing_latency = 0.0
            routing_method = "(manual)"
            primary_domain = None
            primary_confidence = 1.0

        # Get or create the per-primary session
        session_key = active_doc + "::" + ",".join(s.name for s in active_supporting)
        if session_key not in sessions:
            sessions[session_key] = MultiDocSession(
                active_doc, active_supporting, system_message, idx
            )
        session = sessions[session_key]

        # Ask
        try:
            answer, in_tok, out_tok, cache_read, elapsed = session.ask(raw, llm)
        except Exception as e:
            print(f"  ✗ error: {e}")
            continue

        turn = Turn(
            doc=active_doc,
            supporting=[s.name for s in active_supporting],
            question=raw,
            answer=answer,
            in_tokens=in_tok,
            out_tokens=out_tok,
            cache_read=cache_read,
            elapsed=elapsed,
            routing_method=routing_method,
            routing_latency=routing_latency,
            primary_domain=primary_domain,
            primary_confidence=primary_confidence,
        )
        conv.add(turn)

        print(f"\n🤖 {answer}")
        print(_format_session_footer(turn, conv))


# --- Entry point -----------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 9 / Step 2.10+ — DV chat with LLM semantic routing.",
    )
    parser.add_argument("--route", choices=["llm", "string"], default="llm",
                        help="Routing method (default: llm)")
    args = parser.parse_args()

    print(f"🔌 Neo4j: {NEO4J_URL}")
    idx = Neo4jDocumentIndex(
        base_url=NEO4J_URL, username=NEO4J_USER, password=NEO4J_PASSWORD,
    )
    idx.ensure_constraints()

    # Load catalog from Neo4j (used for both display and LLM routing)
    rows = fetch_catalog(idx, PROJECT_ID)
    entries = load_real_catalog(idx)
    print(f"📚 {len(entries)} documents loaded from project {PROJECT_ID}")

    # Build LLMs (one for routing, one for chat — could be same)
    routing_llm = _make_routing_llm()
    chat_llm = _make_llm()
    print(f"🤖 LLM: {MODEL}")

    system_message = SystemMessage(content=_build_system_prompt())

    conv = Conversation()
    _repl(chat_llm, routing_llm, idx, rows, entries, system_message, conv,
          default_method=args.route)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
#!/usr/bin/env python3
"""
Phase 9 — Query side (single entry point).

Consolidates the previously-separate route_semantic.py / dv_chat.py /
eval_routing.py / eval_routing_deep.py / query_deep.py into one CLI:

  python phase9/query.py route    "Nike revenue 2023"
  python phase9/query.py answer   "compare Nike strategy with industry trends"
  python phase9/query.py chat
  python phase9/query.py eval     [--method string|llm|deep|all]
  python phase9/query.py catalog  [--limit 1000]
  python phase9/query.py prompt   "binary classification neural network"

Three routing methods:
  --method string    base's choose_best_document_match (cheap, 57% acc)
  --method llm       raw llm.invoke on catalog prompt (~93% acc, ~10s)
  --method deep      DeepAgent with subagent orchestration (~93% acc, ~20s,
                     supports multi-doc + memory + future skills/HITL)

Build side stays in phase9/build_graphindex.py.

Per rules.md: no truncation, no chunking, no embeddings; MiniMax M3 only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Repo + backend path resolution
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "backend"))
if str(REPO_ROOT / "learning" / "phase9") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "learning" / "phase9"))

from dotenv import load_dotenv  # noqa: E402

try:
    _env = Path(__file__).resolve().parent.parent / ".env"
except NameError:
    _env = Path(os.getcwd()) / ".env"
load_dotenv(_env)

from langchain.chat_models import init_chat_model  # noqa: E402
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage  # noqa: E402
from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402
import fitz  # noqa: E402

from services.neo4j_document_index import (  # noqa: E402
    Neo4jDocumentIndex,
    Neo4jDocumentRecord,
    choose_best_document_match,
)

# --- Constants -------------------------------------------------------------

MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
MINIMAX_BASE_URL = os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1")
MODEL = "minimax-m3"
PROJECT_ID = 1
# Char caps per doc. MiniMax M3 supports 1M-token context, so we can
# afford a lot more than the legacy 30K/15K defaults. 10M chars is
# effectively no cap for normal documents (10-K, contracts, reports)
# — just a safety net to prevent OOM on truly gigantic files. The LLM
# will see the full document in one call.
PRIMARY_MAX_CHARS = 10_000_000
SUPPORTING_MAX_CHARS = 10_000_000
PRICING = {"standard": {"input": 0.60, "output": 2.40},
           "long_ctx": {"input": 1.20, "output": 4.80}}
TIER_THRESHOLD = 512_000
SESSION_START = time.time()


# --- Catalog fetch + format -----------------------------------------------

CATALOG_CYPHER = """
MATCH (d:Document {project_id: $pid})
WITH d, coalesce(d.out_of_scope, []) AS ex_names
UNWIND ex_names AS ex_name
OPTIONAL MATCH (other:Document {name: ex_name})
WITH d, collect({
    name: other.name,
    about: COALESCE(other.what_this_document_is_about,
                    other.content_preview, ''),
    supports: COALESCE(other.supported_queries,
                       other.search_terms, [])
}) AS excluded_full
RETURN d.name AS name,
       coalesce(d.file_path, '') AS fp,
       coalesce(d.what_this_document_is_about,
                d.content_preview, '') AS about,
       coalesce(d.supported_queries, d.search_terms, []) AS supports,
       excluded_full AS excludes,
       coalesce(d.context_doc_id, 0) AS cid
"""


def fetch_catalog(idx: Neo4jDocumentIndex, project_id: int) -> List[Dict[str, Any]]:
    return idx._run_cypher(CATALOG_CYPHER, {"pid": project_id})


def format_catalog(rows: List[Dict[str, Any]], limit_chars: int = 200_000) -> str:
    parts: List[str] = []
    for i, r in enumerate(rows, 1):
        about = r["about"] or ""
        supports = list(r["supports"] or [])
        excludes = list(r["excludes"] or [])
        parts.append(f"[{i}] {r['name']}")
        parts.append(f"  about: {about}")
        if supports:
            parts.append(f"  supports: {supports[:5]}")
        if excludes:
            parts.append(f"  excludes:")
            for ex in excludes:
                ex_about = ex.get("about") or ""
                ex_supports = ex.get("supports") or []
                if not ex.get("name"):
                    continue
                parts.append(f"    - {ex['name']}")
                parts.append(f"      about: {ex_about[:200]}")
                if ex_supports:
                    parts.append(f"      supports: {ex_supports[:5]}")
    text = "\n".join(parts)
    if len(text) > limit_chars:
        text = text[:limit_chars] + f"\n... [truncated at {limit_chars:,} chars]"
    return text


# --- Routing: raw llm.invoke ---------------------------------------------

ROUTING_SYSTEM_TEMPLATE = """You are a routing agent. Pick the best document for the user query, and identify any cross-domain supporting documents.

Use semantic understanding, not just keyword overlap. Consider:
- What the document is about (about field)
- What questions the document can answer (supports field)
- What topics the document explicitly does NOT cover (excludes — note the about/supports of each excluded doc)

Domain-awareness rules:
- Group documents by semantic domain (e.g. "deep_learning_course", "philosophy_and_strategy", "financial_report", "scanned_handbook", "test_placeholder")
- Use lowercase_snake_case short tags for primary_domain (max ~30 chars)
- If the query clearly spans multiple domains (e.g. "compare Nike strategy with industry trends"), include 1-3 supporting documents from RELATED domains — each with a concrete reason explaining what context it adds
- If the query is single-domain, leave supporting as an empty array []
- Prefer a PARTIAL match with low confidence over returning null — if any document's about or supports is even loosely related, pick it
- Only return null if EVERY document is clearly unrelated
- Do NOT pad the supporting list — only include documents that genuinely add context
- Supporting documents should come from different domains than primary

Available documents in this project:
{catalog}

Reply ONLY with a JSON object on a single line:
{{"primary": "<exact doc name>", "primary_domain": "<short_domain_tag>", "primary_confidence": <0.0-1.0>, "supporting": [{{"name": "<exact doc name>", "reason": "<why it adds context>"}}], "reasoning": "<one short sentence>"}}

If NONE of the documents are relevant, reply:
{{"primary": null, "primary_domain": null, "primary_confidence": 0.0, "supporting": [], "reasoning": "<why>"}}

Do NOT include any <think> blocks, commentary, or extra text."""


@dataclass
class SupportingDoc:
    name: str
    reason: str


@dataclass
class RouteDecision:
    primary: Optional[str]
    primary_domain: Optional[str]
    primary_confidence: float
    supporting: List[SupportingDoc]
    reasoning: str

    @property
    def name(self) -> Optional[str]:
        return self.primary

    @property
    def confidence(self) -> float:
        return self.primary_confidence


def _parse_decision(text: str) -> RouteDecision:
    if "<think>" in text and "</think>" in text:
        text = text.split("</think>", 1)[1].strip()
    start = text.find("{")
    if start < 0:
        raise ValueError(f"no JSON object in: {text[:200]}")
    depth, in_string, escape = 0, False, False
    end = -1
    for i in range(start, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end < 0:
        # Truncation recovery: close any unclosed braces/brackets
        partial = text[start:]
        last_full = partial.rfind("},")
        if last_full < 0:
            last_full = partial.rfind("],")
        if last_full < 0:
            raise ValueError(f"unbalanced JSON in: {text[:200]}")
        truncated = partial[:last_full + 1]
        opens = truncated.count("{") - truncated.count("}")
        brackets = truncated.count("[") - truncated.count("]")
        truncated += "]" * max(brackets, 0) + "}" * max(opens, 0)
        try:
            data = json.loads(truncated)
        except Exception:
            raise ValueError(f"unbalanced JSON in: {text[:200]}")
    else:
        data = json.loads(text[start:end + 1])

    primary = data.get("primary")
    if primary is not None or "primary" in data:
        supporting_raw = data.get("supporting", [])
        supporting = [SupportingDoc(name=s.get("name", ""), reason=s.get("reason", ""))
                      for s in supporting_raw if s.get("name")]
        return RouteDecision(
            primary=primary if primary else None,
            primary_domain=data.get("primary_domain"),
            primary_confidence=float(data.get("primary_confidence", 0.0)),
            supporting=supporting,
            reasoning=data.get("reasoning", ""),
        )
    return RouteDecision(
        primary=data.get("name"),
        primary_domain=None,
        primary_confidence=float(data.get("confidence", 0.0)),
        supporting=[],
        reasoning=data.get("reasoning", ""),
    )


def make_llm(temperature: float = 0.0, max_tokens: int = 1024) -> BaseChatModel:
    if not MINIMAX_API_KEY:
        raise RuntimeError("MINIMAX_API_KEY not set in .env")
    return init_chat_model(
        model=MODEL,
        model_provider="openai",
        api_key=MINIMAX_API_KEY,
        base_url=MINIMAX_BASE_URL,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def route_by_llm(query: str, rows: List[Dict[str, Any]],
                 llm: BaseChatModel) -> Tuple[RouteDecision, int]:
    system = SystemMessage(content=ROUTING_SYSTEM_TEMPLATE.format(
        catalog=format_catalog(rows)))
    resp = llm.invoke([system, HumanMessage(content=query)])
    text = resp.content if isinstance(resp.content, str) else str(resp.content)
    decision = _parse_decision(text)
    usage = getattr(resp, "usage_metadata", None) or {}
    details = usage.get("input_token_details", {}) or {}
    cache_read = int(details.get("cache_read", 0) or details.get("cached_tokens", 0))
    return decision, cache_read


def route_by_string(query: str, rows: List[Dict[str, Any]]) -> Optional[str]:
    records = []
    for r in rows:
        excluded_names = [ex["name"] for ex in (r["excludes"] or []) if ex.get("name")]
        records.append(Neo4jDocumentRecord(
            project_id=PROJECT_ID, name=r["name"], file_path=r["fp"] or "",
            description="", tags=[],
            what_this_document_is_about=r["about"] or "",
            supported_queries=list(r["supports"] or []),
            out_of_scope=excluded_names, search_terms=[],
            content_preview="", doc_index_id=None, context_doc_id=r["cid"] or 0,
        ))
    best = choose_best_document_match(query, records)
    return best.name if best else None


# --- Multi-doc context loader --------------------------------------------

_FILE_PATH_CACHE: Dict[str, str] = {}


def _read_doc_text(file_path: str, max_chars: int) -> str:
    if not file_path or not Path(file_path).exists():
        return ""
    ext = Path(file_path).suffix.lower()
    if ext == ".pdf":
        doc = fitz.open(file_path)
        out: List[str] = []
        total = 0
        for i in range(len(doc)):
            if total >= max_chars:
                out.append(f"\n... [truncated after page {i+1}/{len(doc)}]")
                break
            page_text = doc[i].get_text("text").strip()
            if page_text:
                chunk = f"--- Page {i+1}/{len(doc)} ---\n{page_text}"
                out.append(chunk)
                total += len(chunk)
        doc.close()
        return "\n\n".join(out)
    return Path(file_path).read_text(encoding="utf-8", errors="ignore")[:max_chars]


def _file_path_for(idx: Neo4jDocumentIndex, name: str) -> str:
    if name in _FILE_PATH_CACHE:
        return _FILE_PATH_CACHE[name]
    node = idx.get_document(project_id=PROJECT_ID, name=name)
    path = node.file_path if node else ""
    _FILE_PATH_CACHE[name] = path
    return path


def load_multi_doc_context(primary: Optional[str],
                            supporting: List[SupportingDoc],
                            idx: Neo4jDocumentIndex) -> str:
    parts: List[str] = []
    if primary:
        path = _file_path_for(idx, primary)
        text = _read_doc_text(path, PRIMARY_MAX_CHARS)
        parts.append(f"=== Document 1 (PRIMARY): {primary} ===\n{text}"
                     if text else
                     f"=== Document 1 (PRIMARY): {primary} ===\n(no extractable text)")
    for i, sup in enumerate(supporting, 2):
        path = _file_path_for(idx, sup.name)
        text = _read_doc_text(path, SUPPORTING_MAX_CHARS)
        reason = f"\n[Reason: {sup.reason}]" if sup.reason else ""
        parts.append(f"=== Document {i} (SUPPORTING): {sup.name} ==={reason}\n{text}"
                     if text else
                     f"=== Document {i} (SUPPORTING): {sup.name} ==={reason}\n(no extractable text)")
    return "\n\n".join(parts)


ANSWER_SYSTEM = """You are a document-grounded analyst. Answer the user's question using the provided documents.

Rules:
1. Use ONLY the supplied documents. If the answer is not present, say so.
2. Cite document + page for every claim, e.g. "(Document 1, page 3)".
3. If multiple documents are listed, weave them together — note where they agree, disagree, or complement each other.
4. If supporting documents are included for context, mention when a supporting doc adds information that the primary doesn't have."""


def answer_multi_doc(query: str, combined_context: str,
                      llm: BaseChatModel) -> Tuple[str, int]:
    resp = llm.invoke([
        SystemMessage(content=ANSWER_SYSTEM),
        HumanMessage(content=f"Question:\n{query}\n\n--- Documents ---\n\n{combined_context}"),
    ])
    answer = resp.content if isinstance(resp.content, str) else str(resp.content)
    usage = getattr(resp, "usage_metadata", None) or {}
    details = usage.get("input_token_details", {}) or {}
    cache_read = int(details.get("cache_read", 0) or details.get("cached_tokens", 0))
    return answer, cache_read


def _strip_think(answer: str) -> str:
    if "<think>" in answer and "</think>" in answer:
        return answer.split("</think>", 1)[1].strip()
    return answer


def _extract_usage(resp) -> Tuple[int, int, int]:
    usage = getattr(resp, "usage_metadata", None) or {}
    in_tok = int(usage.get("input_tokens", 0))
    out_tok = int(usage.get("output_tokens", 0))
    details = usage.get("input_token_details", {}) or {}
    cache_read = int(details.get("cache_read", 0) or details.get("cached_tokens", 0))
    return in_tok, out_tok, cache_read


def _print_turn_footer(label: str, in_tok: int, out_tok: int,
                        cache_read: int, elapsed: float) -> None:
    tier = "long-ctx" if in_tok > TIER_THRESHOLD else "standard"
    cache_pct = 100 * cache_read / in_tok if in_tok else 0
    print(f"   ├─ [{label}] tokens: in={in_tok:>7,}  out={out_tok:>5,}  ({tier})")
    print(f"   │            cache_read={cache_read:>6,}  ({cache_pct:.1f}% cached)")
    print(f"   └─ latency:  {elapsed:5.1f}s")


# --- Mode: route (single-shot) ------------------------------------------

def cmd_route(query: str, method: str) -> int:
    idx = Neo4jDocumentIndex()
    rows = fetch_catalog(idx, PROJECT_ID)

    if method == "string":
        t0 = time.time()
        name = route_by_string(query, rows)
        elapsed = time.time() - t0
        print(f"Query: {query!r}")
        print(f"  string → {name}  (latency {elapsed*1000:.0f} ms)")
        return 0 if name is not None or _is_irrelevant_query(query) else 0

    # llm or deep both need an LLM
    llm = make_llm()

    if method == "llm":
        t0 = time.time()
        decision, cache_read = route_by_llm(query, rows, llm)
        elapsed = time.time() - t0
        print(f"Query: {query!r}")
        _print_decision("llm", decision)
        print(f"   ({elapsed:.2f}s, cache_read={cache_read:,})")
        return 0

    if method == "deep":
        from query_agent import get_query_agent
        agent = get_query_agent()
        t0 = time.time()
        result = agent.invoke(
            {"messages": [{"role": "user", "content":
                f"Route this query only — do NOT load any documents. Reply with JSON.\nQuery: {query}"}]},
            config={"configurable": {"thread_id": "phase9-route"}},
        )
        elapsed = time.time() - t0
        answer = _strip_think(result["messages"][-1].content)
        # Try to parse a primary out of the final answer
        primary = _quick_extract_primary(answer)
        print(f"Query: {query!r}")
        print(f"  deep → {primary}")
        print(f"   ({elapsed:.2f}s)")
        if len(answer) < 400:
            print(f"   raw: {answer}")
        return 0

    print(f"unknown method: {method}", file=sys.stderr)
    return 1


def _is_irrelevant_query(query: str) -> bool:
    return False  # no ground truth in this CLI


def _quick_extract_primary(text: str) -> Optional[str]:
    """Try to pull a primary field out of an arbitrary LLM response."""
    m = re.search(r'"primary"\s*:\s*"([^"]+)"', text)
    return m.group(1) if m else None


def _print_decision(label: str, decision: RouteDecision) -> None:
    if decision.primary:
        domain = f" domain={decision.primary_domain}" if decision.primary_domain else ""
        print(f"  {label:<8} → {decision.primary}  "
              f"(confidence={decision.primary_confidence:.2f}){domain}")
        if decision.reasoning:
            print(f"           {decision.reasoning}")
    else:
        print(f"  {label:<8} → (no match)")
        if decision.reasoning:
            print(f"           {decision.reasoning}")
    if decision.supporting:
        print(f"  supporting ({len(decision.supporting)}):")
        for s in decision.supporting:
            print(f"    - {s.name}")
            if s.reason:
                print(f"      reason: {s.reason}")


# --- Mode: answer (route + load + synthesize) ----------------------------

def cmd_answer(query: str, method: str) -> int:
    idx = Neo4jDocumentIndex()
    rows = fetch_catalog(idx, PROJECT_ID)

    if method == "string":
        # String route → load + answer via llm.invoke
        name = route_by_string(query, rows)
        if not name:
            print(f"Query: {query!r}")
            print("  ✗ no match (string)")
            return 1
        decision = RouteDecision(primary=name, primary_domain=None,
                                 primary_confidence=1.0, supporting=[], reasoning="string")
    elif method == "llm":
        llm = make_llm()
        decision, _ = route_by_llm(query, rows, llm)
    else:  # deep
        from query_agent import get_query_agent
        agent = get_query_agent()
        t0 = time.time()
        result = agent.invoke(
            {"messages": [{"role": "user", "content": query}]},
            config={"configurable": {"thread_id": "phase9-answer"}},
        )
        elapsed = time.time() - t0
        answer_text = _strip_think(result["messages"][-1].content)
        in_tok, out_tok, cache_read = _extract_usage(result["messages"][-1])
        print(f"\nQuery: {query!r}")
        print(f"\n🤖 {answer_text}")
        _print_turn_footer("deep", in_tok, out_tok, cache_read, elapsed)
        return 0

    if not decision.primary:
        print(f"Query: {query!r}")
        print(f"  ✗ no match: {decision.reasoning}")
        return 1

    # llm.invoke path: load multi-doc context + synthesize
    print(f"Query: {query!r}")
    _print_decision(method, decision)

    t0 = time.time()
    context = load_multi_doc_context(decision.primary, decision.supporting, idx)
    load_time = time.time() - t0
    print(f"\n  loaded {len(context):,} chars  ({load_time:.1f}s)")

    llm = make_llm(temperature=0.2, max_tokens=8192)
    t0 = time.time()
    answer, ans_cache = answer_multi_doc(query, context, llm)
    ans_time = time.time() - t0
    in_tok, out_tok, _ = (0, 0, 0)  # approximate
    print(f"  synthesized  ({ans_time:.1f}s, cache_read={ans_cache:,})")

    print(f"\n{'='*70}\nANSWER\n{'='*70}\n")
    print(_strip_think(answer))
    print()
    return 0


# --- Mode: chat (REPL) ---------------------------------------------------

HELP_TEXT = """\
Phase 9 / query.py — interactive REPL (multi-turn, persistent thread).

Commands:
  /docs              List available documents
  /doc <name>        Switch to a specific doc (manual override)
  /method [s|l|d]    Show or switch routing method (string|llm|deep)
  /route             Re-route the last query (force fresh routing)
  /stats             Show session totals
  /help              Show this help
  /quit              Exit

Type any other text to ask a question — the system routes it to the best
document (default: deep, configurable via --method).
"""


def cmd_chat(method: str) -> int:
    idx = Neo4jDocumentIndex()
    rows = fetch_catalog(idx, PROJECT_ID)
    llm = make_llm() if method in ("llm",) else None
    deep_agent = None
    if method == "deep":
        from query_agent import get_query_agent
        deep_agent = get_query_agent()

    print(f"\n{'='*60}")
    print(f"Phase 9 / REPL — method={method}")
    print(f"Type /help for commands\n")

    active_doc: Optional[str] = None
    active_supporting: List[SupportingDoc] = []
    turn_count = 0
    method_now = method

    while True:
        try:
            raw = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye.")
            return 0
        if not raw:
            continue
        low = raw.lower()

        if low in ("/quit", "/exit", "/q"):
            print("bye.")
            return 0
        if low in ("/help", "/h"):
            print(HELP_TEXT)
            continue
        if low == "/docs":
            print(format_catalog(rows, limit_chars=2000))
            continue
        if low == "/stats":
            print(f"  turns: {turn_count}  active_doc: {active_doc}")
            continue
        if low == "/method":
            print(f"  current method: {method_now}")
            continue
        if low.startswith("/method "):
            arg = raw[len("/method "):].strip().lower()
            if arg in ("s", "string"):
                method_now = "string"
            elif arg in ("l", "llm"):
                method_now = "llm"
                if llm is None:
                    llm = make_llm()
            elif arg in ("d", "deep"):
                method_now = "deep"
                if deep_agent is None:
                    from query_agent import get_query_agent
                    deep_agent = get_query_agent()
            else:
                print(f"  ✗ unknown: {arg!r}  (use s/l/d)")
                continue
            active_doc = None
            print(f"  → method={method_now}  (active doc reset)")
            continue
        if low.startswith("/doc "):
            name = raw[len("/doc "):].strip()
            match = next((r for r in rows if r["name"] == name), None)
            if match is None:
                print(f"  ✗ no doc named {name!r}")
                continue
            active_doc = name
            active_supporting = []
            print(f"  → switched to {name}")
            continue
        if low == "/route":
            active_doc = None
            active_supporting = []
            print("  → will re-route next query")
            continue

        # Normal question — route if needed
        turn_count += 1
        if active_doc is None:
            if method_now == "string":
                name = route_by_string(raw, rows)
                if name:
                    decision = RouteDecision(primary=name, primary_domain=None,
                                             primary_confidence=1.0, supporting=[],
                                             reasoning="string")
                else:
                    decision = RouteDecision(primary=None, primary_domain=None,
                                             primary_confidence=0.0, supporting=[],
                                             reasoning="no match")
            elif method_now == "llm":
                decision, _ = route_by_llm(raw, rows, llm)
            else:  # deep
                from query_agent import get_query_agent
                agent = deep_agent or get_query_agent()
                result = agent.invoke(
                    {"messages": [{"role": "user", "content": raw}]},
                    config={"configurable": {"thread_id": "phase9-chat"}},
                )
                answer = _strip_think(result["messages"][-1].content)
                in_tok, out_tok, cache_read = _extract_usage(result["messages"][-1])
                elapsed = 0  # not measured
                print(f"\n🤖 {answer}")
                _print_turn_footer("deep", in_tok, out_tok, cache_read, elapsed)
                continue

            if not decision.primary:
                print(f"  ✗ no match: {decision.reasoning}")
                continue
            active_doc = decision.primary
            active_supporting = decision.supporting
            domain_str = f"  domain={decision.primary_domain}" if decision.primary_domain else ""
            sup_str = f"  +{len(decision.supporting)} supporting" if decision.supporting else ""
            print(f"  → routed ({method_now}, {decision.primary_confidence:.2f}"
                  f"{domain_str}{sup_str}): {active_doc}")
            for s in decision.supporting:
                print(f"      + {s.name}")

        # Load + answer
        t0 = time.time()
        context = load_multi_doc_context(active_doc, active_supporting, idx)
        chat_llm = make_llm(temperature=0.2, max_tokens=8192)
        answer, ans_cache = answer_multi_doc(raw, context, chat_llm)
        elapsed = time.time() - t0
        in_tok, out_tok, _ = 0, 0, 0
        print(f"\n🤖 {_strip_think(answer)}")
        _print_turn_footer(method_now, in_tok, out_tok, ans_cache, elapsed)


# --- Mode: eval ----------------------------------------------------------

EVAL_QUERIES: List[Dict[str, Any]] = [
    {"q": "Nike revenue 2023", "category": "A_simple_en_literal",
     "primary": "nke-10k-2023.pdf", "supporting": []},
    {"q": "Nike 10-K annual report financial statements",
     "category": "A_simple_en_literal",
     "primary": "nke-10k-2023.pdf", "supporting": []},
    {"q": "苏格拉底思想", "category": "B_simple_zh",
     "primary": "6 人物库.pdf", "supporting": []},
    {"q": "孔子语录", "category": "B_simple_zh",
     "primary": "6 人物库.pdf", "supporting": []},
    {"q": "binary classification neural network", "category": "C_conceptual",
     "primary": "C1M2.pdf", "supporting": []},
    {"q": "reinforcement learning Q-learning Deep Q-Network",
     "category": "C_conceptual",
     "primary": "lecture-notes-9.pdf", "supporting": []},
    {"q": "face recognition Siamese triplet loss", "category": "C_conceptual",
     "primary": "C4M4.pdf", "supporting": []},
    {"q": "word embedding Word2Vec GloVe", "category": "C_conceptual",
     "primary": "C5M2.pdf", "supporting": []},
    {"q": "compare Nike strategy with industry trends",
     "category": "D_cross_domain",
     "primary": "nke-10k-2023.pdf",
     "supporting": ["Departmental Survey for Biz Strategy.pdf",
                    "Strategic Framework Presentation.pdf"]},
    {"q": "apply entrepreneur thinking to AI strategy framework",
     "category": "D_cross_domain",
     "primary": "Strategic Framework Presentation.pdf",
     "supporting": ["6 人物库.pdf"]},
    {"q": "what is the weather today in Tokyo", "category": "E_irrelevant",
     "primary": None, "supporting": []},
    {"q": "how do I bake a chocolate cake", "category": "E_irrelevant",
     "primary": None, "supporting": []},
    {"q": "deep learning course logistics grading", "category": "F_ambiguous",
     "primary": "Week1_slides.pdf", "supporting": []},
    {"q": "machine learning project planning error analysis",
     "category": "F_ambiguous",
     "primary": "lecture-notes-6.pdf", "supporting": []},
]


@dataclass
class EvalRow:
    query: str
    category: str
    expected_primary: Optional[str]
    actual_primary: Optional[str]
    latency_s: float
    cache_read: int = 0
    method: str = ""


def _primary_hit(r: EvalRow) -> bool:
    if r.expected_primary is None:
        return r.actual_primary is None
    return r.actual_primary == r.expected_primary


def _run_string_eval(rows: List[Dict]) -> List[EvalRow]:
    return [EvalRow(query=q["q"], category=q["category"],
                    expected_primary=q["primary"],
                    actual_primary=route_by_string(q["q"], rows),
                    latency_s=0.0, method="string")
            for q in EVAL_QUERIES]


def _run_llm_eval(rows: List[Dict], llm) -> List[EvalRow]:
    out = []
    for q in EVAL_QUERIES:
        t0 = time.time()
        d, _ = route_by_llm(q["q"], rows, llm)
        out.append(EvalRow(query=q["q"], category=q["category"],
                           expected_primary=q["primary"],
                           actual_primary=d.primary,
                           latency_s=time.time() - t0, method="llm"))
    return out


def _run_deep_eval() -> List[EvalRow]:
    from query_agent import get_query_agent
    agent = get_query_agent()
    out = []
    for i, q in enumerate(EVAL_QUERIES, 1):
        t0 = time.time()
        result = agent.invoke(
            {"messages": [{"role": "user", "content":
                f"Route this query only — do NOT load any documents. Reply with JSON.\nQuery: {q['q']}"}]},
            config={"configurable": {"thread_id": f"eval-deep-{i}"}},
        )
        answer = _strip_think(result["messages"][-1].content)
        primary = _quick_extract_primary(answer)
        _, _, cache_read = _extract_usage(result["messages"][-1])
        out.append(EvalRow(query=q["q"], category=q["category"],
                           expected_primary=q["primary"],
                           actual_primary=primary,
                           latency_s=time.time() - t0,
                           cache_read=cache_read, method="deep"))
    return out


def _summarize(results: List[EvalRow]) -> Dict:
    total = len(results)
    hits = sum(1 for r in results if _primary_hit(r))
    by_cat: Dict[str, Dict] = {}
    for r in results:
        s = by_cat.setdefault(r.category, {"n": 0, "primary_hit": 0})
        s["n"] += 1
        if _primary_hit(r):
            s["primary_hit"] += 1
    latencies = [r.latency_s for r in results]
    return {
        "total": total,
        "primary_accuracy": hits / total if total else 0,
        "latency_mean": statistics.mean(latencies) if latencies else 0,
        "latency_max": max(latencies) if latencies else 0,
        "by_category": by_cat,
    }


def _render_method(label: str, summary: Dict, results: List[EvalRow]) -> str:
    lines = [f"\n{'='*70}\n  {label}\n{'='*70}"]
    lines.append(f"  queries run:      {summary['total']}")
    lines.append(f"  primary accuracy: {summary['primary_accuracy']*100:.0f}%")
    lines.append(f"  latency mean:     {summary['latency_mean']*1000:.0f} ms")
    lines.append(f"  latency max:      {summary['latency_max']*1000:.0f} ms")
    lines.append("")
    lines.append("  per-category:")
    for cat, s in sorted(summary["by_category"].items()):
        pa = s["primary_hit"] / s["n"] * 100 if s["n"] else 0
        lines.append(f"    {cat:30s}  n={s['n']}  primary={pa:3.0f}%")
    lines.append("")
    lines.append("  misroutes:")
    for r in results:
        if not _primary_hit(r):
            lines.append(f"    ✗ [{r.category}] {r.query!r}")
            lines.append(f"        expected:  {r.expected_primary}")
            lines.append(f"        actual:    {r.actual_primary}")
    return "\n".join(lines)


def _render_compare(summaries: Dict[str, Dict]) -> str:
    lines = [f"\n{'='*70}\n  COMPARISON\n{'='*70}"]
    cats = sorted(set(q["category"] for q in EVAL_QUERIES))
    lines.append(f"  {'category':30s}  string  llm.invoke  deepagent")
    for cat in cats:
        ns = summaries.get("string", {}).get("by_category", {}).get(cat, {}).get("n", 0)
        if not ns:
            continue
        ps = summaries["string"]["by_category"][cat]["primary_hit"] / ns * 100
        pl = summaries.get("llm", {}).get("by_category", {}).get(cat, {}).get("primary_hit", 0) / ns * 100
        pd = summaries.get("deep", {}).get("by_category", {}).get(cat, {}).get("primary_hit", 0) / ns * 100
        lines.append(f"  {cat:30s}  {ps:3.0f}%   {pl:3.0f}%       {pd:3.0f}%")
    ns = summaries.get("string", {}).get("primary_accuracy", 0) * 100
    nl = summaries.get("llm", {}).get("primary_accuracy", 0) * 100
    nd = summaries.get("deep", {}).get("primary_accuracy", 0) * 100
    lines.append(f"  {'OVERALL':30s}  {ns:3.0f}%   {nl:3.0f}%       {nd:3.0f}%")
    return "\n".join(lines)


def cmd_eval(method: str) -> int:
    idx = Neo4jDocumentIndex()
    rows = fetch_catalog(idx, PROJECT_ID)
    print(f"🔌 Neo4j: {len(rows)} docs in project {PROJECT_ID}")
    print(f"📋 Eval: {len(EVAL_QUERIES)} queries, methods={method}\n")

    methods_to_run = (["string", "llm", "deep"] if method == "all" else [method])
    summaries: Dict[str, Dict] = {}
    rows_by_method: Dict[str, List[EvalRow]] = {}

    for m in methods_to_run:
        print(f"  running {m}...", end=" ", flush=True)
        if m == "string":
            res = _run_string_eval(rows)
        elif m == "llm":
            llm = make_llm()
            res = _run_llm_eval(rows, llm)
        elif m == "deep":
            res = _run_deep_eval()
        else:
            continue
        summaries[m] = _summarize(res)
        rows_by_method[m] = res
        print(f"done ({len(res)} queries)")

    for m in methods_to_run:
        print(_render_method(m.upper(), summaries[m], rows_by_method[m]))

    if len(methods_to_run) > 1:
        print(_render_compare(summaries))

    return 0


# --- Mode: catalog / prompt ----------------------------------------------

def cmd_catalog(limit: int) -> int:
    idx = Neo4jDocumentIndex()
    rows = fetch_catalog(idx, PROJECT_ID)
    print(format_catalog(rows, limit_chars=limit))


def cmd_prompt(query: str) -> int:
    idx = Neo4jDocumentIndex()
    rows = fetch_catalog(idx, PROJECT_ID)
    catalog = format_catalog(rows)
    system_prompt = ROUTING_SYSTEM_TEMPLATE.format(catalog=catalog)
    print(f"\n{'='*70}\nSYSTEM MESSAGE ({len(system_prompt):,} chars)\n{'='*70}\n")
    print(system_prompt)
    print(f"\n{'='*70}\nUSER MESSAGE\n{'='*70}\n")
    print(query)
    print()


# --- Main -----------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 9 / query.py — multi-mode query CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--method", choices=["string", "llm", "deep"],
                        default="deep",
                        help="routing method (default: deep)")
    sub = parser.add_subparsers(dest="mode", required=True)

    p_route = sub.add_parser("route", help="single-shot routing decision")
    p_route.add_argument("query", help="the user query to route")

    p_answer = sub.add_parser("answer", help="route + load + synthesize answer")
    p_answer.add_argument("query", help="the user query to answer")

    p_chat = sub.add_parser("chat", help="interactive REPL")

    p_eval = sub.add_parser("eval", help="run eval suite")
    p_eval.add_argument("--method", choices=["string", "llm", "deep", "all"],
                        default="all", help="which method(s) to run")

    p_cat = sub.add_parser("catalog", help="print document catalog")
    p_cat.add_argument("--limit", type=int, default=100_000,
                       help="max chars to print")

    p_prompt = sub.add_parser("prompt", help="print the LLM system+user prompt")
    p_prompt.add_argument("query", help="the user query to build a prompt for")

    args = parser.parse_args()

    if not MINIMAX_API_KEY:
        sys.stderr.write("FATAL: MINIMAX_API_KEY not set in .env\n")
        return 1

    if args.mode == "route":
        return cmd_route(args.query, args.method)
    if args.mode == "answer":
        return cmd_answer(args.query, args.method)
    if args.mode == "chat":
        return cmd_chat(args.method)
    if args.mode == "eval":
        return cmd_eval(args.method)
    if args.mode == "catalog":
        cmd_catalog(args.limit)
        return 0
    if args.mode == "prompt":
        cmd_prompt(args.query)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
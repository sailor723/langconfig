#!/usr/bin/env python3
"""
Phase 9 / Step 2.5 — complete GraphIndex builder.

Reuses the base project's Neo4j types and helpers (services/neo4j_document_index.py)
but adds an actual enrichment pipeline that the production sync in
backend/api/knowledge/rag.py never runs (it passes enrichment=None).

The enrichment generator (`extract_document_enrichment`) was lifted from
backend/scripts/test_neo4j_document_kv_roundtrip.py — it lived as a nested
function inside a script and was effectively dead code. We extract it to
module level so we can call it from anywhere, and we swap the LLM to
MiniMax M3 (consistent with dv_chat.py).

Commands (query side moved to index_query.py):
  --show <name>           Dump the current node + enrichment for one doc
  --wipe-graph            Empty the Neo4j graph (Document + Entity nodes) for a project
  --rebuild-one <name>    Rebuild enrichment for one doc (LLM call)
  --rebuild-project       Rebuild enrichment for every Document node (LLM call)
  --build-graph           Rebuild the entity graph layer (Entity nodes + MENTIONS edges)
  --build-embeddings      Embed each Document node's routing blob (doc_embedding index)
  --build-entity-embeddings  Embed each Entity node's blob (entity_embedding index)
  --list / --ingest / --ingest-folder / --remove / --remove-folder / --purge / --show-agent
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from dotenv import load_dotenv

# .env resolution (works as script AND in REPL)
try:
    _env_path = Path(__file__).resolve().parent.parent.parent.parent / ".env"
except NameError:
    _env_path = Path(os.getcwd()) / ".env"
if not _env_path.exists():
    _alt = Path(os.getcwd()).parent / ".env"
    if _alt.exists():
        _env_path = _alt
load_dotenv(_env_path)

# Reuse base's Neo4j types + helpers
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))
from services.neo4j_document_index import (  # noqa: E402
    Neo4jDocumentEnrichment,
    Neo4jDocumentIndex,
    build_document_node_properties,
)
from services.neo4j_embedding_matcher import Neo4jEmbeddingMatcher  # noqa: E402

from db.database import SessionLocal
from models.core import ContextDocument, DocumentType, IndexingStatus

from langchain.chat_models import init_chat_model  # noqa: E402
from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402
from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

# --- Local defaults (domain logic, not configuration) ----------------------
_DOCS_BASE = REPO_ROOT / "backend/data/documents"
_SUPPORTED_EXTS = {".pdf", ".md", ".markdown", ".txt", ".json"}
_PROJECT_ID = int(os.getenv("GRAPHINDEX_DEFAULT_PROJECT_ID", "1"))


# --- Ontology source (single source of truth: .Codex/docs/graphindex-ontology.md) ---
# The md is parsed at import time into the controlled vocabularies below. The
# Pydantic schemas, the normalization map, and the prompt blocks are all built
# from ONTOLOGY, so changing a vocabulary is a one-file edit. A built-in
# fallback keeps the module importable if the md is missing or unparseable.

_ONTOLOGY_MD = REPO_ROOT / ".Codex" / "docs" / "graphindex-ontology.md"

_ONTOLOGY_FALLBACK = {
    "entity_type": [
        "Organization", "Industry", "Person", "Product", "Brand",
        "Geography", "Metric", "Department", "Concept",
    ],
    "role": ["subject", "competitor", "partner", "author", "source", "market", "other"],
    "genre": [
        "company_analysis", "industry_analysis", "comparison", "survey", "dossier",
        "strategic_framework", "financial_data", "source_document", "filing",
        "dashboard", "other",
    ],
    "primary_subject": [
        "economy_business_finance", "science_technology", "labour", "environment",
        "health", "education", "society", "politics", "other",
    ],
    "question_types": [
        "factual", "financial_metric", "comparison", "trend_analysis",
        "customer_support", "regulatory", "strategy_recommendation", "other",
    ],
}


def _md_table_values(text: str, header: str) -> list[str]:
    """Collect first-column backticked tokens from a markdown table."""
    start = text.find(header)
    if start < 0:
        return []
    lines = text[start:].splitlines()
    # Skip the header row and its "|---|---|" separator before data rows.
    for i, line in enumerate(lines):
        if line.startswith("|") and "---" in line and i > 0:
            lines = lines[i + 1:]
            break
    values: list[str] = []
    for line in lines:
        if not line.startswith("|"):
            if values:
                break  # table ended
            continue
        m = re.search(r"`([a-zA-Z][a-zA-Z0-9_]*)`", line)
        if m and m.group(1) not in values:
            values.append(m.group(1))
    return values


def _md_brace_values(text: str) -> list[str]:
    """Parse the `` `role` ∈ `{a, b, c}` `` idiom."""
    m = re.search(r"`\{([^}`]+)\}`", text)
    if not m:
        return []
    return [t.strip() for t in m.group(1).split(",") if t.strip()]


def _md_inline_values(text: str, section: str) -> list[str]:
    """Collect backticked snake_case tokens from a markdown section.

    Handles the `` `value1` · `value2` ... `` idiom, possibly wrapped over
    multiple lines. Stops at the next level-2/3 heading so later sections
    don't leak in.
    """
    start = text.find(section)
    if start < 0:
        return []
    body = text[start:]
    m = re.search(r"\n(?=#{2,3} )", body)
    if m:
        body = body[:m.start()]
    return list(dict.fromkeys(re.findall(r"`([a-z][a-z0-9_]*)`", body)))


def load_ontology() -> dict[str, list[str]]:
    """Parse the controlled vocabularies from the ontology md.

    Falls back to _ONTOLOGY_FALLBACK per-field when the md is missing,
    unparseable, or a section is not found.
    """
    try:
        text = _ONTOLOGY_MD.read_text(encoding="utf-8")
        parsed = {
            "entity_type": _md_table_values(text, "| `entity_type` |"),
            "role": _md_brace_values(text),
            "genre": _md_inline_values(text, "### 2.1 genre"),
            "primary_subject": _md_inline_values(text, "### 2.2 primary_subject"),
            "question_types": _md_inline_values(text, "### 2.4 question_types"),
        }
    except Exception as e:
        sys.stderr.write(f"WARNING: failed to read ontology md {_ONTOLOGY_MD}: {e}\n")
        return dict(_ONTOLOGY_FALLBACK)
    return {
        field: (values if values else _ONTOLOGY_FALLBACK[field])
        for field, values in parsed.items()
    }


ONTOLOGY = load_ontology()

# Dynamic Literal types — rebuilt whenever the md vocabulary changes.
EntityType = Literal[tuple(ONTOLOGY["entity_type"])]
Role = Literal[tuple(ONTOLOGY["role"])]
Genre = Literal[tuple(ONTOLOGY["genre"])]
PrimarySubject = Literal[tuple(ONTOLOGY["primary_subject"])]
QuestionType = Literal[tuple(ONTOLOGY["question_types"])]


def _ontology_prompt_block() -> str:
    """Render the controlled vocabularies for the enrichment prompt."""
    return "\n".join(
        f"- {field}: {', '.join(ONTOLOGY[field])}"
        for field in ("entity_type", "role", "genre", "primary_subject", "question_types")
    )



# --- Document loading (lifted from scripts/test_neo4j_document_kv_roundtrip.py) -

def _read_pdf_text(file_path: Path, max_chars: int = 0) -> str:
    """Read a PDF with PyMuPDF. Truncates at max_chars if > 0."""
    import fitz
    doc = fitz.open(str(file_path))
    parts: List[str] = []
    total = 0
    for i in range(len(doc)):
        if 0 < max_chars <= total:
            parts.append(f"\n... [truncated after page {i+1}/{len(doc)}]")
            break
        text = doc[i].get_text("text").strip()
        if text:
            chunk = f"--- Page {i+1}/{len(doc)} ---\n{text}"
            parts.append(chunk)
            total += len(chunk)
    doc.close()
    return "\n\n".join(parts)


def _read_text_file(file_path: Path, max_chars: int = 0) -> str:
    text = file_path.read_text(encoding="utf-8", errors="ignore")
    return text[:max_chars] if max_chars > 0 else text


def load_document_content(file_path: str, max_chars: int = 0) -> str:
    """Read the full text of a document based on its file extension.

    If max_chars > 0, truncates output to approximately that many characters.

    JSON note: a raw JSON file is technically readable as text but
    looks like a single dense blob to the LLM (no newlines between
    keys, deeply nested escapes, etc.). We re-emit it via
    `json.dumps(..., indent=2, ensure_ascii=False)` so the LLM gets
    a pretty-printed tree it can actually reason over. If parsing
    fails for any reason, we fall back to the raw text — never
    silently drop the file.
    """
    p = Path(file_path)
    if not p.exists():
        return ""
    ext = p.suffix.lower()
    if ext == ".pdf":
        return _read_pdf_text(p, max_chars=max_chars)
    if ext == ".json":
        try:
            raw = p.read_text(encoding="utf-8", errors="ignore")
            parsed = json.loads(raw) if raw.strip() else {}
            pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
        except Exception:
            pretty = p.read_text(encoding="utf-8", errors="ignore")
        if max_chars and len(pretty) > max_chars:
            pretty = pretty[:max_chars] + "\n…[truncated]"
        return pretty
    if ext in {".md", ".markdown", ".txt", ".yaml", ".yml"}:
        return _read_text_file(p, max_chars=max_chars)
    return _read_text_file(p, max_chars=max_chars)


def load_graphindex_metadata(file_path: str) -> dict:
    """For now we don't have a DocIndex client here; the full content is
    enough for the LLM to derive everything it needs. Returned as {} for
    compatibility with the build_document_node_properties signature."""
    return {}


# Per-doc char limits. Primary gets more; supporting is tighter.
_PRIMARY_MAX_CHARS = int(os.getenv("GRAPHINDEX_PRIMARY_MAX_CHARS", "10000000"))
_SUPPORTING_MAX_CHARS = int(os.getenv("GRAPHINDEX_SUPPORTING_MAX_CHARS", "10000000"))

# Cache file_path lookups so we don't hit Neo4j per doc load.
_FILE_PATH_CACHE: Dict[tuple, str] = {}


def _file_path_for(index: Neo4jDocumentIndex, project_id: int, name: str) -> str:
    """Look up file_path from Neo4j, with in-memory cache."""
    key = (project_id, name)
    if key in _FILE_PATH_CACHE:
        return _FILE_PATH_CACHE[key]
    node = index.get_document(project_id=project_id, name=name)
    path = node.file_path if node else ""
    _FILE_PATH_CACHE[key] = path
    return path


def load_doc_context(
    index: Neo4jDocumentIndex,
    project_id: int,
    doc_names: List[str],
    reasons: Optional[Dict[str, str]] = None,
) -> str:
    """Concatenate matched docs into a single human-readable string.

    Reads full text for each document, ordered by relevance (best first).
    First doc is marked PRIMARY, rest are SUPPORTING with their reason.
    """
    parts: List[str] = []
    for i, name in enumerate(doc_names, start=1):
        path = _file_path_for(index, project_id, name)
        max_chars = _PRIMARY_MAX_CHARS if i == 1 else _SUPPORTING_MAX_CHARS
        text = load_document_content(path, max_chars=max_chars)
        label = "PRIMARY" if i == 1 else "SUPPORTING"
        reason = (reasons or {}).get(name, "")
        reason_line = f"\n[Reason: {reason}]" if reason else ""
        parts.append(
            f"=== Document {i} ({label}): {name} ==={reason_line}\n{text}"
            if text else
            f"=== Document {i} ({label}): {name} ==={reason_line}\n(no extractable text)"
        )
    return "\n\n".join(parts)


# --- Enrichment schema (lifted from scripts/test_neo4j_document_kv_roundtrip.py) ---

class FewShotExample(BaseModel):
    query: str = Field(default="")
    answer_hint: str = Field(default="")


class DocumentEntity(BaseModel):
    """Typed noun entity mentioned in the document (docs/graphindex-ontology.md).

    entity_type and role are controlled vocabularies loaded from the
    ontology md (ONTOLOGY) at import time; the LLM must pick from them
    (unknown values normalize to the fallback in the parser).
    """
    name: str = Field(..., min_length=1, max_length=100,
                      description="Exact surface form of the entity as it appears in the document.")
    entity_type: EntityType = Field(..., description="Controlled entity type (see ontology spec).")
    role: Role = Field(default="other", description="Entity's role relative to the document.")


class DocumentCategories(BaseModel):
    """Controlled categorization of the document (docs/graphindex-ontology.md).

    genre / primary_subject / question_types are controlled vocabularies
    loaded from the ontology md (ONTOLOGY) at import time.
    """
    genre: Genre = Field(..., description="Document kind.")
    primary_subject: PrimarySubject = Field(
        ..., description="IPTC Media Topics-aligned top-level subject.")
    subjects: List[str] = Field(
        default_factory=list, max_length=5,
        description="Level-2 topics (e.g. financial performance, market position, "
                    "product portfolio, technology & innovation, operations, "
                    "strategy, organization, regulatory, transformation).",
    )
    question_types: List[QuestionType] = Field(
        default_factory=list, max_length=3,
        description="Kinds of questions this document can answer.",
    )
    financial_metrics: List[str] = Field(
        default_factory=list, max_length=10,
        description="IFRS/XBRL-aligned metric concepts (revenue, operating_profit, "
                    "net_income, ebitda_margin, current_assets, net_cash_flow, cagr, ...). "
                    "Only when the document is finance-related; empty otherwise.",
    )


class DocumentEnrichmentOutput(BaseModel):
    what_this_document_is_about: str = Field(
        default="",
        description="One-sentence description of what this document covers.",
    )
    supported_queries: List[str] = Field(
        default_factory=list,
        description="Natural-language questions this document can answer.",
    )
    few_shot: List[FewShotExample] = Field(default_factory=list)
    # Ontology enrichment (docs/graphindex-ontology.md)
    entities: List[DocumentEntity] = Field(
        default_factory=list, max_length=20,
        description="Typed noun entities mentioned in the document.",
    )
    categories: DocumentCategories = Field(
        default_factory=DocumentCategories,
        description="Controlled categorization (genre, subjects, question types, "
                    "financial metrics).",
    )
    tags: List[str] = Field(
        default_factory=list, max_length=10,
        description="Document-level tags derived from the top entities and key "
                    "topics; lowercase, no standalone dates/numbers.",
    )


# --- Controlled-vocabulary normalization --------------------------------------
# "Controlled + LLM maps" (docs/graphindex-ontology.md): the LLM occasionally
# invents enum members or malformed shapes. Coerce them to the safe fallback
# instead of failing the whole node.

# Fallbacks are derived from ONTOLOGY so they stay in sync with the md:
# 'Concept' is the catch-all entity type, 'other' the catch-all elsewhere.
_ENTITY_TYPE_FALLBACK = ONTOLOGY["entity_type"][-1]
_OTHER_FALLBACK = "other"


def _canonical_map(values: list[str]) -> dict[str, str]:
    """Map lowercase keys to canonical members, preserving original casing.

    entity_type members are PascalCase (FIBO-style names), the rest are
    lowercase snake; keying by lowercase lets _coerce_enum match
    case-insensitively while still returning the canonical form.
    """
    return {value.lower(): value for value in values}


# Canonical (schema-facing) members per field, keyed by their lowercase form —
# rebuilt from ONTOLOGY so normalization and the md never drift apart.
_ENUM_CANONICAL = {field: _canonical_map(ONTOLOGY[field]) for field in ONTOLOGY}

# LLM-friendly synonyms for the PascalCase entity_type vocabulary. The md's
# table literally lists "company / institution / agency" as the *meaning* of
# Organization, so a sloppy LLM echoes those words instead of the enum name —
# map them back to the canonical member.
_ENTITY_TYPE_SYNONYMS = {
    "company": "Organization", "corporation": "Organization",
    "institution": "Organization", "agency": "Organization",
    "country": "Geography", "region": "Geography", "nation": "Geography",
}


def _coerce_enum(value: Any, field: str, fallback: str) -> str:
    """Case-insensitive match against a controlled vocabulary.

    Returns the canonical member (e.g. 'industry' -> 'Industry',
    'economy, business, finance' -> 'economy_business_finance').
    """
    if not isinstance(value, str):
        return fallback
    key = value.strip().lower().replace(",", "").replace(" ", "_")
    if field == "entity_type" and key in _ENTITY_TYPE_SYNONYMS:
        return _ENTITY_TYPE_SYNONYMS[key]
    return _ENUM_CANONICAL[field].get(key, fallback)


def _str_list(value: Any, cap: int) -> list[str]:
    """Coerce to a cleaned string list, truncated to cap."""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        if len(out) >= cap:
            break
    return out


def _normalize_few_shot(raw: Any) -> list[dict]:
    out: list[dict] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and isinstance(item.get("query"), str):
                out.append({
                    "query": item["query"],
                    "answer_hint": str(item.get("answer_hint") or ""),
                })
                if len(out) >= 50:
                    break
    return out


def _normalize_entities(raw: Any) -> list[dict]:
    out: list[dict] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            out.append({
                "name": name.strip()[:100],
                "entity_type": _coerce_enum(item.get("entity_type"),
                                            "entity_type",
                                            _ENTITY_TYPE_FALLBACK),
                "role": _coerce_enum(item.get("role"), "role", _OTHER_FALLBACK),
            })
            if len(out) >= 20:
                break
    return out


def normalize_enrichment_data(data: Any) -> dict:
    """Coerce raw LLM JSON into the DocumentEnrichmentOutput shape.

    Unknown enum values fall back to 'other' (or 'Concept' for entity_type);
    lists are truncated to their caps; financial_metrics are dropped when the
    document is not finance-related (no 'financial_metric' question type).
    """
    data = data if isinstance(data, dict) else {}

    categories = data.get("categories") if isinstance(data.get("categories"), dict) else {}
    question_types = [
        _coerce_enum(q, "question_types", _OTHER_FALLBACK)
        for q in _str_list(categories.get("question_types"), 3)
    ]
    # IFRS/XBRL-anchored metrics only make sense for finance-related documents.
    financial_metrics = _str_list(categories.get("financial_metrics"), 10)
    if "financial_metric" not in question_types:
        financial_metrics = []

    return {
        "what_this_document_is_about": str(data.get("what_this_document_is_about") or ""),
        "supported_queries": _str_list(data.get("supported_queries"), 50),
        "few_shot": _normalize_few_shot(data.get("few_shot")),
        "entities": _normalize_entities(data.get("entities")),
        "categories": {
            "genre": _coerce_enum(categories.get("genre"), "genre", _OTHER_FALLBACK),
            "primary_subject": _coerce_enum(categories.get("primary_subject"),
                                            "primary_subject", _OTHER_FALLBACK),
            "subjects": _str_list(categories.get("subjects"), 5),
            "question_types": question_types,
            "financial_metrics": financial_metrics,
        },
        "tags": _str_list(data.get("tags"), 10),
    }


# --- LLM + enrichment (lifted from scripts/test_neo4j_document_kv_roundtrip.py) --

def make_llm() -> BaseChatModel:
    if not os.getenv("MINIMAX_API_KEY"):
        sys.stderr.write("FATAL: MINIMAX_API_KEY not set in .env\n")
        sys.exit(1)
    return init_chat_model(
        model=os.getenv("GRAPHINDEX_MODEL", "minimax-m3"),
        model_provider="openai",
        api_key=os.getenv("MINIMAX_API_KEY"),
        base_url=os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1"),
        temperature=0.2,
        max_tokens=2048,
        # Per-call timeout. Without this a hung API can leave the
        # backend blocked forever — which is exactly what we saw
        # when MiniMax API stopped responding mid-batch and the
        # uvicorn event loop stalled waiting on a single LLM call.
        # 90s is generous (a single enrichment round-trip is
        # typically 5-20s) but tight enough that a stuck call
        # surfaces within ~2 minutes instead of indefinitely.
        timeout=90,
    )


def extract_document_enrichment(
    llm: BaseChatModel,
    document_name: str,
    description: str,
    tags: List[str],
    graphindex_meta: dict,
    content: str,
) -> Neo4jDocumentEnrichment:
    """Use the LLM to create compact routing metadata for one document.

    Lifted from backend/scripts/test_neo4j_document_kv_roundtrip.py:103-160
    and adapted to use MiniMax M3 via init_chat_model.
    """
    structured_llm = llm.with_structured_output(DocumentEnrichmentOutput)
    content_excerpt = content[:6000]  # keep prompt bounded
    # Cap caller-supplied metadata fields so the enrichment prompt
    # stays bounded regardless of how much was stored on the
    # source node. Without these caps a single 1000-doc project
    # could grow each prompt by 50+ KB from a fat `description` or
    # a `tags` list with hundreds of entries.
    description_capped = (description or "")[:500]
    tags_capped = (tags or [])[:30]
    content_preview_capped = graphindex_meta.get("content_preview", "")[:1000]
    search_terms_capped = (graphindex_meta.get("search_terms") or [])[:20]
    message = (
        "Create compact routing metadata for one document.\n"
        "We use this metadata only to choose the best document before "
        "loading full content.\n\n"
        f"Document name: {document_name}\n"
        f"Description: {description_capped or 'N/A'}\n"
        f"Tags: {tags_capped}\n"
        f"GraphIndex doc_name: {graphindex_meta.get('doc_name', '')}\n"
        f"GraphIndex page_count: {graphindex_meta.get('page_count', 0)}\n"
        f"GraphIndex content_preview: {content_preview_capped}\n"
        f"GraphIndex search_terms: {search_terms_capped}\n\n"
        "Return:\n"
        "1. what_this_document_is_about\n"
        "2. supported_queries\n"
        "3. few_shot\n"
        "4. entities — typed noun entities (name, entity_type, role); max 20\n"
        "5. categories — genre, primary_subject, subjects, question_types, "
        "financial_metrics\n"
        "6. tags — lowercase document-level tags; max 10\n\n"
        "CRITICAL — controlled vocabularies (pick only from these):\n"
        f"{_ontology_prompt_block()}\n\n"
        "Rules:\n"
        "- Keep it concise and routing-oriented\n"
        "- supported_queries are the natural questions this doc can answer\n"
        "- few_shot should be short examples of the kinds of questions "
        "this document can answer\n"
        "- Do not invent unsupported topics\n"
        "- entities: only entities actually mentioned in the document; "
        "use the exact name as written\n"
        "- subjects: 1-5 level-2 topics; financial_metrics only when the "
        "document is finance-related (use IFRS-style concept names)\n"
        "- tags: derive from the top entities and key topics; lowercase, "
        "no standalone dates or numbers\n\n"
        f"Document excerpt:\n{content_excerpt}"
    )
    try:
        result = structured_llm.invoke([
            SystemMessage(content=(
                "You generate document routing metadata for a whole-document "
                "KV system. Be precise, compact, and conservative. "
                "Do NOT include any <think> blocks or commentary in your output — "
                "return only the JSON object matching the schema."
            )),
            HumanMessage(content=message),
        ])
    except Exception as e:
        # MiniMax sometimes wraps its answer in <think>...</think> despite instructions.
        # Fall back to a plain text call and strip the reasoning block.
        print(f"    (structured output failed, retrying plain: {e})")
        resp = llm.invoke([
            SystemMessage(content=(
                "You generate document routing metadata for a whole-document "
                "KV system. Reply with ONLY a JSON object matching this schema:\n"
                '{"what_this_document_is_about": str, '
                '"supported_queries": [str], '
                '"few_shot": [{"query": str, "answer_hint": str}], '
                '"entities": [{"name": str, "entity_type": str, "role": str}], '
                '"categories": {"genre": str, "primary_subject": str, '
                '"subjects": [str], "question_types": [str], '
                '"financial_metrics": [str]}, '
                '"tags": [str]}\n'
                "entities/categories use only the controlled vocabularies: "
                f"entity_type in [{', '.join(ONTOLOGY['entity_type'])}], "
                f"genre in [{', '.join(ONTOLOGY['genre'])}]. "
                "Do NOT include <think> blocks or commentary."
            )),
            HumanMessage(content=message),
        ])
        text = resp.content if isinstance(resp.content, str) else str(resp.content)
        # Strip <think>...</think> block if present
        if "<think>" in text and "</think>" in text:
            text = text.split("</think>", 1)[1].strip()
        # MiniMax sometimes wraps the JSON in a ```json ... ``` fence —
        # extract the fenced body before parsing.
        fence = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
        if fence:
            text = fence.group(1).strip()
        # Fast path: the whole remaining text is already valid JSON.
        try:
            data = json.loads(text)
        except Exception:
            # Fall back to brace matching (the LLM sometimes appends prose
            # after the JSON object). Quotes toggle in_string; backslashes
            # only escape the NEXT char while inside a string — treating a
            # stray backslash in prose as an escape would swallow the
            # following quote and desync the whole scan.
            start = text.find("{")
            if start < 0:
                raise ValueError(f"no JSON object in response: {text[:200]}")
            depth = 0
            in_string = False
            escape = False
            end = -1
            for i in range(start, len(text)):
                c = text[i]
                if in_string:
                    if escape:
                        escape = False
                    elif c == "\\":
                        escape = True
                    elif c == '"':
                        in_string = False
                    continue
                if c == '"':
                    in_string = True
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            if end < 0:
                raise ValueError(f"unbalanced JSON braces in: {text[:200]}")
            text = text[start:end + 1]
            # Sanitize common LLM JSON issues
            text = text.replace("\\n", " ").replace("\\t", " ")
            text = re.sub(r"[\x00-\x1f]+", " ", text)
            data = json.loads(text)
        # Normalize enum values / shapes so one bad field never kills the node.
        result = DocumentEnrichmentOutput(**normalize_enrichment_data(data))
    # Convert the validated output into the enrichment the Neo4j layer stores.
    return Neo4jDocumentEnrichment(
        what_this_document_is_about=result.what_this_document_is_about,
        supported_queries=list(result.supported_queries),
        few_shot=[ex.model_dump() for ex in result.few_shot],
        entities=[e.model_dump() for e in result.entities],
        categories=result.categories.model_dump(),
        llm_tags=list(result.tags),
    )


# --- File → property builder -------------------------------------------------

def build_properties(
    file_path: str,
    name: str,
    enrichment: Neo4jDocumentEnrichment,
    graphindex_meta: Optional[dict] = None,
    description: str = "",
    tags: Optional[List[str]] = None,
    context_doc_id: int = 0,
    project_id: int = _PROJECT_ID,
    hierarchy: dict = None,
) -> Dict[str, Any]:
    """Build a flat Neo4j property map for one document node."""
    return build_document_node_properties(
        project_id=project_id,
        context_doc_id=context_doc_id,
        doc_index_id=(graphindex_meta or {}).get("doc_index_id") or None,
        name=name,
        file_path=file_path,
        description=description,
        tags=tags or [],
        graphindex_meta=graphindex_meta or {},
        enrichment=enrichment,
    )


# --- Commands ----------------------------------------------------------------

def cmd_show(index: Neo4jDocumentIndex, name: str, project_id: int = _PROJECT_ID) -> int:
    """Show one node's full content."""
    node = index.get_document(project_id=project_id, name=name)
    if node is None:
        print(f"  ✗ no Document node with name={name!r}")
        return 1
    print(f"\n{'='*70}\nDocument: {node.name}\n{'='*70}")
    print(f"  context_doc_id  = {node.context_doc_id}")
    print(f"  doc_index_id    = {node.doc_index_id!r}")
    print(f"  file_path       = {node.file_path}")
    print(f"  page_count      = {node.page_count}")
    print(f"  description     = {node.description!r}")
    print(f"  tags            = {node.tags}")
    print(f"  search_terms    = {node.search_terms}")
    print(f"  about ({len(node.what_this_document_is_about)} chars):")
    if node.what_this_document_is_about:
        print(f"    {node.what_this_document_is_about}")
    print(f"  supported_queries ({len(node.supported_queries)}):")
    for q in node.supported_queries:
        print(f"    - {q}")
    print(f"  few_shot ({len(node.few_shot)}):")
    for ex in node.few_shot:
        print(f"    - Q: {ex.get('query')}  A: {ex.get('answer_hint')}")
    print(f"  entities ({len(node.entities)}):")
    for e in node.entities:
        print(f"    - {e.get('name')}  [{e.get('entity_type')} / {e.get('role')}]")
    cats = node.categories or {}
    print(f"  categories:")
    print(f"    genre           = {cats.get('genre')}")
    print(f"    primary_subject = {cats.get('primary_subject')}")
    print(f"    subjects        = {cats.get('subjects')}")
    print(f"    question_types  = {cats.get('question_types')}")
    print(f"    financial_metrics = {cats.get('financial_metrics')}")
    return 0


# --- sha256 helpers + dedup ---------------------------------------------------

def sha256_of_file(file_path: str) -> str:
    """Compute SHA-256 hex digest of a file's bytes."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def scan_neo4j_for_dupe(index: Neo4jDocumentIndex, content_hash: str,
                         project_id: int = _PROJECT_ID) -> List[str]:
    """Find any Document node whose content_sha256 matches. Returns names."""
    rows = index._run_cypher(
        "MATCH (d:Document {project_id: $pid, content_sha256: $h}) "
        "RETURN d.name AS name",
        {"pid": project_id, "h": content_hash},
    )
    return [r["name"] for r in rows]


def cmd_ingest(
    index: Neo4jDocumentIndex,
    llm: BaseChatModel,
    source_path: str,
    target_project_dir: str = None,
   project_id: int = _PROJECT_ID,
    hierarchy: dict = None,
) -> int:
    """Ingest a new file: hash it, dedup against fs + Neo4j, copy if new,
    then run rebuild-one to add the graphindex node."""
    src = Path(source_path).expanduser().resolve()
    if not src.exists():
        # Search project docs folder by filename
        candidates = list(_DOCS_BASE.rglob(src.name))
        if candidates:
            src = candidates[0]
            print(f"  → found: {src}")
        else:
            print(f"  ✗ source not found: {src}")
            return 1
    if src.suffix.lower() not in _SUPPORTED_EXTS:
        print(f"  ✗ unsupported extension: {src.suffix}")
        return 1

    # 1. Hash source
    content_hash = sha256_of_file(str(src))
    print(f"  hash:  {content_hash[:8]}…  ({src.stat().st_size:,} bytes)")

    # 2. Dedup against Neo4j (primary — content hash is source of truth)
    neo_dupes = scan_neo4j_for_dupe(index, content_hash)
    if neo_dupes:
        print(f"  ✗ already indexed (Neo4j): {neo_dupes[0]}")
        return 0

    # 3. Check target folder for same-name collision
    target_dir = (Path(target_project_dir) if target_project_dir
                  else _DOCS_BASE / f"project_{project_id}")
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / src.name
    if target_path.resolve() == src.resolve():
        # Already at the target path — skip copy, just re-index.
        print(f"  → already at target path: {target_path}")
    elif target_path.exists():
        old_hash = sha256_of_file(str(target_path))
        if old_hash == content_hash:
            print(f"  → already on disk: {target_path.name}")
        else:
            # The source has changed since the last ingest (or a
            # previous run wrote a stale copy). Overwrite with the
            # current source bytes — the Neo4j content_hash check
            # above is the real source of truth and it has already
            # passed. Returning 1 here used to abort the entire
            # folder ingest, which is what made a single hash
            # mismatch silently stop ~100 other files from
            # indexing. We log a warning instead.
            print(
                f"  ! file exists with different content: {target_path.name} — "
                f"overwriting (Neo4j hash check passed)"
            )
            shutil.copy2(src, target_path)
    else:
        shutil.copy2(src, target_path)
        print(f"  ✓ copied: {target_path}")

    # 4. Add Neo4j node via rebuild-one (which also sets content_sha256)
    # 5. Insert into PostgreSQL context_documents so the file appears
    #    in the Knowledge panel tree view with the correct folder.
    try:
        db = SessionLocal()
        try:
            existing = db.query(ContextDocument).filter(
                ContextDocument.project_id == project_id,
                ContextDocument.original_filename == src.name,
            ).first()
            if not existing:
                target_filename = target_path.name if target_path.exists() else src.name
                doc_type = (
                    DocumentType.PDF if src.suffix.lower() == ".pdf"
                    else DocumentType.DOCX if src.suffix.lower() in (".docx", ".doc")
                    else DocumentType.JSON if src.suffix.lower() == ".json"
                    else DocumentType.MARKDOWN if src.suffix.lower() in (".md", ".markdown")
                    else DocumentType.TEXT
                )
                doc = ContextDocument(
                    project_id=project_id,
                    filename=target_filename,
                    original_filename=src.name,
                    document_type=doc_type,
                    file_size=src.stat().st_size,
                    file_path=str(target_path),
                    indexing_status=IndexingStatus.READY,
                    industry=(hierarchy or {}).get("industry"),
                    player=(hierarchy or {}).get("player"),
                    sub_category=(hierarchy or {}).get("sub_category"),
                    sub_department=(hierarchy or {}).get("sub_department"),
                )
                db.add(doc)
                db.commit()
                print(f"  ✓ added to PostgreSQL context_documents")
        finally:
            db.close()
    except Exception as e:
        print(f"  ⚠️ PostgreSQL insert skipped: {e}")

    return cmd_rebuild_one(index, llm, src.name, project_id=project_id)


def cmd_ingest_folder(
    index: Neo4jDocumentIndex,
    llm: BaseChatModel,
    folder_path: str,
    project_id: int = _PROJECT_ID,
) -> int:
    """Ingest all supported files in a directory."""
    folder = Path(folder_path).expanduser().resolve()
    if not folder.is_dir():
        print(f"  ✗ folder not found: {folder}")
        return 1
    # Walk the folder for files we know how to index. Two filters
    # are applied:
    #   1. Skip hidden entries (`.placeholder`, `.DS_Store`, etc.) —
    #      any path component that starts with a dot. We don't want
    #      these in the doc corpus even if their extension happens
    #      to be `.md` or similar.
    #   2. Match against `_SUPPORTED_EXTS` (pdf/md/txt/json).
    files = sorted([
        p for p in folder.rglob("*")
        if p.is_file()
        and p.suffix.lower() in _SUPPORTED_EXTS
        and not any(part.startswith(".") for part in p.relative_to(folder).parts)
    ])
    if not files:
        print(f"  ✗ no supported files in {folder}")
        return 1
    print(f"\nIngesting {len(files)} file(s) from {folder}...\n")
    failed = 0
    for f in files:
        print(f"── {f.name} ──")
        parts = str(f.relative_to(folder)).split("/")
        hierarchy = {
            "industry": str(folder.name),
            "player": parts[0] if len(parts) >= 2 else None,
            "sub_category": parts[1] if len(parts) >= 3 else None,
            "sub_department": parts[2] if len(parts) >= 4 else None,
        }
        ok = cmd_ingest(index, llm, str(f), hierarchy=hierarchy, project_id=project_id)
        if ok != 0:
            failed += 1
        print()
    print(f"Done: {len(files) - failed}/{len(files)} ingested")
    return 0 if failed == 0 else 1


def cmd_rebuild_one(
    index: Neo4jDocumentIndex,
    llm: BaseChatModel,
    name: str,
    project_id: int = _PROJECT_ID,
) -> int:
    """Rebuild enrichment for one doc and upsert it.

    If the node doesn't exist yet (e.g. after a delete), we locate the file
    under backend/data/documents/ and create a fresh node.
    """
    node = index.get_document(project_id=project_id, name=name)
    file_path: Optional[str] = None
    context_doc_id = 0
    description = ""
    tags: List[str] = []
    if node is not None:
        file_path = node.file_path
        context_doc_id = node.context_doc_id
        description = node.description or ""
        tags = list(node.tags or [])
        print(f"  → found existing node (context_doc_id={context_doc_id})")
    else:
        # Find the file under any project_*/ folder.
        # Filenames often have a hash prefix (e.g. "31042021_nke-10k-2023.pdf")
        # but the node name is just the suffix. Strip .pdf and search.
        base = name[:-4] if name.lower().endswith(".pdf") else name
        candidates = [p for p in _DOCS_BASE.rglob("*.pdf")
                      if p.stem.endswith(base) or base in p.stem]
        if not candidates:
            # Fall back to exact-name match (for non-PDF files)
            candidates = list(_DOCS_BASE.rglob(name))
        if not candidates:
            print(f"  ✗ no Document node with name={name!r} "
                  f"and no matching file under {_DOCS_BASE}")
            return 1
        file_path = str(candidates[0].resolve())
        print(f"  → node missing; will recreate from file {file_path}")

    content = load_document_content(file_path)
    if not content:
        print(f"  ✗ no content extracted from {file_path}")
        return 1
    graphindex_meta = load_graphindex_metadata(file_path)

    print(f"  → generating enrichment for {name!r} "
          f"({len(content):,} chars)...")
    t0 = time.time()
    enrichment = extract_document_enrichment(
        llm=llm,
        document_name=name,
        description=description,
        tags=tags,
        graphindex_meta=graphindex_meta,
        content=content,
    )
    elapsed = time.time() - t0

    properties = build_properties(
        file_path=file_path,
        name=name,
        enrichment=enrichment,
        graphindex_meta=graphindex_meta,
        description=description,
        tags=tags,
        context_doc_id=context_doc_id,
        project_id=project_id,
    )
    index.upsert_document(project_id=project_id, name=name,
                          file_path=file_path, properties=properties)
    # Keep the entity graph layer (Entity nodes + MENTIONS edges) in sync
    # with the freshly generated enrichment.
    index.sync_entity_graph(project_id, name, enrichment.entities)

    # Also set content_sha256 (not in base properties builder)
    content_hash = sha256_of_file(file_path)
    index._run_cypher(
        "MATCH (d:Document {project_id: $pid, name: $name}) "
        "SET d.content_sha256 = $h",
        {"pid": project_id, "name": name, "h": content_hash},
    )

    print(f"  ✓ upserted in {elapsed:.1f}s")
    print(f"    about: {enrichment.what_this_document_is_about[:120]}")
    print(f"    supports ({len(enrichment.supported_queries)}): "
          f"{enrichment.supported_queries[:3]}")
    print(f"    entities ({len(enrichment.entities)}): "
          f"{[e['name'] for e in enrichment.entities[:5]]}")
    return 0


def cmd_wipe_graph(index: Neo4jDocumentIndex, project_id: int = _PROJECT_ID) -> int:
    """Empty the Neo4j graph for a project (Document + Entity nodes).

    Neo4j only — files on disk and PostgreSQL context_documents are kept,
    so a subsequent --rebuild-one / --ingest can recreate the nodes.
    """
    index.delete_project_documents(project_id)
    print(f"  ✓ wiped graph for project {project_id}: "
          f"Document + Entity nodes removed")
    return 0


def cmd_build_graph(index: Neo4jDocumentIndex, project_id: int = _PROJECT_ID) -> int:
    """Promote each doc's entities_json into (:Entity) nodes + MENTIONS edges.

    Idempotent: purges the project's entity layer and rebuilds it from the
    current Document nodes, so it's safe to re-run after any enrichment
    rebuild or backfill.
    """
    stats = index.build_entity_graph(project_id)
    print(f"  ✓ entity graph rebuilt: {stats['entities']} entities, "
          f"{stats['mentions']} mentions")
    return 0


def cmd_list(
    index: Neo4jDocumentIndex,
    project_id: int = _PROJECT_ID,
) -> int:
    """Scan files on disk and cross-check against Neo4j index."""
    project_folder = _DOCS_BASE / f"project_{project_id}"
    indexed = {d.name for d in index.list_documents(project_id=project_id)}
    print(f"\nFiles on disk — {project_folder}\n")
    files = sorted([
        p for p in project_folder.rglob("*")
        if p.suffix.lower() in _SUPPORTED_EXTS
    ])
    if not files:
        print("  (no supported files found)")
        return 0
    indexed_count = 0
    for i, f in enumerate(files, 1):
        name = f.name
        in_neo4j = any(name.endswith(d) or d.endswith(name)
                       for d in indexed)
        status = "✓" if in_neo4j else "✗ NOT INDEXED"
        if in_neo4j:
            indexed_count += 1
        size = f.stat().st_size
        print(f"  {i}. [{status}] {name}  ({size:,} bytes)")
    print(f"\n  {indexed_count}/{len(files)} indexed")
    return 0


def cmd_remove(
    index: Neo4jDocumentIndex,
    name: str,
    project_id: int = _PROJECT_ID,
) -> int:
    """Remove a doc from Neo4j and delete the file from disk."""
    # Check if it exists in Neo4j
    doc = index.get_document(project_id=project_id, name=name)
    if doc:
        file_path = doc.file_path
        index._run_cypher(
            "MATCH (d:Document {project_id: $pid, name: $name}) DELETE d",
            {"pid": project_id, "name": name},
        )
        print(f"  ✓ removed from Neo4j: {name}")
    else:
        print(f"  ✗ not found in Neo4j (project {project_id}): {name}")
        file_path = None

    # Also delete from PostgreSQL context_documents
    try:
        db = SessionLocal()
        try:
            deleted = db.query(ContextDocument).filter(
                ContextDocument.project_id == project_id,
                ContextDocument.original_filename == name,
            ).delete()
            db.commit()
            if deleted:
                print(f"  ✓ deleted from PostgreSQL: {name}")
        finally:
            db.close()
    except Exception as e:
        print(f"  ⚠️ PostgreSQL delete skipped: {e}")

    # Try to find and delete the file on disk
    project_folder = _DOCS_BASE / f"project_{project_id}"
    candidates = list(project_folder.rglob(name))
    if not candidates:
        # Try matching by suffix (e.g. name="a34de781_01..." → file="2c406458_a34de781_01...")
        candidates = [p for p in project_folder.rglob(name.split("_", 1)[-1])
                      if p.stem.endswith(name)]
    if not candidates and file_path:
        candidates = [Path(file_path)]
    if candidates:
        for p in candidates:
            p.unlink()
            print(f"  ✓ removed from disk: {p.name}")
    else:
        print(f"  (no matching file found on disk)")
    return 0


def cmd_purge(
    index: Neo4jDocumentIndex,
    project_id: int = _PROJECT_ID,
) -> int:
    """Remove ALL documents in a project from Neo4j and disk."""
    docs = index.list_documents(project_id=project_id)
    if not docs:
        print(f"  No documents in project {project_id}")
        return 0
    print(f"  Purging {len(docs)} document(s) from project {project_id}...")
    for d in docs:
        index._run_cypher(
            "MATCH (d:Document {project_id: $pid, name: $name}) DETACH DELETE d",
            {"pid": project_id, "name": d.name},
        )
        fp = Path(d.file_path) if d.file_path else None
        if fp and fp.exists():
            fp.unlink()
    # Also delete from PostgreSQL context_documents
    try:
        db = SessionLocal()
        try:
            deleted = db.query(ContextDocument).filter(
                ContextDocument.project_id == project_id
            ).delete()
            db.commit()
            print(f"  ✓ deleted {deleted} record(s) from PostgreSQL")
        finally:
            db.close()
    except Exception as e:
        print(f"  ⚠️ PostgreSQL delete skipped: {e}")

    print(f"  Done — {len(docs)} document(s) purged")
    return 0


def cmd_remove_folder(
    index: Neo4jDocumentIndex,
    folder: str,
    project_id: int = _PROJECT_ID,
) -> int:
    """Remove ALL documents in a folder (by file_path prefix) from Neo4j and disk."""
    docs = index.list_documents(project_id=project_id)
    matching = [d for d in docs if folder.replace("/", "") in d.file_path.replace("\\", "/")]
    if not matching:
        print(f"  ✗ no documents matching folder '{folder}' in project {project_id}")
        return 1

    print(f"  Found {len(matching)} document(s) matching folder '{folder}'")
    for d in matching:
        index._run_cypher(
            "MATCH (d:Document {project_id: $pid, name: $name}) DETACH DELETE d",
            {"pid": project_id, "name": d.name},
        )
        print(f"  ✓ removed from Neo4j: {d.name}")
        # Try to delete file from disk
        fp = Path(d.file_path) if d.file_path else None
        if fp and fp.exists():
            fp.unlink()
            print(f"  ✓ removed from disk: {fp.name}")
        # Also delete from PostgreSQL
        try:
            db = SessionLocal()
            try:
                q = db.query(ContextDocument).filter(
                    ContextDocument.project_id == project_id,
                    ContextDocument.original_filename == d.name,
                )
                cnt = q.delete()
                db.commit()
                if cnt:
                    print(f"  ✓ deleted from PostgreSQL: {d.name}")
            finally:
                db.close()
        except Exception as e:
            print(f"  ⚠️ PostgreSQL delete skipped: {e}")
            print(f"  ✓ removed from disk: {fp.name}")
    print(f"  Done — {len(matching)} document(s) removed")
    return 0


def cmd_rebuild_project(
    index: Neo4jDocumentIndex,
    llm: BaseChatModel,
    project_id: int = _PROJECT_ID,
) -> int:
    """Rebuild enrichment for every Document node in the project."""
    docs = index.list_documents(project_id=project_id)
    print(f"\n{'='*70}\nRebuilding enrichment for {len(docs)} doc(s) "
          f"(project {project_id})\n{'='*70}\n")
    failed = 0
    for d in docs:
        ok = cmd_rebuild_one(index, llm, d.name, project_id=project_id)
        if ok != 0:
            failed += 1
        print()
    print(f"{'='*70}\n{len(docs) - failed}/{len(docs)} rebuilt successfully\n{'='*70}")
    return 0 if failed == 0 else 1


def cmd_build_embeddings(index: Neo4jDocumentIndex,
                         project_id: int = _PROJECT_ID) -> int:
    """Embed every Document node's routing blob into the Neo4j vector index."""
    matcher = Neo4jEmbeddingMatcher(index)
    matcher.ensure_index()
    stats = matcher.build_embeddings(project_id)
    print(f"\n  ✓ embedded {stats['embedded']} doc(s) into vector index "
          f"'doc_embedding' (dim={stats['dim']}, cosine)")
    return 0


def cmd_build_entity_embeddings(index: Neo4jDocumentIndex,
                                project_id: int = _PROJECT_ID) -> int:
    """Embed every Entity node's routing blob into the entity vector index."""
    matcher = Neo4jEmbeddingMatcher(index)
    matcher.ensure_entity_index()
    stats = matcher.build_entity_embeddings(project_id)
    print(f"\n  ✓ embedded {stats['embedded']} entity node(s) into vector index "
          f"'entity_embedding' (dim={stats['dim']}, cosine)")
    return 0


# --- Entry point -------------------------------------------------------------

def cmd_show_agent() -> int:
    """Print agent topology for the build-side DeepAgent (if available)."""
    try:
        from learning.phase9.build_agent import get_build_agent
        agent = get_build_agent()
        print("Build-side DeepAgent topology:")
        for node in agent.get_graph().nodes:
            print("  -", node)
    except ImportError:
        print("Build agent not available (build_agent module not found)")
    except Exception as e:
        print("  (could not introspect: {})".format(e))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 9 — complete GraphIndex builder.",
    )
    parser.add_argument("--project-id", type=int, default=_PROJECT_ID,
                        help=f"Neo4j project id (default: {_PROJECT_ID}, "
                             "from GRAPHINDEX_DEFAULT_PROJECT_ID env var)")
    parser.add_argument("--purge", action="store_true",
                        help="Remove ALL documents in the project from Neo4j and disk")
    parser.add_argument("--wipe-graph", action="store_true",
                        help="Empty the Neo4j graph for the project (Document + Entity nodes)")
    parser.add_argument("--build-embeddings", action="store_true",
                        help="Embed each Document node's routing blob into the Neo4j vector index")
    parser.add_argument("--build-entity-embeddings", action="store_true",
                        help="Embed each Entity node's blob into the Neo4j vector index")
    parser.add_argument("--list", action="store_true",
                        help="List files on disk, cross-checked against Neo4j")
    parser.add_argument("--show", metavar="NAME", help="Show a document node")
    parser.add_argument("--remove-folder", metavar="FOLDER",
                        help="Remove ALL docs in a folder (by file_path match)")
    parser.add_argument("--remove", metavar="NAME",
                        help="Remove a doc from Neo4j and delete file from disk")
    parser.add_argument("--rebuild-one", metavar="NAME",
                        help="Rebuild enrichment for one doc")
    parser.add_argument("--rebuild-project", action="store_true",
                        help="Rebuild enrichment for every doc in the project")
    parser.add_argument("--build-graph", action="store_true",
                        help="Rebuild the entity graph layer (Entity nodes + MENTIONS edges)")
    parser.add_argument("--ingest", metavar="FILE",
                        help="Ingest a single file: hash, dedup, copy, build graphindex")
    parser.add_argument("--ingest-folder", metavar="DIR",
                        help="Ingest all supported files in a directory")
    parser.add_argument("--show-agent", action="store_true", help="Print agent topology")
    parser.add_argument("--ingest-target", metavar="DIR", default=None,
                        help="Target directory for the ingested file "
                             "(default: backend/data/documents/project_{ID})")
    args = parser.parse_args()
    project_id = args.project_id

    if not any([args.list, args.show, args.remove, args.remove_folder, args.show_agent,
                args.purge, args.wipe_graph,
                args.rebuild_one, args.rebuild_project,
                args.ingest, args.ingest_folder,
                args.build_graph, args.build_embeddings,
                args.build_entity_embeddings]):
        parser.print_help()
        return 1

    # Connect to Neo4j
    _neo4j_url = os.getenv("NEO4J_URL", "http://localhost:7474")
    print(f"🔌 Neo4j: {_neo4j_url}")
    index = Neo4jDocumentIndex(
        base_url=_neo4j_url,
        username=os.getenv("NEO4J_USER", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD", "password"),
    )
    index.ensure_constraints()
    print(f"   constraints ensured")

    # Build LLM (lazy — only when we need enrichment)
    llm: Optional[BaseChatModel] = None
    if args.rebuild_one or args.rebuild_project or args.ingest or args.ingest_folder:
        llm = make_llm()
        print(f"🔌 LLM: {os.getenv('GRAPHINDEX_MODEL', 'minimax-m3')}\n")

    if args.list:
        return cmd_list(index, project_id=project_id)
    if args.show:
        return cmd_show(index, args.show, project_id=project_id)
    if args.purge:
        return cmd_purge(index, project_id=project_id)
    if args.wipe_graph:
        return cmd_wipe_graph(index, project_id=project_id)
    if args.remove_folder:
        return cmd_remove_folder(index, args.remove_folder, project_id=project_id)
    if args.remove:
        return cmd_remove(index, args.remove, project_id=project_id)
    if args.rebuild_one:
        return cmd_rebuild_one(index, llm, args.rebuild_one,
                               project_id=project_id)
    if args.rebuild_project:
        return cmd_rebuild_project(index, llm, project_id=project_id)
    if args.build_graph:
        return cmd_build_graph(index, project_id=project_id)
    if args.build_embeddings:
        return cmd_build_embeddings(index, project_id=project_id)
    if args.build_entity_embeddings:
        return cmd_build_entity_embeddings(index, project_id=project_id)
    if args.ingest:
        return cmd_ingest(index, llm, args.ingest, args.ingest_target,
                          project_id=project_id)
    if args.show_agent:
        return cmd_show_agent()
    if args.ingest_folder:
        return cmd_ingest_folder(index, llm, args.ingest_folder,
                                 project_id=project_id)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

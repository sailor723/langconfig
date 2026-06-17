#!/usr/bin/env python3
"""Test script for GraphIndex search and KV-style full-document answering."""
from typing import Dict, Optional, List, Tuple

# Mock data setup
mock_documents: List[Dict] = [
    {
        "id": 1,
        "filename": "Nike 10K 2023.pdf",
        "description": "Nike's 2023 annual financial report",
        "tags": ["finance", "nike", "annual report"],
        "content_preview": "Nike 2023 annual report covering revenue, income, products, and leadership.",
        "content": "Nike Inc. 2023 Annual Report\nRevenue: $51.2 billion\nNet Income: $6.1 billion\nKey products: Air Jordan, Air Max, Nike Pro\nCEO: John Donahoe"
    },
    {
        "id": 2,
        "filename": "人物库.pdf",
        "description": "Chinese figures database for philosophers and entrepreneurs",
        "tags": ["chinese", "philosophy", "entrepreneurs"],
        "content_preview": "人物库，包含哲学家与企业家的核心思想和人物信息。",
        "content": "哲学家人物库\n企业家人物库\n姓名：孔子，核心思想：仁、礼\n姓名：乔布斯，核心思想：极简主义、专注用户体验\n姓名：稻盛和夫，核心思想：敬天爱人"
    }
]


def build_query_terms(query: str) -> List[str]:
    """Build vector-free query terms for both English and Chinese queries."""
    normalized = query.strip().lower()
    if not normalized:
        return []

    terms: List[str] = [normalized]
    whitespace_tokens = [token for token in normalized.split() if token]
    terms.extend(whitespace_tokens)

    # Chinese queries often have no spaces, so keep the full query and add bigrams.
    if " " not in normalized and len(normalized) > 1:
        for i in range(len(normalized) - 1):
            terms.append(normalized[i:i + 2])

    return list(dict.fromkeys(terms))


def keyword_match_score(query: str, doc: Dict) -> float:
    """Calculate a metadata-first score for a document."""
    score = 0.0
    normalized_query = query.strip().lower()
    query_terms = build_query_terms(query)

    # Check filename
    for token in query_terms:
        if len(token) < 2:
            continue
        if len(normalized_query) > 8 and len(token) < 4:
            continue
        if token in doc["filename"].lower():
            score += 3.0

    # Check description
    for token in query_terms:
        if len(token) < 2:
            continue
        if len(normalized_query) > 8 and len(token) < 4:
            continue
        if token in doc["description"].lower():
            score += 2.0

    # Check preview
    for token in query_terms:
        if len(token) < 2:
            continue
        if len(normalized_query) > 8 and len(token) < 4:
            continue
        if token in doc["content_preview"].lower():
            score += 2.0

    # Check tags
    for tag in doc["tags"]:
        for token in query_terms:
            if len(token) < 2:
                continue
            if len(normalized_query) > 8 and len(token) < 4:
                continue
            if token in tag.lower():
                score += 2.5

    # Check content
    for token in query_terms:
        if len(token) < 2:
            continue
        if len(normalized_query) > 8 and len(token) < 4:
            continue
        if token in doc["content"].lower():
            score += 1.0

    return score


def find_best_doc(query: str) -> Optional[Dict]:
    """Find the most relevant document using only keyword matching"""
    scored_docs: List[Tuple[float, Dict]] = []
    for doc in mock_documents:
        score = keyword_match_score(query, doc)
        if score > 0:
            scored_docs.append((score, doc))

    if not scored_docs:
        return None

    # Sort by score descending
    scored_docs.sort(key=lambda x: x[0], reverse=True)
    return scored_docs[0][1]


def answer_query_with_kv(query: str, doc: Dict) -> str:
    """Mock KV-style answer generation using whole-document context."""
    full_context = doc["content"]
    lowered_query = query.lower()

    if "revenue" in lowered_query and "revenue:" in full_context.lower():
        for line in full_context.splitlines():
            if line.lower().startswith("revenue:"):
                return f"[doc={doc['filename']}] {line}"

    if "乔布斯" in query:
        for line in full_context.splitlines():
            if "乔布斯" in line:
                return f"[doc={doc['filename']}] {line}"

    if "孔子" in query:
        for line in full_context.splitlines():
            if "孔子" in line:
                return f"[doc={doc['filename']}] {line}"

    return f"[doc={doc['filename']}] Whole document loaded, but no focused answer rule matched."


def main():
    """Run test cases for doc finding and full-document answering."""
    test_queries: List[Tuple[str, bool]] = [
        ("Nike revenue", True),
        ("乔布斯", True),
        ("孔子仁", True),
        ("financial report", True),
        ("xydsfsdfsdfdsfds", False),  # Truly unique, won't match anything
    ]

    print("=" * 60)
    print("Testing GraphIndex Search + KV Full-Document Answering")
    print("=" * 60)
    print()

    for query, should_match in test_queries:
        print(f"Query: {query}")
        best_doc = find_best_doc(query)

        if should_match:
            assert best_doc is not None, f"Expected a match for: {query}"
            answer = answer_query_with_kv(query, best_doc)
            print(f"✅ Found best doc: {best_doc['filename']}")
            print(f"   Description: {best_doc['description']}")
            print(f"   KV Answer: {answer}")
            print("-" * 40)
        else:
            assert best_doc is None, f"Did not expect a match for: {query}"
            print("❌ No matching documents found")
            print("-" * 40)

    print("\n✅ All GraphIndex KV test cases completed!")


if __name__ == "__main__":
    main()

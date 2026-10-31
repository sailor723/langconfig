# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Step 2 of the semantic-search tutorial: embeddings.

The tutorial's five steps are `Document → Embeddings → splitter → VectorStore →
retriever`. Each is verified here in isolation, because a retrieval failure is
otherwise indistinguishable between them: wrong chunks, wrong vectors and wrong
distance metric all look like "the answer is bad".

These tests talk to a **local Ollama** (`nomic-embed-text`, 768 dims). They skip —
not fail — when nothing is listening, so the suite stays runnable on a machine
that has never pulled the model; a missing optional dependency must not turn a
green build red. When Ollama *is* up, the assertions are real embeddings computed
against the running server, not mocks.

What is pinned:

* the configured model is the one that answers, and its dimension is 768 —
  pgvector columns are dimension-typed, so a silent model swap would make every
  stored vector unreadable;
* identical text embeds to the same vector, different text does not;
* related text scores higher than unrelated text (the property retrieval depends
  on — if this is false, no amount of prompt work fixes the answers);
* `embed_documents` returns one vector per input, in order.
"""

import math
import os

import pytest

from core.rag import embedding_model_name, get_embeddings, ollama_base_url

#: Set to skip the live tests deliberately (e.g. a CI box with no Ollama).
SKIP_LIVE = os.getenv("SKIP_OLLAMA_TESTS") == "1"


def _cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


@pytest.fixture(scope="module")
def embeddings():
    """The live `Embeddings` object, or skip if Ollama is not answering."""
    if SKIP_LIVE:
        pytest.skip("SKIP_OLLAMA_TESTS=1")
    emb = get_embeddings()
    try:
        emb.embed_query("ping")
    except Exception as exc:  # noqa: BLE001 — any transport failure means "no server"
        pytest.skip(f"Ollama not available at {ollama_base_url()}: {exc}")
    return emb


def test_the_configured_model_is_nomic_embed_text():
    """Whatever else changes, the course's embeddings are reproducible and local.

    The tag is part of the Ollama model id and the API accepts it with or without
    one, so compare the base name: `.env` here carries
    `OLLAMA_EMBED_MODEL=nomic-embed-text:latest`, and hard-coding the untagged form
    in the assertion would fail on a correct configuration.
    """
    assert embedding_model_name().split(":")[0] == "nomic-embed-text"


def test_base_url_strips_the_openai_v1_suffix():
    """`local_base_url` is the OpenAI-compatible base used for chat
    (`http://host:11434/v1`). The native Ollama API — what `langchain_ollama`
    speaks — lives at the host root, so the suffix must not leak through."""
    from core.rag.embeddings import ollama_base_url as base

    assert not base().endswith("/v1")


def test_one_query_embeds_to_768_dimensions(embeddings):
    vec = embeddings.embed_query("Dogs are great companions.")
    assert isinstance(vec, list) and vec
    assert len(vec) == 768, f"nomic-embed-text is 768-dim, got {len(vec)}"
    assert all(isinstance(x, float) for x in vec)


def test_identical_text_embeds_identically(embeddings):
    """Determinism is what makes a stored vector comparable to a new query."""
    text = "Cats are independent pets."
    assert _cosine(embeddings.embed_query(text), embeddings.embed_query(text)) == pytest.approx(
        1.0, abs=1e-6
    )


def test_related_text_scores_higher_than_unrelated_text(embeddings):
    """The property the whole feature rests on.

    Same topic vs different topic — not a subtle semantic win. If this fails, the
    lesson cannot be taught and the answer is "fix retrieval", not "write a better
    prompt", which is exactly the distinction the course is making.
    """
    query = embeddings.embed_query("What do dogs eat?")
    related = embeddings.embed_query("Dogs are great companions, known for their loyalty.")
    unrelated = embeddings.embed_query("The 2023 annual report lists eight distribution centers.")

    assert _cosine(query, related) > _cosine(query, unrelated)


def test_embed_documents_returns_one_vector_per_input_in_order(embeddings):
    texts = ["first document", "second document", "third document"]
    vectors = embeddings.embed_documents(texts)

    assert len(vectors) == len(texts)
    assert all(len(v) == 768 for v in vectors)
    # Order matters: a store that pairs the wrong vector with a chunk retrieves
    # the right text under the wrong name and citations become fiction.
    for text, vec in zip(texts, vectors):
        assert _cosine(vec, embeddings.embed_query(text)) == pytest.approx(1.0, abs=1e-6)

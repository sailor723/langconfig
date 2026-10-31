# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Embeddings for retrieval — step 2 of the semantic-search tutorial.

The tutorial (https://docs.langchain.com/oss/python/langchain/knowledge-base)
presents retrieval as five steps, each a LangChain core object:

    1. Document(page_content, metadata, id)
    2. embeddings = <provider>Embeddings(...)          ← this module
    3. RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200,
                                      add_start_index=True)
    4. vector_store.add_documents(splits)
    5. vector_store.similarity_search(q, k) / .as_retriever(...)

This module owns step 2 and nothing else: one place that answers "what turns text
into a vector here", so the splitter, the store and the retriever never disagree.

Why Ollama + ``nomic-embed-text``:

* **No new credential, no new bill.** The install already runs Ollama for local
  chat models, and DeepSeek's API — the one provider this instance holds a key
  for — does not expose an embeddings endpoint at all. A retrieval feature that
  needed a second vendor account would sit unused like Tavily did.
* **It fits the machine.** 274 MB, 768 dimensions, already pulled.
* **Deterministic and local**: a course that teaches "same query → same vector"
  cannot use a remote model whose version changes under it.

The one thing this choice costs: 768 dimensions and a local process, so retrieval
quality is below a large hosted embedding model. For a course about *evidence and
citations* that is the right trade — the lesson is that a score and a page number
beat a fluent summary, not that the embedding is state of the art.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

#: The Ollama embedding model this install uses. Overridable for experiments
#: (`OLLAMA_EMBED_MODEL`) without touching code, because trying a second model is
#: the normal way to answer "is retrieval bad or is the model bad?".
DEFAULT_EMBEDDING_MODEL = "nomic-embed-text"

#: Dimension of `nomic-embed-text`; asserted against a live call in the tests so a
#: model swap cannot silently make existing vectors unreadable (pgvector columns
#: are dimension-typed, and a mismatch fails at insert time, not at query time).
DEFAULT_EMBEDDING_DIM = 768


def embedding_model_name() -> str:
    return (os.getenv("OLLAMA_EMBED_MODEL") or DEFAULT_EMBEDDING_MODEL).strip()


def ollama_base_url() -> str:
    """Where the Ollama server is.

    Reads the same setting the local chat models use (`models.local_base_url`),
    minus the OpenAI-compatible `/v1` suffix those models need: the native Ollama
    API — which is what `langchain_ollama` speaks — lives at the host root.

    Settings first, then `OLLAMA_BASE_URL`, then localhost, so a machine that has
    only ever configured Ollama for chat needs no second configuration here.
    """
    base: Optional[str] = None
    try:
        from core.settings import runtime_get

        base = runtime_get("models", "local_base_url")
    except Exception:  # noqa: BLE001 — settings unreadable must not break retrieval
        base = None
    if not base:
        base = os.getenv("OLLAMA_BASE_URL") or "http://localhost:11434"
    base = str(base).strip().rstrip("/")
    if base.endswith("/v1"):  # OpenAI-compatible base from the chat path
        base = base[: -len("/v1")]
    return base


def get_embeddings(model: Optional[str] = None, base_url: Optional[str] = None):
    """The one `Embeddings` object retrieval uses.

    Returns a LangChain `Embeddings` implementation — the tutorial's step 2 — so
    the splitter, store and retriever can be swapped without anything here
    changing. Callers must treat it as `langchain_core.embeddings.Embeddings`:
    `embed_query(str)` and `embed_documents(list[str])`.
    """
    from langchain_ollama import OllamaEmbeddings

    return OllamaEmbeddings(
        model=model or embedding_model_name(),
        base_url=base_url or ollama_base_url(),
    )

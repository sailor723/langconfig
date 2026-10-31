# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Retrieval built exactly as the LangChain semantic-search tutorial presents it.

Deliberately separate from `api/knowledge/*` (llama_index, whole-folder inline
context) so the two approaches can be compared side by side instead of one
quietly becoming the other. See `docs/reference/agent-practice.md`, case 1.

Steps map one-to-one onto modules, in tutorial order:

    documents.py  1. Document(page_content, metadata)
    embeddings.py 2. Embeddings(...)
    split.py      3. RecursiveCharacterTextSplitter(...)
    store.py      4. VectorStore.add_documents(splits)
    retriever.py  5. VectorStore.similarity_search / as_retriever
"""

from .documents import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    get_splitter,
    load_file,
    load_pdf_pages,
    load_text_file,
    split_documents,
)
from .embeddings import get_embeddings, embedding_model_name, ollama_base_url
from .index import (
    DEFAULT_K,
    get_retriever,
    has_index,
    index_documents,
    index_file,
    search,
    search_with_scores,
)
from .store import collection_exists, collection_name, connection_string, drop_collection, get_vector_store

__all__ = [
    # 1
    "load_file", "load_pdf_pages", "load_text_file",
    # 2
    "get_embeddings", "embedding_model_name", "ollama_base_url",
    # 3
    "get_splitter", "split_documents", "CHUNK_SIZE", "CHUNK_OVERLAP",
    # 4
    "get_vector_store", "collection_name", "connection_string",
    "drop_collection", "collection_exists",
    # pipeline
    "index_file", "index_documents", "get_retriever", "search",
    "search_with_scores", "has_index", "DEFAULT_K",
]

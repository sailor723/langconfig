# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Documents and splitting — steps 1 and 3 of the semantic-search tutorial.

Step 1: `Document(page_content, metadata, id)`.
Step 3: `RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200,
        add_start_index=True)`.

Both live here because they are the same decision seen twice: **what is one unit of
retrieval**. A chunk too small loses the sentence before the number; a chunk too
large drags irrelevant text into the prompt and dilutes the score. The tutorial's
1000/200 is a sane default for prose; `add_start_index=True` is the important flag,
because without it a retrieved chunk cannot be pointed back to *where* in the source
it came from — and a citation you cannot open is not a citation.

`metadata` carries the provenance the answer needs: `source` (file name), `page`
(PDF page, 1-based for humans), and whatever the caller adds.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, List, Optional

logger = logging.getLogger(__name__)

#: The tutorial's defaults, kept as named constants so a lesson can change them and
#: watch retrieval change — that comparison is more instructive than the numbers.
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200


def load_pdf_pages(file_path: str | Path, source_label: Optional[str] = None) -> List["object"]:
    """One `Document` per PDF page, as the tutorial's `load_pdf_pages` does.

    Pages rather than one document, because a page number is the cheapest useful
    citation ("p. 4") and because a page is still too coarse for retrieval — the
    splitter's job, not this one's.

    `page` is 1-based: PDF indexing is 0-based, but every citation a person reads
    is 1-based. Converting once, here, beats remembering which side does what.
    """
    import pypdf
    from langchain_core.documents import Document

    path = Path(file_path)
    reader = pypdf.PdfReader(str(path))
    label = source_label or path.name
    docs = []
    for i, page in enumerate(reader.pages):
        docs.append(
            Document(
                page_content=page.extract_text() or "",
                metadata={"source": label, "page": i + 1},
            )
        )
    return docs


def load_text_file(file_path: str | Path, source_label: Optional[str] = None) -> List["object"]:
    """A text-like file as one `Document` (markdown, txt, csv, log).

    The splitter does the chunking, so a whole file in one Document is fine here —
    unlike the KV chat, nothing is being put into a prompt at this stage.
    """
    from langchain_core.documents import Document

    path = Path(file_path)
    return [
        Document(
            page_content=path.read_text(encoding="utf-8", errors="replace"),
            metadata={"source": source_label or path.name},
        )
    ]


def load_file(file_path: str | Path, source_label: Optional[str] = None) -> List["object"]:
    """Dispatch on suffix; PDF or text. Unknown binary formats are not guessed at."""
    suffix = Path(file_path).suffix.lower()
    if suffix == ".pdf":
        return load_pdf_pages(file_path, source_label)
    if suffix in {".txt", ".md", ".markdown", ".csv", ".log", ".html", ".htm"}:
        return load_text_file(file_path, source_label)
    raise ValueError(
        f"unsupported file type {suffix!r} for retrieval — add a loader rather than "
        "reading it as text, or the chunks will be binary noise"
    )


def get_splitter(chunk_size: int = CHUNK_SIZE, chunk_overlap: int = CHUNK_OVERLAP):
    """The tutorial's splitter, as one function so every caller splits identically.

    `add_start_index=True` is not optional here: it records each chunk's character
    offset in the source, which is what makes "show me where that came from"
    answerable after retrieval.
    """
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        add_start_index=True,
    )


def split_documents(docs: Iterable, **kwargs) -> List:
    """`splitter.split_documents(docs)` — step 3, with the defaults in one place."""
    return get_splitter(**kwargs).split_documents(list(docs))

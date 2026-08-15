# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Multi-format tool descriptions for the SDK filesystem middleware.

The deepagents SDK's ``write_file`` / ``read_file`` tool schemas describe only
plain-text behaviour ("Writes content to a file"), but LangConfig's
``FormatAwareBackend`` makes them multi-format: ``write_file`` renders
``.docx`` / ``.pdf`` / ``.html`` from markdown content, and ``read_file``
extracts text from ``.pdf`` / ``.docx`` / ``.pptx``. The model only trusts what
the tool schema says, so we override the SDK's descriptions via
``FilesystemMiddleware(custom_tool_descriptions=...)`` (its official hook) to
expose the real capability.
"""

# write_file — multi-format document generation (replaces the SDK's plain-text
# "Writes content to a file" description).
WRITE_FILE_MULTI_FORMAT_DESCRIPTION = """Write content to a file, creating or replacing it.

MULTI-FORMAT: the file extension picks the output format automatically:
- .md    Markdown document (stored as-is)
- .html  Styled, self-contained HTML page (rendered from the content)
- .pdf   PDF document (headings + paragraphs rendered from the content)
- .docx  Word document (headings + paragraphs rendered from the content)
- .txt / .json / .csv / .py  plain text (stored as-is)

Use markdown headings (# / ## / ###) in `content` so pdf/html/docx outputs get
proper document structure. Example:
    write_file(file_path="report.docx", content="# Title\\n\\nBody text...")

Prefer this tool for generating any deliverable file — do NOT use python,
bash, or document libraries to produce .docx/.pdf/.html files."""

# read_file — multi-format text extraction (replaces the SDK's plain-text
# read description).
READ_FILE_MULTI_FORMAT_DESCRIPTION = """Read a file's content.

MULTI-FORMAT: text is extracted automatically for binary document formats:
- .pdf    PDF text extraction
- .docx   Word document text extraction
- .pptx   PowerPoint slide text extraction
- .md / .txt / .json / .csv / .py   read as plain text

Use `offset` / `limit` to page through large files (line-based)."""


def filesystem_tool_descriptions() -> dict:
    """Return the multi-format descriptions map for
    ``FilesystemMiddleware(custom_tool_descriptions=...)``."""
    return {
        "write_file": WRITE_FILE_MULTI_FORMAT_DESCRIPTION,
        "read_file": READ_FILE_MULTI_FORMAT_DESCRIPTION,
    }

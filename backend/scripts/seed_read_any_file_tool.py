"""Seed the `read_any_file` BUILTIN tool row (is_builtin = true).

Why a builtin and not a UI tool: UI-created python_function tools are
UNTRUSTED (`core/tools/factory/builders.py:1808`) — they get an AST check and a
restricted namespace with no `open`, no `subprocess` and imports limited to a
stdlib allowlist. A reader needs filesystem + tesseract + the reader graph, so
it must be trusted code. Builtins run with the full namespace, and a row here
surfaces in `GET /api/tools/registry` — i.e. as a toggle in the agent editor.

Idempotent: re-running updates the row in place.

    cd backend && .venv/bin/python scripts/seed_read_any_file_tool.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import SessionLocal  # noqa: E402
from sqlalchemy import text  # noqa: E402

TOOL_ID = "read_any_file"

CODE = '''# --- imports ---
import sys as _sys
from pathlib import Path as _Path


def _ensure_app_importable() -> None:
    """Make backend/ importable even when the exec namespace lacks cwd context."""
    try:
        backend = str(_Path(__file__).resolve().parent.parent)
    except NameError:  # no __file__ in this namespace
        return
    if backend not in _sys.path:
        _sys.path.insert(0, backend)


async def read_any_file(file_path: str, question: str = None) -> str:
    """Read any file and return TEXT - never raw or base64 bytes.

    text/code/data  -> verbatim, line-numbered
    .pdf/.docx/.pptx -> extracted text
    images          -> vision description + OCR text
    """
    _ensure_app_importable()
    from core.graphs.read_file import read_file_as_text

    return await read_file_as_text(file_path, question=question)
'''

DESCRIPTION = (
    "Read any file and return its TEXT. Text, code and data files come back verbatim "
    "(line-numbered); .pdf/.docx/.pptx are converted to text; images "
    "(.png/.jpg/.jpeg/.webp/.gif/.bmp/.tiff) come back as a short vision description plus "
    "OCR-extracted text. Use this for images instead of read_file - it never returns raw or "
    "base64 image data, so it cannot overflow the context. Pass `question` to ask something "
    "specific about an image."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "file_path": {
            "type": "string",
            "description": "Path to the file to read (text, document, or image).",
        },
        "question": {
            "type": "string",
            "description": "Optional question about an image (ignored for text files).",
            # The factory marks a field required unless its entry carries a
            # `default` (core/tools/factory/builders.py:1873-1876) — without
            # this, callers must pass `question` explicitly.
            "default": "",
        },
    },
    "required": ["file_path"],
}

DEFINITION = {
    "category": "filesystem",
    "order": 6,
    "section": None,
    "is_concurrency_safe": True,
    "output_schema": None,
    "guard": {"approval": False, "confirmation": False},
    "presentation": {},
}

# The builder prefers implementation_config.args_schema verbatim; the
# JSON-Schema -> {arg: {type, description}} translation it applies to the
# top-level input_schema DROPS any `default` key (core/tools/factory/
# builders.py:1766-1772), which would make `question` a required argument.
# Declaring it here keeps `question` optional for the model.
ARGS_SCHEMA = {
    "file_path": {
        "type": "string",
        "description": "Path to the file to read (text, document, or image).",
    },
    "question": {
        "type": "string",
        "description": "Optional question about an image (ignored for text files).",
        "default": "",
    },
}

INSERT_SQL = text(
    """
    INSERT INTO custom_tools
        (tool_id, name, description, tool_type, template_type, category, is_builtin,
         is_public, output_format, definition, input_schema, implementation_config,
         requires_api_key, tags, version, usage_count, error_count,
         is_template_based, is_advanced_mode, created_at, updated_at)
    VALUES
        (:tool_id, :name, :description, 'python_function', 'custom', 'filesystem', true,
         false, 'string', CAST(:definition AS json), CAST(:input_schema AS json),
         CAST(:impl AS json), false, CAST(:tags AS json), '1.0.0', 0, 0,
         true, true, now(), now())
    ON CONFLICT (tool_id) DO UPDATE SET
        name = EXCLUDED.name,
        description = EXCLUDED.description,
        definition = EXCLUDED.definition,
        input_schema = EXCLUDED.input_schema,
        implementation_config = EXCLUDED.implementation_config,
        category = EXCLUDED.category,
        is_builtin = true,
        updated_at = now()
    """
)


def main() -> int:
    db = SessionLocal()
    try:
        db.execute(INSERT_SQL, {
            "tool_id": TOOL_ID,
            "name": "Read Any File (text + images)",
            "description": DESCRIPTION,
            "definition": json.dumps(DEFINITION),
            "input_schema": json.dumps(INPUT_SCHEMA),
            "impl": json.dumps({
                "function_name": "read_any_file",
                "code": CODE,
                "args_schema": ARGS_SCHEMA,
            }),
            "tags": json.dumps(["filesystem", "image", "ocr", "vision"]),
        })
        db.commit()

        row = db.execute(text(
            "SELECT tool_id, name, category, is_builtin, is_public, "
            "length(implementation_config->>'code') AS code_len "
            "FROM custom_tools WHERE tool_id = :t"
        ), {"t": TOOL_ID}).fetchone()
        print("row:", row)
        print("filesystem builtins now:", db.execute(text(
            "SELECT count(*) FROM custom_tools WHERE is_builtin AND category = 'filesystem'"
        )).scalar())
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

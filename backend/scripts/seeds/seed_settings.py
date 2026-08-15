"""
Seed settings documents for a fresh LangConfig install (idempotent).

Writes the default namespace documents (models/general/workspace/storage/rag/
search/onboarding) into the ``settings_documents`` table — only for namespaces
that have no document row yet; existing rows are never touched. This is step
[4/10] of ``seed_all.py`` and also runs automatically on backend boot (no-op
when documents exist).

Run from backend/:
    uv run python scripts/seeds/seed_settings.py

Safety: only creates/inserts into ``settings_documents``. The legacy single-row
``settings`` table and every other table are untouched.
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from core.settings.seed import ensure_settings_seeded  # noqa: E402


def main() -> int:
    written = ensure_settings_seeded()
    print(f"settings seed: {written} document(s) written (existing rows kept)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

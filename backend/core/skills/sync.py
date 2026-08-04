#!/usr/bin/env python3
"""
Skills sync layer — keeps DB and Filesystem in sync.

DB is the runtime source of truth.
Filesystem is the git-tracked materialized view (SKILL.md files).

Bidirectional sync rules:
  - On startup: scan FS → upsert DB if mtime changed
  - On PUT (edit): write DB → write FS (so git picks it up)
  - On POST (create): insert DB → write FS
  - On DELETE: delete DB → remove FS

This matches the Phase 5 GraphIndex pattern (DB primary, FS for git tracking).
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)


# Default skill roots (LangChain deepagents layout).
# Values come from the root .env (BUILTIN_SKILLS_ROOT / PERSONAL_SKILLS_ROOT).
# Relative values are resolved against the project root so they work no matter
# what the process CWD is; fallbacks keep the repo layout as-is.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]  # backend/core/skills/ -> repo root


def _resolve_skill_root(env_name: str, default_rel: str) -> Path:
    """Resolve a skill root from env, or fall back to the repo-relative default."""
    raw = os.environ.get(env_name)
    if raw:
        p = Path(raw).expanduser()
        return p if p.is_absolute() else (_PROJECT_ROOT / p).resolve()
    return (_PROJECT_ROOT / default_rel).resolve()


DEFAULT_BUILTIN_SKILLS_ROOT = _resolve_skill_root("BUILTIN_SKILLS_ROOT", "backend/skills/builtin")
# Personal/user-created skills live alongside builtin, in a sibling directory.
# The library's FilesystemBackend reads SKILL.md from these real FS paths.
PERSONAL_SKILLS_ROOT = _resolve_skill_root("PERSONAL_SKILLS_ROOT", "backend/skills/personal")


def parse_skill_md(text: str) -> Tuple[Dict[str, Any], str]:
    """Parse YAML frontmatter + body from a SKILL.md file."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    yaml_str = text[3:end].strip()
    body = text[end + 4:].strip()
    try:
        frontmatter = yaml.safe_load(yaml_str) or {}
    except yaml.YAMLError as e:
        logger.warning(f"Failed to parse SKILL.md YAML: {e}")
        frontmatter = {}
    return frontmatter, body


def serialize_skill_md(frontmatter: Dict[str, Any], body: str) -> str:
    """Build a SKILL.md file from frontmatter dict + body string.

    Uses yaml.safe_dump for proper YAML output (not concatenated lines that
    break parsing). The `...` document-end marker should NOT appear in the
    middle of a single document.
    """
    # Order important fields first for readability
    ordered_keys = ["name", "description", "version", "author", "tags",
                    "triggers", "allowed_tools", "required_context", "examples"]
    seen = set()
    ordered_fm: Dict[str, Any] = {}
    for key in ordered_keys:
        if key in frontmatter:
            ordered_fm[key] = frontmatter[key]
            seen.add(key)
    for key, value in frontmatter.items():
        if key not in seen:
            ordered_fm[key] = value

    yaml_str = yaml.safe_dump(ordered_fm, default_flow_style=False, sort_keys=False).rstrip()

    parts = ["---", yaml_str, "---", ""]
    if body:
        parts.append(body)
        if not body.endswith("\n"):
            parts.append("")
    return "\n".join(parts)


def skill_row_to_markdown(skill_row) -> str:
    """
    Render a DB skill row as the canonical SKILL.md text (frontmatter + body).

    Shared by ``db_row_to_fs`` (FS mirror) and the Phase 3 DbBackend wiring
    (DB-only skills), so both write byte-identical content.
    """
    fm = {
        "name": skill_row.name,
        "description": skill_row.description,
    }
    if skill_row.version:
        fm["version"] = skill_row.version
    if skill_row.author:
        fm["author"] = skill_row.author
    if skill_row.tags:
        fm["tags"] = list(skill_row.tags)
    if skill_row.triggers:
        fm["triggers"] = list(skill_row.triggers)
    if skill_row.allowed_tools:
        fm["allowed_tools"] = list(skill_row.allowed_tools)
    if getattr(skill_row, "required_context", None):
        fm["required_context"] = list(skill_row.required_context)
    if getattr(skill_row, "examples", None):
        fm["examples"] = skill_row.examples

    body = skill_row.instructions or ""

    # Wrap body in ## Instructions section (required by loader's _parse_body_sections).
    # Examples section is appended separately if present.
    if skill_row.examples:
        body = (
            f"## Instructions\n\n{body}\n\n"
            f"## Examples\n\n{skill_row.examples}"
        )
    else:
        body = f"## Instructions\n\n{body}"

    return serialize_skill_md(fm, body)


def normalize_source_type(source_type: Any) -> str:
    """Normalize a skill row's source_type to its canonical key segment.

    Handles str-mixin enums (``SkillSourceType.PERSONAL`` -> ``"personal"``),
    plain strings, and legacy dot paths (``"learning.phase5"`` -> ``"phase5"``);
    missing/empty defaults to ``"builtin"``. Shared by ``skill_storage_key``
    and ``db_row_to_fs`` so storage keys and FS dirs always agree.
    """
    if source_type is None or source_type == "":
        return "builtin"
    if not isinstance(source_type, str):
        # str-mixin enum members are str subclasses whose f-string repr is
        # "SkillSourceType.PERSONAL"; the actual value lives in `.value`.
        source_type = getattr(source_type, "value", str(source_type))
    if "." in source_type:
        source_type = source_type.split(".")[-1]
    return source_type.lower()


def skill_storage_key(skill_row) -> str:
    """
    Canonical storage key for a skill: ``skills/<source_type>/<skill_id>/SKILL.md``.

    Normalizes ``source_type`` via ``normalize_source_type`` so DB rows and
    FS mirrors agree on the key.
    """
    source_type = normalize_source_type(getattr(skill_row, "source_type", "builtin"))
    return f"skills/{source_type}/{skill_row.skill_id}/SKILL.md"


def db_row_to_fs(skill_row, skills_root: Optional[Path] = None) -> Path:
    """
    Write a DB skill row to its SKILL.md on the filesystem.

    Returns the path to the SKILL.md file.

    The skill directory is determined by:
      1. skill_row.source_path if set (existing location)
      2. Otherwise: skills_root / <source_type> / <skill_id>
    """
    root = skills_root or DEFAULT_BUILTIN_SKILLS_ROOT

    # Determine target directory
    source_type = normalize_source_type(getattr(skill_row, "source_type", "builtin"))

    if hasattr(skill_row, "source_path") and skill_row.source_path:
        skill_dir = Path(skill_row.source_path)
    else:
        skill_dir = root / source_type / skill_row.skill_id

    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md = skill_dir / "SKILL.md"

    content = skill_row_to_markdown(skill_row)
    skill_md.write_text(content, encoding="utf-8")
    logger.info(f"Wrote SKILL.md → {skill_md}")

    # Phase 2 write-through (docs/system-architecture.md §15): when
    # STORAGE_MODE=db, also persist the SKILL.md body to the storage
    # backend so it survives independently of the git mirror. The FS
    # mirror stays the operational view until Phase 3 DbBackend lands;
    # local mode (default) is a no-op and behavior is unchanged.
    try:
        from config import settings
        if settings.storage_mode == "db":
            from services.storage import get_storage
            get_storage().save(
                skill_storage_key(skill_row),
                content.encode("utf-8"),
                "text/markdown",
            )
    except Exception as e:
        logger.warning(f"Failed to persist SKILL.md to storage: {e}")

    return skill_md


def fs_to_db_dict(skill_md: Path) -> Dict[str, Any]:
    """
    Parse a SKILL.md file and return a dict ready for DB upsert.
    """
    text = skill_md.read_text(encoding="utf-8")
    fm, body = parse_skill_md(text)

    skill_id = skill_md.parent.name
    # Use timezone-aware UTC datetime to match DB columns (TIMESTAMP WITH TIME ZONE)
    from datetime import timezone
    mtime = datetime.fromtimestamp(skill_md.stat().st_mtime, tz=timezone.utc)

    return {
        "skill_id": skill_id,
        "name": fm.get("name", skill_id),
        "description": fm.get("description", ""),
        "version": fm.get("version", "1.0.0"),
        "author": fm.get("author"),
        "tags": fm.get("tags") or [],
        "triggers": fm.get("triggers") or [],
        "allowed_tools": fm.get("allowed_tools") or [],
        "required_context": fm.get("required_context") or [],
        "examples": fm.get("examples"),
        "instructions": body,
        "source_path": str(skill_md.parent),
        "file_modified_at": mtime,
    }


def scan_builtin_skills(root: Optional[Path] = None) -> List[Path]:
    """
    Find all SKILL.md files under builtin/ and personal/.

    Returns list of SKILL.md paths.
    """
    root = root or DEFAULT_BUILTIN_SKILLS_ROOT
    if not root.exists():
        logger.warning(f"Skills root does not exist: {root}")
        return []

    return sorted(root.rglob("SKILL.md"))


def derive_source_type(skill_md: Path, builtin_root: Optional[Path] = None) -> str:
    """
    Determine if a SKILL.md belongs to builtin or personal based on its path.

    /backend/skills/builtin/{id}/SKILL.md     → "builtin"
    /backend/skills/personal/{user}/{id}/SKILL.md → "personal"
    """
    root = builtin_root or DEFAULT_BUILTIN_SKILLS_ROOT
    try:
        rel = skill_md.relative_to(root)
    except ValueError:
        return "personal"  # outside root → treat as personal

    parts = rel.parts
    if len(parts) >= 2 and parts[0] == "builtin":
        return "builtin"
    elif len(parts) >= 2 and parts[0] == "personal":
        return "personal"
    return "builtin"  # default to builtin if unclear
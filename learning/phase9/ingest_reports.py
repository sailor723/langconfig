#!/usr/bin/env python3
"""
ingest_reports.py — Bulk-ingest the reports_new/ corpus into a project
workspace, preserving the on-disk folder hierarchy as Postgres metadata.

Hierarchy mapping:
    reports_new/<industry>/<player>/<sub_category>[/<sub_department>]/<file>
    → industry       = <industry>
      player         = <player>       (None for industry-only docs)
      sub_category   = <sub_category> (None for player-level docs)
      sub_department = <sub_department> (None unless 4-level path)

Examples:
    reports_new/electric_vehicle_industry/tesla/Tesla_Comprehensive.md
      → industry="electric_vehicle_industry"
        player="tesla"
        sub_category=NULL  (it's at the player root)
        sub_department=NULL

    reports_new/electric_vehicle_industry/tesla/marketing/01-product-lineup.md
      → industry="electric_vehicle_industry"
        player="tesla"
        sub_category="marketing"
        sub_department=NULL

    reports_new/electric_vehicle_industry/tesla/strategic_consensus/finance/gap_analysis.json
      → industry="electric_vehicle_industry"
        player="tesla"
        sub_category="strategic_consensus"
        sub_department="finance"

By default this script targets project_id=2 ("my deep agent project").
Override with --project-id.

Idempotent: existing files (by content_hash) are skipped.
"""

import argparse
import hashlib
import json
import logging
import shutil
import sys
from pathlib import Path
from typing import Optional

# Resolve repo root so this script runs from anywhere
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("ingest_reports")

# Default source: the user's deep-agent reports corpus
DEFAULT_SOURCE = Path("/Users/weiping/dev/Learn/langchain-ai/my-deep-agent/reports_new")
# Default target: project 2 ("my deep agent project")
DEFAULT_PROJECT_ID = 2

# File types we know how to index (from upload pipeline's doc_type_map).
# JSON / MD / TXT / PDF are the bulk of reports_new/.
SUPPORTED_EXTS = {
    ".md", ".markdown", ".txt",
    ".pdf",
    ".json",
    ".csv", ".tsv",
    ".py", ".js", ".ts", ".tsx", ".jsx",
    ".html", ".htm",
    ".docx", ".doc",
    ".pptx", ".ppt",
    ".xlsx", ".xls",
    ".png", ".jpg", ".jpeg", ".gif", ".webp",
}

# Placeholder files used to force Git to track empty directories.
# reports_new/ uses ".placeholder" for that — never ingest these.
SKIP_NAMES = {".placeholder", ".DS_Store", ".gitkeep"}


def parse_path_to_metadata(rel_path: Path) -> dict:
    """Map a relative path under reports_new/ to hierarchy fields.

    Expects the structure reports_new/<industry>/<player>/<sub_cat>[/<sub_dept>]/<file>.
    Returns dict with optional industry/player/sub_category/sub_department.
    """
    parts = rel_path.parts
    meta = {
        "industry":       None,
        "player":         None,
        "sub_category":   None,
        "sub_department": None,
    }
    # parts[0] is the industry (since rel_path is relative to args.source
    # which IS reports_new/, so parts[0] = first folder under reports_new/).
    if len(parts) >= 2:
        meta["industry"] = parts[0]
    if len(parts) >= 3:
        meta["player"] = parts[1]
    if len(parts) >= 4:
        meta["sub_category"] = parts[2]
    if len(parts) >= 5:
        # 4th-level folder = department under strategic_consensus/, etc.
        meta["sub_department"] = parts[3]
    return meta


def ingest_file(
    src_path: Path,
    rel_path: Path,
    project_id: int,
    docs_root: Path,
    db,
    ContextDocument,
    IndexingStatus,
    DocumentType,
) -> tuple[str, Optional[int]]:
    """Copy a single file into the project workspace and create a
    ContextDocument row. Returns ("created", doc_id) or ("skipped", doc_id)
    or ("failed", None)."""
    try:
        # 1. Read source content + hash for dedup
        content = src_path.read_bytes()
        content_hash = hashlib.sha256(content).hexdigest()

        # 1b. Parse hierarchy metadata first — used both for the dedup
        #     back-fill below AND for the new row creation.
        meta = parse_path_to_metadata(rel_path)

        # 2. Check for existing duplicate by content_hash + project_id
        existing = (
            db.query(ContextDocument)
            .filter(
                ContextDocument.project_id == project_id,
                ContextDocument.content_hash == content_hash,
                ContextDocument.indexing_status != IndexingStatus.FAILED,
            )
            .first()
        )
        if existing:
            # Step N+1: back-fill hierarchy metadata on existing rows
            # that were uploaded before folder-hierarchy was wired
            # through (e.g. via the bulk upload endpoint before the
            # per-file metadata fix). Without this back-fill, those
            # docs would all land in the synthetic "(ungrouped)" root
            # in the sidebar's Tree view even though we have the
            # original folder path from reports_new/.
            # Only update fields that are NULL — never clobber
            # metadata that the user has already curated.
            updated_fields = []
            if not existing.industry and meta["industry"]:
                existing.industry = meta["industry"]
                updated_fields.append("industry")
            if not existing.player and meta["player"]:
                existing.player = meta["player"]
                updated_fields.append("player")
            if not existing.sub_category and meta["sub_category"]:
                existing.sub_category = meta["sub_category"]
                updated_fields.append("sub_category")
            if not existing.sub_department and meta["sub_department"]:
                existing.sub_department = meta["sub_department"]
                updated_fields.append("sub_department")
            if updated_fields:
                # Tags too — but keep any pre-existing tags.
                existing.tags = list(existing.tags or []) + [
                    meta["industry"], meta["player"], meta["sub_category"]
                ]
                db.commit()
                logger.info(
                    f"  UPDATED id={existing.id:>4}  "
                    f"({'+'.join(updated_fields)})  "
                    f"{rel_path}"
                )
                return ("updated", existing.id)
            logger.info(f"  SKIP (duplicate hash) {rel_path} → existing id={existing.id}")
            return ("skipped", existing.id)

        # 3. Build destination path. Mirror the source folder hierarchy
        #    under the project workspace so on-disk layout matches the
        #    metadata (industry/player/sub_category).
        dst_dir = docs_root / str(project_id) / rel_path.parent
        dst_dir.mkdir(parents=True, exist_ok=True)
        # Add a short hash prefix to avoid filename collisions between
        # different folder paths that share a basename (e.g. two
        # gap_analysis.json files in strategic_consensus/<dept>/).
        dst_filename = f"{content_hash[:8]}_{src_path.name}"
        dst_path = dst_dir / dst_filename

        if not dst_path.exists():
            shutil.copy2(src_path, dst_path)

        # 4. Determine document type from extension (mirrors upload pipeline)
        ext = src_path.suffix.lower().lstrip(".")
        doc_type_map = {
            "md": DocumentType.MARKDOWN, "markdown": DocumentType.MARKDOWN,
            "txt": DocumentType.TEXT,
            "pdf": DocumentType.PDF,
            "json": DocumentType.JSON,
            "py": DocumentType.CODE, "js": DocumentType.CODE,
            "ts": DocumentType.CODE, "tsx": DocumentType.CODE, "jsx": DocumentType.CODE,
            "html": DocumentType.HTML, "htm": DocumentType.HTML,
            "csv": DocumentType.CSV, "tsv": DocumentType.CSV,
            "docx": DocumentType.TEXT, "doc": DocumentType.TEXT,
            "pptx": DocumentType.TEXT, "ppt": DocumentType.TEXT,
            "xlsx": DocumentType.CSV, "xls": DocumentType.CSV,
            "png": DocumentType.IMAGE, "jpg": DocumentType.IMAGE, "jpeg": DocumentType.IMAGE,
            "gif": DocumentType.IMAGE, "webp": DocumentType.IMAGE,
        }
        document_type = doc_type_map.get(ext, DocumentType.TEXT)

        # 5. Parse hierarchy metadata (already computed in step 1b)

        # 6. Create ContextDocument row
        doc = ContextDocument(
            project_id=project_id,
            filename=src_path.name,           # display name (basename)
            original_filename=src_path.name,
            file_path=str(dst_path),
            file_size=len(content),
            mime_type=None,                    # let frontend guess by extension
            document_type=document_type,
            indexing_status=IndexingStatus.NOT_INDEXED,
            content_hash=content_hash,
            tags=[meta["industry"], meta["player"], meta["sub_category"]],
            industry=meta["industry"],
            player=meta["player"],
            sub_category=meta["sub_category"],
            sub_department=meta["sub_department"],
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        logger.info(
            f"  CREATED id={doc.id:>4}  "
            f"{meta['industry']}/{meta['player'] or '-'}/"
            f"{meta['sub_category'] or '-'}/{meta['sub_department'] or '-'}  "
            f"{src_path.name}"
        )
        return ("created", doc.id)
    except Exception as e:
        logger.error(f"  FAILED  {rel_path}: {e}")
        db.rollback()
        return ("failed", None)


def main():
    parser = argparse.ArgumentParser(
        description="Bulk-ingest reports_new/ into a project workspace, "
                    "preserving folder hierarchy as metadata.",
    )
    parser.add_argument(
        "--source", type=Path, default=DEFAULT_SOURCE,
        help=f"Source directory containing reports_new/ (default: {DEFAULT_SOURCE})",
    )
    parser.add_argument(
        "--project-id", type=int, default=DEFAULT_PROJECT_ID,
        help=f"Project ID to ingest into (default: {DEFAULT_PROJECT_ID})",
    )
    parser.add_argument(
        "--industry", type=str, default=None,
        help="Optional: only ingest files under this industry (e.g. 'electric_vehicle_industry')",
    )
    parser.add_argument(
        "--player", type=str, default=None,
        help="Optional: only ingest files under this player (e.g. 'tesla')",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Walk the source tree and print what would be ingested, "
             "but don't copy or create rows",
    )
    args = parser.parse_args()

    # Late-import DB models (needs sys.path tweak above)
    from db.database import SessionLocal, engine, init_db  # noqa
    from models.core import ContextDocument, IndexingStatus, DocumentType  # noqa
    from services.file_storage import file_storage  # noqa

    # Run the idempotent column migrations before we touch the table.
    init_db()

    if not args.source.is_dir():
        logger.error(f"Source directory not found: {args.source}")
        sys.exit(1)

    docs_root = Path(file_storage._base_dir)
    logger.info(f"Source:  {args.source}")
    logger.info(f"Target:  project_id={args.project_id}  workspace={docs_root}")
    logger.info(f"Filters: industry={args.industry or '*'}  player={args.player or '*'}")
    if args.dry_run:
        logger.info("DRY RUN — no files will be copied, no rows will be created")

    # Walk
    counts = {"created": 0, "skipped": 0, "updated": 0, "failed": 0, "would_create": 0}
    file_count = 0
    for src_path in sorted(args.source.rglob("*")):
        if not src_path.is_file():
            continue
        if src_path.name in SKIP_NAMES:
            continue
        if src_path.suffix.lower() not in SUPPORTED_EXTS:
            continue
        rel_path = src_path.relative_to(args.source)

        # Apply filters
        if args.industry and (len(rel_path.parts) < 2 or rel_path.parts[0] != args.industry):
            continue
        if args.player and (len(rel_path.parts) < 3 or rel_path.parts[1] != args.player):
            continue

        file_count += 1
        if args.dry_run:
            counts["would_create"] += 1
            logger.info(f"  WOULD INGEST  {rel_path}")
            continue

        with SessionLocal() as db:
            status, doc_id = ingest_file(
                src_path=src_path,
                rel_path=rel_path,
                project_id=args.project_id,
                docs_root=docs_root,
                db=db,
                ContextDocument=ContextDocument,
                IndexingStatus=IndexingStatus,
                DocumentType=DocumentType,
            )
            counts[status] += 1

    logger.info("")
    logger.info(f"=== Done ===")
    logger.info(f"  Files seen:           {file_count}")
    if args.dry_run:
        logger.info(f"  Would ingest:         {counts['would_create']}")
    else:
        logger.info(f"  Created:              {counts['created']}")
        logger.info(f"  Updated (metadata):   {counts['updated']}")
        logger.info(f"  Skipped (duplicate):  {counts['skipped']}")
        logger.info(f"  Failed:               {counts['failed']}")


if __name__ == "__main__":
    main()

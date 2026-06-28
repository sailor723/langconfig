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
import time
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


def find_existing_doc(db, ContextDocument, project_id: int, src_path: Path):
    """Step O.6: locate the existing ContextDocument row for a
    duplicate file. Used by the --re-enrich-existing flag to look
    up the row that was skipped (because its content_hash already
    exists in the DB) so we can re-run the enrichment pipeline on
    it.

    Match strategy: first try content_hash (most reliable — same
    file = same hash even if renamed); fall back to filename in
    the same project. Returns the first match or None.
    """
    import hashlib
    h = hashlib.sha256(src_path.read_bytes()).hexdigest()
    row = db.query(ContextDocument).filter(
        ContextDocument.project_id == project_id,
        ContextDocument.content_hash == h,
    ).first()
    if row is not None:
        return row
    row = db.query(ContextDocument).filter(
        ContextDocument.project_id == project_id,
        ContextDocument.filename == src_path.name,
    ).first()
    return row


def run_full_enrichment(
    doc_id: int,
    file_path: str,
    project_id: int,
) -> None:
    """Step O.6: run the full enrichment pipeline for a freshly inserted doc.

    This mirrors what the API endpoint's `index_document_background`
    function does as a background task. Calling the same function
    means the CLI gets the EXACT same behavior as the UI — same
    DocIndex output, same chunking, same LLM enrichment, same Neo4j
    sync. The only difference is timing: the CLI runs it
    synchronously (waits for completion) instead of as a fire-and-
    forget background task.

    Pipeline (per doc):
      1. DocIndex.index(file_path) → builds L1 _meta.json, L2 .json,
         and L3 page content for the GraphIndex/PageIndex routing
      2. context_document_indexer.index_document(doc_id, file_path)
         → chunking + embedding into the project's vector table
      3. _try_sync_context_document_to_neo4j(doc, client) → upserts
         the :Document node + generates LLM enrichment (about /
         supported_queries / out_of_scope / few_shot)

    Args:
        doc_id:      ID of the freshly inserted ContextDocument row
        file_path:   Absolute path to the file (used by DocIndex)
        project_id:  Project ID (used by Neo4j sync)
    """
    from services.context_document_indexer import context_document_indexer

    logger.info(f"  ENRICH  doc_id={doc_id}  {file_path}")
    enrich_start = time.time()

    # 1+2. Run the same function the API endpoint calls. It does
    # DocIndex + vector indexing + status update + Neo4j sync +
    # LLM enrichment all in one call. By reusing the live API
    # code, we guarantee the CLI behavior matches the UI behavior.
    try:
        import asyncio
        from api.knowledge.rag import index_document_background
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        if loop.is_running():
            # We're inside an existing event loop (e.g. under a test
            # runner) — fall back to creating a new one in a thread.
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(lambda: asyncio.run(index_document_background(doc_id))).result()
        else:
            loop.run_until_complete(index_document_background(doc_id))
        elapsed = time.time() - enrich_start
        logger.info(f"    ENRICHED  doc_id={doc_id}  ({elapsed:.1f}s)")
    except Exception as e:
        elapsed = time.time() - enrich_start
        logger.error(f"    ENRICH FAILED  doc_id={doc_id}  ({elapsed:.1f}s): {e}")


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
    parser.add_argument(
        "--enrich", action="store_true",
        help="After insert, run the FULL pipeline: DocIndex (L1/L2/L3) + "
             "vector embedding (chunking) + LLM enrichment (about/queries) "
             "+ Neo4j :Document sync. Same as the UI's full upload flow. "
             "Slow (10-30s per file) — use --skip-enrich for fast ingest.",
    )
    parser.add_argument(
        "--skip-enrich", action="store_true",
        help="Insert rows but skip the full pipeline (default behavior — "
             "docs are inserted as NOT_INDEXED, will be enriched on first "
             "open in the UI or by a separate job).",
    )
    parser.add_argument(
        "--enrich-concurrency", type=int, default=1,
        help="Number of docs to enrich in parallel (default: 1, sequential). "
             "Higher = faster but uses more API quota / risk rate limits.",
    )
    parser.add_argument(
        "--re-enrich-existing", action="store_true",
        help="In addition to newly-ingested docs, also re-enrich rows that "
             "were SKIPPED because the file already exists (i.e. the doc "
             "was inserted previously but may not have been fully indexed). "
             "Use this to bring existing docs up to the current state of "
             "the indexing pipeline (e.g. after a code change, or to "
             "back-fill docs that were inserted without --enrich).",
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

    # Step O.7: Resolve the docs_root to an ABSOLUTE path anchored at
    # the backend directory. The backend runs from `backend/` and uses
    # `data/documents/` relative to its CWD; the CLI might be invoked
    # from the project root or from `learning/phase9/`, so we anchor
    # on the backend's absolute path to avoid the CWD mismatch that
    # caused "File not found on disk" in the viewer (the CLI wrote to
    # `<project>/data/documents/8/...` but the backend looked in
    # `<project>/backend/data/documents/project_8/...`).
    backend_dir = Path(__file__).resolve().parent.parent.parent / "backend"
    backend_data_dir = backend_dir / "data" / "documents"
    if backend_data_dir.exists():
        docs_root = backend_data_dir
    else:
        # Fall back to the CWD-relative base_dir (the old behavior)
        docs_root = Path(file_storage._base_dir)
    logger.info(f"Source:  {args.source}")
    logger.info(f"Target:  project_id={args.project_id}  workspace={docs_root}")
    logger.info(f"Filters: industry={args.industry or '*'}  player={args.player or '*'}")
    if args.dry_run:
        logger.info("DRY RUN — no files will be copied, no rows will be created")
    if args.enrich:
        logger.info("Enrichment: ON (will run DocIndex + vector embedding + LLM enrichment + Neo4j sync per doc)")
    else:
        logger.info("Enrichment: OFF (docs will be inserted as NOT_INDEXED; enrich via UI or re-run with --enrich)")

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

        # If the row was just created, optionally run the full enrichment
        # pipeline (DocIndex + vector embedding + LLM enrichment +
        # Neo4j sync). This is the same flow the API endpoint triggers
        # as a background task. For 5 small files, it takes ~10-30s each.
        if status == "created" and args.enrich and doc_id is not None:
            run_full_enrichment(
                doc_id=doc_id,
                file_path=str(src_path),
                project_id=args.project_id,
            )

        # If the row was SKIPPED (duplicate by content_hash) and
        # --re-enrich-existing is set, look up the existing row and
        # enrich it. Useful for back-filling docs that were inserted
        # before --enrich was added, or for re-running after a code
        # change in the indexing pipeline.
        if status == "skipped" and args.re_enrich_existing and args.enrich:
            with SessionLocal() as db2:
                existing = find_existing_doc(
                    db=db2,
                    ContextDocument=ContextDocument,
                    project_id=args.project_id,
                    src_path=src_path,
                )
            if existing is not None:
                run_full_enrichment(
                    doc_id=existing.id,
                    file_path=str(existing.file_path or src_path),
                    project_id=args.project_id,
                )

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
        if args.re_enrich_existing and counts["skipped"] > 0:
            logger.info(f"  Re-enriched existing: {counts['skipped']}")


if __name__ == "__main__":
    main()

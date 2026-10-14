"""Audit which of this install's data lives in the database and which is files on disk.

Written for moving a machine from the zip install to a git checkout: it answers
"what do I actually have to carry across?" — because most of it is in Postgres and
comes with the database, not with a folder.

    cd <tree>/backend
    .venv/bin/python scripts/audit_local_data.py

Read-only: it runs SELECTs and stats file trees, and writes nothing.

Why this is not just "copy outputs/": the Knowledge panel in the left sidebar reads
its document list from disk in the default ``storage.mode = local`` — from
``<documents_base_dir>/.kvmeta`` — so moving trees without those files leaves the
panel empty while Postgres still holds the rows and the embeddings. In ``db`` mode
the opposite is true: the panel lists from ``storage_objects`` and the files are in
Postgres, so there is nothing to copy.
"""
import os
import sys
from pathlib import Path

# Run from anywhere: take backend/ from this file's own location and work from there. The
# app resolves settings paths against the process CWD ("./data/documents"), so the CWD must be
# backend/ no matter where the script was invoked from — running it from the repo root used to
# fail with "can't open file .../scripts/<name>.py".
BACKEND = Path(__file__).resolve().parents[1]
os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))

from sqlalchemy import text  # noqa: E402

from db.database import engine  # noqa: E402

BACKEND = Path.cwd()
TREE = BACKEND.parent


def human(path: Path) -> str:
    if not path.exists():
        return "MISSING"
    files = [f for f in path.rglob("*") if f.is_file()]
    total = sum(f.stat().st_size for f in files)
    return f"{len(files)} file(s), {total / 1048576:.1f} MB"


def resolve(value: str, default: str) -> Path:
    """Resolve a settings path the way its consumer does.

    The two settings do not share a base: ``storage.documents_base_dir`` is
    ``./data/documents`` and resolves against the process CWD (``backend/``, where
    the app runs from), while ``workspace.base_dir`` is ``backend/outputs`` and
    resolves against the repository root. Getting this wrong reports MISSING for a
    directory that plainly exists.
    """
    value = value or default
    p = Path(value)
    if p.is_absolute():
        return p
    if value.startswith("backend/") or value.startswith("backend\\"):
        return (TREE / value).resolve()
    return (BACKEND / value).resolve()


with engine.connect() as conn:
    def settings_doc(namespace: str) -> dict:
        row = conn.execute(
            text("SELECT document FROM settings_documents WHERE ns = :n"),
            {"n": namespace},
        ).scalar()
        return row or {}

    storage = settings_doc("storage")
    workspace = settings_doc("workspace")
    counts = {}
    for table in (
        "chat_sessions", "context_documents", "session_documents",
        "data_context_documents_embeddings", "storage_objects",
        "workspace_files", "file_versions", "skills", "deep_agent_templates",
        "custom_tools",
    ):
        try:
            counts[table] = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar()
        except Exception:  # table absent on an older schema
            counts[table] = "n/a"

mode = storage.get("mode") or "local"
print(f"tree      : {TREE}")
print(f"database  : {engine.url.render_as_string(hide_password=True)}")
print(f"storage   : mode={mode!r}  documents_base_dir={storage.get('documents_base_dir')!r}")
print(f"workspace : {workspace.get('workspace_path')!r}")
print("in the database (nothing to copy while the machine keeps this database):")
for table, n in counts.items():
    print(f"    {table:34} {n}")

print("\non disk (per tree — git never carries any of it):")
# The knowledge base root is resolved the way the application resolves it: from the environment,
# never from the settings document. The document's value is shown above only so a divergence is
# visible — it is reported, not obeyed.
from services.kb_discovery import kb_root  # noqa: E402

knowledge = Path(kb_root()).resolve()
document_says = storage.get("documents_base_dir")
kvmeta = knowledge / ".kvmeta"
outputs = resolve(workspace.get("base_dir", ""), "backend/outputs")
agents_md = resolve(os.getenv("LANGCONFIG_WORKSPACE_ROOT", ""), "backend/.workspace_data")
skills = BACKEND / "skills" / "personal"

print(f"    knowledge files + .kvmeta  {knowledge}\n        -> {human(knowledge)}"
      f"   (.kvmeta: {human(kvmeta)})")
print(f"    agent workspaces/outputs   {outputs}\n        -> {human(outputs)}")
print(f"    project AGENTS.md root     {agents_md}\n        -> {human(agents_md)}")
print(f"    skills of their own        {skills}\n        -> {human(skills)}")

print("\nwhat that means:")
print("    The knowledge base is FILESYSTEM-ONLY: the documents and the .kvmeta catalog under")
print(f"    {knowledge}")
print("    are the whole of it, and the Knowledge panel lists from that catalog. Copy the")
print("    directory and the knowledge base has moved; a project folder found there is")
print("    registered automatically when the panel asks for the project list.")
print("    storage.mode no longer affects it, and neither does any settings document:")
if document_says and str(knowledge) != str(resolve(document_says, "./data/documents")):
    print(f"      ! the storage document says documents_base_dir={document_says!r}, which is now")
    print("        IGNORED. Nothing reads the registry to find the knowledge base.")
print("    Embeddings stay in Postgres, so search returns after a re-index, not from a copy.")
print("    The workspace directory is referenced by ABSOLUTE path in the database")
print(f"    ({workspace.get('workspace_path')!r}); either keep the tree at that path or")
print("    update Settings -> Workspace, or agents keep writing to the old folder.")
print("    Neo4j, if this install indexes into it (NEO4J_URI), is a third store and")
print("    docker-compose ships no service for it: that knowledge is neither in")
print("    Postgres nor in either tree.")

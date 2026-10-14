"""Reproduce the "copied knowledge base" case, then prove the fix — as a regression test.

    cd <tree>/backend
    .venv/bin/python scripts/verify_copied_knowledge_base.py

The case that stalled a team migration: a legacy `data/documents` folder is copied into a fresh
install, every file and every `.kvmeta` record arrives intact, and the Knowledge panel shows
nothing — because it lists projects from `GET /api/projects/` and there is no row for those ids.

This script builds that situation from scratch, asserts that it is genuinely broken, applies the
fix, and asserts it is genuinely fixed. If the reproduction ever stops reproducing, the script
fails loudly rather than passing vacuously — a test that cannot fail is worse than no test.

Everything it needs it creates itself: a scratch database (`langconfig_kbtest`), a scratch
documents tree under /tmp, and a fake copied folder. It overrides POSTGRES_DB before importing
anything from the app, so it cannot touch the configured database.

Four phases:

  1. REPRODUCE   documents on disk + .kvmeta, no projects row  -> unreachable through the API
  2. THE TRAP    a row of only id and name breaks the whole project list (500)
  3. FIX         scripts/adopt_orphan_projects.adopt + fix_sequence
  4. VERIFY      reachable, openable, and a new project does not collide

Run through Starlette's TestClient, i.e. the real routes and response models — the 500 in phase 2
only appears at that layer, which is exactly why it is worth testing there.
"""
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

MOCK_DB = "langconfig_kbtest"
DOCS_ROOT = Path("/tmp/langconfig-copied-kb")

# Override the database before db.* is imported: the engine is built from POSTGRES_DB.
os.environ["POSTGRES_DB"] = MOCK_DB
os.environ["WORKSPACE_ROOT"] = "/tmp/langconfig-copied-kb-ws"
# STORAGE_MODE too, and this is not cosmetic: the panel's listing decides between `.kvmeta` and
# `storage_objects` by reading `config.settings.storage_mode` — the .env value — at
# api/knowledge/kv.py:377, while file_storage resolves its root from the storage settings
# *document*. Two sources of truth for one setting: a machine whose .env says `db` while the
# document says `local` lists from one catalog and writes to the other.
os.environ["STORAGE_MODE"] = "local"

BACKEND = Path(__file__).resolve().parents[1]  # scripts/ -> backend/
os.chdir(BACKEND)   # the app resolves relative settings paths against the CWD
sys.path.insert(0, str(BACKEND))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from db.database import engine, init_db  # noqa: E402

URL = engine.url.render_as_string(hide_password=False)
assert MOCK_DB in URL, f"refusing to run outside the scratch DB: {URL}"
MAINT = make_url(URL).set(database="postgres").render_as_string(hide_password=False)

KNOWN_ID = 900          # a project that exists in the database
ORPHAN_ID = 901         # files + .kvmeta, no row: the copied legacy folder
MINIMAL_ID = 902        # phase 2: a row with only id and name


def psql(sql: str) -> str:
    p = subprocess.run(["psql", MAINT, "-tA", "-q", "-v", "ON_ERROR_STOP=1", "-c", sql],
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise SystemExit(f"psql failed: {p.stderr.strip()}")
    return p.stdout.strip()


def make_documents(project_id: int, filenames: list[str]) -> None:
    """A folder plus .kvmeta records, exactly as a legacy copy would arrive."""
    folder = DOCS_ROOT / f"project_{project_id}" / "archive"
    folder.mkdir(parents=True, exist_ok=True)
    records = {}
    for i, name in enumerate(filenames):
        doc_id = uuid.uuid4().hex[:16]
        path = folder / f"{uuid.uuid4().hex[:8]}_{name}"
        path.write_text(f"content of {name}\n")
        records[doc_id] = {
            "id": doc_id, "project_id": project_id, "filename": name,
            "original_filename": name, "size": path.stat().st_size,
            "mime_type": "text/plain", "storage_path": str(path),
            "industry": "archive", "player": None, "sub_category": None,
            "sub_department": None, "created_at": 1786061110.0 + i,
        }
    (DOCS_ROOT / ".kvmeta").mkdir(parents=True, exist_ok=True)
    (DOCS_ROOT / ".kvmeta" / f"project_{project_id}.json").write_text(json.dumps(records))


print("1. scratch database + copied documents tree …")
psql(f'DROP DATABASE IF EXISTS "{MOCK_DB}"')
psql(f'CREATE DATABASE "{MOCK_DB}"')
init_db()
subprocess.run([sys.executable, "scripts/seeds/seed_settings.py"], cwd=str(BACKEND),
               env=dict(os.environ, POSTGRES_DB=MOCK_DB), check=True,
               capture_output=True, text=True)

if DOCS_ROOT.exists():
    subprocess.run(["rm", "-rf", str(DOCS_ROOT)], check=True)
make_documents(KNOWN_ID, ["policy.md", "minutes.md"])
make_documents(ORPHAN_ID, ["legacy-report.md", "legacy-data.csv"])

# Point this database at the scratch tree, with local mode so the listing reads .kvmeta.
# Both must be set BEFORE the app is imported: kv.py caches KV_DATA_DIR at import time.
with engine.begin() as conn:
    conn.execute(text("""
        UPDATE settings_documents
        SET document = jsonb_set(jsonb_set(document::jsonb, '{documents_base_dir}',
                                           to_jsonb(CAST(:root AS text))), '{mode}', '"local"')::json
        WHERE ns = 'storage'
    """), {"root": str(DOCS_ROOT)})
    conn.execute(text("""
        INSERT INTO projects (id, name, description, status, configuration,
                              indexing_status, created_at, updated_at)
        VALUES (:id, 'Known Project', NULL, 'active', '{}'::json, 'not_indexed', now(), now())
    """), {"id": KNOWN_ID})
print(f"   project_{KNOWN_ID} has a row; project_{ORPHAN_ID} has files and .kvmeta only")

from starlette.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402

# raise_server_exceptions=False: a real server turns an unhandled exception into a 500,
# which is what the browser and curl see. Without it TestClient re-raises, and phase 2 —
# the whole point of which is that a partial row breaks the endpoint — would crash the test
# instead of failing a check.
client = TestClient(app, raise_server_exceptions=False)


def project_ids() -> list[int] | None:
    """The ids the Knowledge panel can offer, or None when the endpoint is broken."""
    response = client.get("/api/projects/")
    if response.status_code != 200:
        return None
    return [p["id"] for p in response.json()]


def documents_of(project_id: int):
    response = client.get(f"/api/kv/documents?project_id={project_id}")
    return response.json() if response.status_code == 200 else None


# ── 1. reproduce ─────────────────────────────────────────────────────────────
print("\n2. REPRODUCE — the copied folder is present but unreachable …")
ids_before = project_ids()
orphan_docs = documents_of(ORPHAN_ID)
reachable_before = ids_before is not None and ORPHAN_ID in ids_before
doc_count = len(orphan_docs or [])
first_doc = (orphan_docs or [{}])[0].get("id")
file_status = (client.get(f"/api/kv/documents/{first_doc}/file?project_id={ORPHAN_ID}")
               .status_code if first_doc else None)
print(f"   GET /api/projects/            -> {ids_before}")
print(f"   GET /api/kv/documents?p={ORPHAN_ID} -> {doc_count} document(s)")
print(f"   GET .../file?project_id={ORPHAN_ID} -> HTTP {file_status}")

reproduced = (not reachable_before) and doc_count > 0 and file_status == 200

# ── 2. the trap: a partial row is worse than no row ──────────────────────────
print("\n3. THE TRAP — a row of only id and name …")
with engine.begin() as conn:
    conn.execute(text("INSERT INTO projects (id, name) VALUES (:id, 'Minimal')"),
                 {"id": MINIMAL_ID})
ids_with_minimal = project_ids()
minimal_breaks_endpoint = ids_with_minimal is None
print(f"   GET /api/projects/ -> {'HTTP 500 (ResponseValidationError)' if minimal_breaks_endpoint else ids_with_minimal}")
with engine.begin() as conn:
    conn.execute(text("DELETE FROM projects WHERE id = :id"), {"id": MINIMAL_ID})
print(f"   removed the partial row -> {project_ids()}")

# ── 3. fix ───────────────────────────────────────────────────────────────────
print("\n4. FIX — scripts/adopt_orphan_projects …")
from scripts.adopt_orphan_projects import adopt, find_orphans, fix_sequence  # noqa: E402

# the script resolves the root from the app, which is already redirected here
import services.file_storage as _fs  # noqa: E402
_fs.file_storage._base_dir = DOCS_ROOT

found = [pid for pid, _, _ in find_orphans()]
print(f"   orphans found: {found}")
for pid in found:
    adopt(pid, f"Adopted {pid}")
seq_before, seq_after = fix_sequence()
print(f"   adopted {len(found)}; projects_id_seq {seq_before} -> {seq_after}")

# ── 4. verify ────────────────────────────────────────────────────────────────
print("\n5. VERIFY — reachable, openable, and no id collision …")
ids_after = project_ids()
reachable_after = ids_after is not None and ORPHAN_ID in ids_after
docs_after = documents_of(ORPHAN_ID)
with engine.connect() as conn:
    row = conn.execute(text("""
        SELECT name, status, indexing_status, configuration IS NOT NULL
        FROM projects WHERE id = :id
    """), {"id": ORPHAN_ID}).fetchone()

created = client.post("/api/projects/", json={"name": "Created After Adoption",
                                              "description": "sequence check"})
new_id = created.json().get("id") if created.status_code in (200, 201) else None
print(f"   GET /api/projects/ -> {ids_after}")
print(f"   documents -> {len(docs_after or [])};  new project created -> id {new_id}")

checks = [
    ("the case reproduced: unreachable while its documents exist",
     reproduced and not reachable_before),
    ("its documents were readable the whole time", doc_count == 2 and file_status == 200),
    ("a partial project row breaks the whole list (hence the full-row insert)",
     minimal_breaks_endpoint),
    ("the orphan was found by the fix", ORPHAN_ID in found),
    ("it is now selectable through the API", reachable_after),
    ("its documents are still listed", len(docs_after or []) == 2),
    ("its row has the fields the response model requires",
     bool(row) and row[1] and row[2] and row[3]),
    ("a project created afterwards does not collide", new_id is not None and new_id > ORPHAN_ID),
]
for label, ok in checks:
    print(f"   [{'PASS' if ok else 'FAIL'}] {label}")

failed = [label for label, ok in checks if not ok]
print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed")
print("ALL CHECKS PASSED" if not failed else "SOME CHECKS FAILED")
sys.exit(1 if failed else 0)

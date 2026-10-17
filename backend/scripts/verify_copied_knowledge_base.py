"""The knowledge base is filesystem-only, and a copy of it is a working knowledge base.

    cd <tree>/backend
    .venv/bin/python scripts/verify_copied_knowledge_base.py

The case that stalled a team migration: a legacy `data/documents` folder is copied into a fresh
install, every file and every `.kvmeta` record arrives intact, and the Knowledge panel shows
nothing — because it listed projects from `GET /api/projects/` and there was no row for those ids.
Copying files into a database-shaped feature does not move the feature.

This script asserts the contract that replaced it, through the real routes:

  1. DISCOVERY  a copied folder is listed with NO operator action — straight off the disk by
                `GET /api/kv/bases`, and no longer only because a row was registered. The name is
                the folder name; there is no project id in the request path at all
  2. REGISTRY   the storage settings document cannot repoint the knowledge base — it is set here
                to a nonexistent path and to mode='db', and neither may matter
  3. THE TRAP   a row of only id and name still breaks the whole project list (500), which is why
                the row that gets registered carries every field the response model requires
  4. TOOL       the explicit adopt script is still correct, and now has nothing to do
  5. VERIFY     reachable, openable, and a project created afterwards does not collide

Everything it needs it creates itself: a scratch database (`langconfig_kbtest`), a scratch
documents tree under /tmp, and a fake copied folder. It overrides POSTGRES_DB and
DOCUMENTS_BASE_DIR before importing anything from the app, so it cannot touch the configured
database or the real documents directory.

Run through Starlette's TestClient, i.e. the real routes and response models — the 500 in phase 3
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
# STORAGE_MODE no longer selects the catalog — the knowledge base is filesystem-only — but it is
# still set, so that a regression reintroducing the `db` branch would be caught here.
os.environ["STORAGE_MODE"] = "local"
# The documents root now comes from the environment, never from the settings registry, so this is
# what redirects the knowledge base. It must be set BEFORE the app is imported: kv.py caches
# KV_DATA_DIR at import time.
os.environ["KB_ROOT"] = str(DOCS_ROOT)
# And no legacy fallback: without this, key 1 resolves to the real data/documents.
os.environ["DOCUMENTS_KB_ROOT"] = str(DOCS_ROOT)

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
subprocess.run([sys.executable, "scripts/seeds/in/seed_settings.py"], cwd=str(BACKEND),
               env=dict(os.environ, POSTGRES_DB=MOCK_DB), check=True,
               capture_output=True, text=True)

if DOCS_ROOT.exists():
    subprocess.run(["rm", "-rf", str(DOCS_ROOT)], check=True)
make_documents(KNOWN_ID, ["policy.md", "minutes.md"])
make_documents(ORPHAN_ID, ["legacy-report.md", "legacy-data.csv"])

# Point the *database's* settings document somewhere else entirely. It must have no effect: the
# knowledge base root is a filesystem fact, resolved from the environment. Before this change the
# document won here, which is how a copied row (or a seed snapshot) could silently repoint where
# documents were read from.
with engine.begin() as conn:
    conn.execute(text("""
        UPDATE settings_documents
        SET document = jsonb_set(jsonb_set(document::jsonb, '{documents_base_dir}',
                                           to_jsonb(CAST(:root AS text))), '{mode}', '"db"')::json
        WHERE ns = 'storage'
    """), {"root": "/nonexistent/and-irrelevant"})
    conn.execute(text("""
        INSERT INTO projects (id, name, description, status, configuration,
                              indexing_status, created_at, updated_at)
        VALUES (:id, 'Known Project', NULL, 'active', '{}'::json, 'not_indexed', now(), now())
    """), {"id": KNOWN_ID})
print(f"   project_{KNOWN_ID} has a row; project_{ORPHAN_ID} has files and .kvmeta only")
print("   the settings document points at /nonexistent/and-irrelevant, and mode says 'db'")

from starlette.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402

# raise_server_exceptions=False: a real server turns an unhandled exception into a 500,
# which is what the browser and curl see. Without it TestClient re-raises, and phase 2 —
# the whole point of which is that a partial row breaks the endpoint — would crash the test
# instead of failing a check.
client = TestClient(app, raise_server_exceptions=False)


def project_ids() -> list[int] | None:
    """The ids the project list can offer, or None when the endpoint is broken."""
    response = client.get("/api/projects/")
    if response.status_code != 200:
        return None
    return [p["id"] for p in response.json()]


def knowledge_bases() -> list[dict] | None:
    """The knowledge bases the Knowledge panel lists — from disk, no database — or None."""
    response = client.get("/api/kv/bases")
    return response.json().get("bases") if response.status_code == 200 else None


def documents_of(knowledge: str):
    """A knowledge base's documents, named the way every endpoint names one: by folder."""
    response = client.get("/api/kv/documents", params={"knowledge": knowledge})
    return response.json() if response.status_code == 200 else None


# The copied folder is named `project_901` — the legacy layout, deliberately, because that is
# what a folder copied off an older machine looks like. The knowledge base's name IS that folder
# name, so this is also the handle every endpoint takes.
ORPHAN_KB = f"project_{ORPHAN_ID}"

# ── 1. the copied folder is discovered by listing ────────────────────────────
print("\n2. DISCOVERY — a copied folder registers itself …")
# Asked BEFORE /api/projects/, which is what registers the row: the point is that the listing
# does not depend on the row existing. `/api/kv/bases` reads the disk and nothing else.
bases = knowledge_bases()
listed = [b["key"] for b in (bases or [])]
ids_before = project_ids()
orphan_docs = documents_of(ORPHAN_KB)
reachable = ids_before is not None and ORPHAN_ID in ids_before
# The stronger claim, and the one the panel actually uses: the knowledge base is listed straight
# off the filesystem, so it is present and openable with no row and no database at all.
listed_on_disk = ORPHAN_KB in listed
doc_count = len(orphan_docs or [])
first_doc = (orphan_docs or [{}])[0].get("id")
file_status = (client.get(f"/api/kv/documents/{first_doc}/file",
                          params={"knowledge": ORPHAN_KB})
               .status_code if first_doc else None)
with engine.connect() as conn:
    registered_row = conn.execute(text("""
        SELECT name, status, indexing_status, configuration IS NOT NULL
        FROM projects WHERE id = :id
    """), {"id": ORPHAN_ID}).fetchone()
print(f"   GET /api/kv/bases             -> {listed}")
print(f"   GET /api/projects/            -> {ids_before}")
print(f"   GET /api/kv/documents?knowledge={ORPHAN_KB} -> {doc_count} document(s)")
print(f"   GET .../file?knowledge={ORPHAN_KB} -> HTTP {file_status}")

# The root is a filesystem fact: the settings document pointed elsewhere and said mode='db', and
# neither may matter. This is the check that the knowledge base has no registry dependency.
secret_document_ignored = doc_count == 2 and file_status == 200

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
print("\n4. THE EXPLICIT TOOL — still available, now a no-op …")
from scripts.adopt_orphan_projects import adopt, find_orphans, fix_sequence  # noqa: E402

found = [pid for pid, _, _ in find_orphans()]
print(f"   orphans found: {found}  (registration already happened during listing)")
for pid in found:
    adopt(pid, f"Adopted {pid}")
seq_before, seq_after = fix_sequence()
print(f"   projects_id_seq {seq_before} -> {seq_after}")

# ── 5. verify ────────────────────────────────────────────────────────────────
print("\n5. VERIFY — reachable, openable, and no id collision …")
ids_after = project_ids()
reachable_after = ids_after is not None and ORPHAN_ID in ids_after
docs_after = documents_of(ORPHAN_KB)

created = client.post("/api/projects/", json={"name": "Created After Registration",
                                              "description": "sequence check"})
new_id = created.json().get("id") if created.status_code in (200, 201) else None
print(f"   GET /api/projects/ -> {ids_after}")
print(f"   documents -> {len(docs_after or [])};  new project created -> id {new_id}")

checks = [
    ("a copied folder is listed without any operator action",
     reachable and listed_on_disk),
    ("its documents are listed from .kvmeta", doc_count == 2),
    ("and the file itself opens (HTTP 200)", file_status == 200),
    ("the settings document cannot repoint the knowledge base", secret_document_ignored),
    ("its row got the fields the response model requires",
     bool(registered_row) and registered_row[1] and registered_row[2] and registered_row[3]),
    ("a partial project row still breaks the whole list (hence the full-row insert)",
     minimal_breaks_endpoint),
    ("the explicit tool has nothing left to adopt", ORPHAN_ID not in found),
    ("it is still selectable through the API", reachable_after),
    ("its documents are still listed", len(docs_after or []) == 2),
    ("a project created afterwards does not collide", new_id is not None and new_id > ORPHAN_ID),
]
for label, ok in checks:
    print(f"   [{'PASS' if ok else 'FAIL'}] {label}")

failed = [label for label, ok in checks if not ok]
print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed")
print("ALL CHECKS PASSED" if not failed else "SOME CHECKS FAILED")
sys.exit(1 if failed else 0)

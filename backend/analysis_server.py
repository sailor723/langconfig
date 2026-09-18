"""Standalone Analysis Server — no PostgreSQL. Caches dashboards, supports live data refresh."""
import asyncio, hashlib, json, logging, os, re, sqlite3
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv; load_dotenv(override=True)
from fastapi import FastAPI, APIRouter, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
import uvicorn

from services.csv_to_sqlite import csv_to_sqlite_from_bytes
from services.dashboard_generator import generate_dashboard

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("analysis-server")

ROOT = Path(__file__).resolve().parent.parent
DBS_DIR = ROOT / "data" / "analysis_dbs"
DBS_DIR.mkdir(parents=True, exist_ok=True)
router = APIRouter(prefix="/api/analysis", tags=["analysis"])


# ── Models ──────────────────────────────────────────────────────────

class DashboardFile(BaseModel):
    filename: str; path: str; size_bytes: int; created: str


# ── Metadata store ──────────────────────────────────────────────────
# Each dashboard_<hash>.html has a companion dashboard_<hash>.meta.json
# Stored alongside the HTML in DBS_DIR.

def _meta_path(hash_id: str) -> Path:
    return DBS_DIR / f"dashboard_{hash_id}.meta.json"

def save_meta(hash_id: str, db_path: str, table_name: str, columns: list[str]):
    data = {"db_path": db_path, "table_name": table_name, "columns": columns}
    p = _meta_path(hash_id)
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

def load_meta(hash_id: str) -> Optional[dict]:
    p = _meta_path(hash_id)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None

def _hash_from_filename(fn: str) -> Optional[str]:
    m = re.match(r"dashboard_([a-f0-9]+)\.html", fn)
    return m.group(1) if m else None


# ── Data helpers ────────────────────────────────────────────────────

def query_data(db_path: str, table_name: str) -> list:
    """Query all rows from SQLite, return as 2D array (matching CSV column order)."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(f'SELECT * FROM "{table_name}"')
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description] if cur.description else []
    result = []
    for row in rows:
        result.append([str(v) if v is not None else "" for v in row])
    conn.close()
    return result


def list_dashboards():
    files = sorted(DBS_DIR.glob("dashboard_*.html"), key=lambda f: f.stat().st_mtime, reverse=True)
    return [DashboardFile(filename=f.name, path=f"/api/files/{f.name}",
            size_bytes=f.stat().st_size, created=str(f.stat().st_mtime)) for f in files]


# ── HTML post-processing for refresh ────────────────────────────────

REFRESH_SCRIPT = """
<style>
  #dashRefreshBar {
    display: flex; align-items: center; gap: 10px;
    padding: 8px 16px; background: #1e3a8a; color: white;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    font-size: 13px;
  }
  #dashRefreshBar button {
    background: #3b82f6; color: white; border: none;
    padding: 5px 14px; border-radius: 5px; cursor: pointer; font-size: 13px;
  }
  #dashRefreshBar button:hover { background: #2563eb; }
  #dashRefreshBar button:disabled { opacity: 0.6; cursor: wait; }
  #dashRefreshStatus { opacity: 0.9; }
  #dashRefreshBar .spacer { flex: 1; }
</style>
<div id="dashRefreshBar">
  <span>Data: <span id="dashRefreshRows">--</span> rows</span>
  <div class="spacer"></div>
  <button id="dashRefreshBtn" onclick="dashRefresh()">Refresh from source</button>
  <span id="dashRefreshStatus"></span>
</div>
<script>
async function dashRefresh() {
  const btn = document.getElementById('dashRefreshBtn');
  const status = document.getElementById('dashRefreshStatus');
  btn.disabled = true; status.textContent = 'Loading...';
  try {
    const r = await fetch('/api/analysis/data/HASH_ID');
    if (!r.ok) throw new Error(r.statusText);
    const data = await r.json();
    // Replace the data variable — try common names
    if (typeof salesData !== 'undefined') {
      if (Array.isArray(data) && data.length > 0 && !Array.isArray(data[0])) {
        // Data is array of objects — use as-is
        salesData = data;
      } else {
        // Data is 2D array — convert to objects using column names
        const meta = await fetch('/api/analysis/meta/HASH_ID').then(res => res.json());
        const cols = meta.columns;
        salesData = data.map(row => {
          const obj = {};
          cols.forEach((c, i) => { obj[c.toLowerCase().replace(/\\s+/g, '')] = row[i]; });
          return obj;
        });
      }
    } else if (typeof RAW !== 'undefined') {
      RAW = data;  // 2D array, use as-is
    }
    // Re-render — try common render function names
    if (typeof renderAll === 'function') renderAll(salesData || RAW);
    else if (typeof refreshAll === 'function') refreshAll();
    else if (typeof applyFilters === 'function') applyFilters();
    else location.reload();  // fallback
    status.textContent = 'Updated ' + new Date().toLocaleTimeString();
  } catch (e) {
    status.textContent = 'Error: ' + e.message;
  } finally {
    btn.disabled = false;
  }
}
</script>
"""


def _inject_refresh(html: str, hash_id: str) -> str:
    """Post-process dashboard HTML: replace embedded data with dynamic fetch + refresh bar."""
    # Inject refresh bar + script before </body>
    refresh_html = REFRESH_SCRIPT.replace("HASH_ID", hash_id)
    html = html.replace("</body>", refresh_html + "\n</body>")

    # Try to make the data variable mutable (let instead of const)
    html = html.replace("const salesData", "var salesData")
    html = html.replace("const RAW", "var RAW")
    html = html.replace("const allData", "var allData")

    return html


# ── Endpoints ────────────────────────────────────────────────────────

@router.get("/dashboards")
async def get_dashboards():
    return list_dashboards()


@router.get("/data/{hash_id}")
async def get_data(hash_id: str):
    """Return live data from the SQLite source for a dashboard."""
    meta = load_meta(hash_id)
    if not meta:
        raise HTTPException(404, "Dashboard metadata not found")
    data = query_data(meta["db_path"], meta["table_name"])
    return data


@router.get("/meta/{hash_id}")
async def get_meta_endpoint(hash_id: str):
    """Return column metadata for a dashboard."""
    meta = load_meta(hash_id)
    if not meta:
        raise HTTPException(404, "Dashboard metadata not found")
    return meta


@router.post("/upload")
async def analysis_upload(
    file: UploadFile = File(...),
    skill_file: UploadFile = File(None),
):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files supported")

    csv_bytes = await file.read()
    table_name = Path(file.filename).stem.replace("-", "_").replace(" ", "_")

    # Convert CSV to SQLite
    db_path = csv_to_sqlite_from_bytes(csv_bytes, file.filename, table_name)
    cols, row_count = get_meta(db_path, table_name)

    # Save companion skill if provided
    skill_path = None
    skill_status = "none"
    if skill_file and skill_file.filename:
        skill_path = DBS_DIR / skill_file.filename
        skill_path.write_bytes(await skill_file.read())
        skill_status = "active"

    # Generate dashboard (or cache hit)
    skill_bytes = skill_path.read_bytes() if skill_path else None
    html_path = await generate_dashboard(csv_bytes, skill_bytes, file.filename, str(DBS_DIR))

    # Save metadata for data refresh
    fname = Path(html_path).name
    h = _hash_from_filename(fname)
    if h:
        save_meta(h, db_path, table_name, cols)
        logger.info(f"Saved metadata for dashboard_{h}")

    return {
        "db_path": db_path,
        "table_name": table_name,
        "row_count": row_count,
        "col_count": len(cols),
        "columns": cols,
        "dashboard_file": f"/api/files/{fname}",
        "skill_status": skill_status,
    }


# ── Helpers (duplicated from upload for standalone use) ─────────────

def get_meta(db_path: str, table_name: str) -> tuple:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.execute(f'PRAGMA table_info("{table_name}")')
    cols = [r["name"] for r in c.fetchall()]
    rc = conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
    conn.close()
    return cols, rc


# ── Static files (with refresh injection) ───────────────────────────

file_router = APIRouter()

@file_router.get("/api/files/{fn}")
async def serve(fn: str):
    fp = DBS_DIR / fn
    if not fp.exists() or fp.suffix != ".html":
        raise HTTPException(404)
    html = fp.read_text(encoding="utf-8")
    # Inject refresh if we have metadata
    h = _hash_from_filename(fn)
    if h and _meta_path(h).exists():
        html = _inject_refresh(html, h)
    return HTMLResponse(html)


# ── App ─────────────────────────────────────────────────────────────

app = FastAPI(title="Analysis Server (standalone)")
app.include_router(router)
app.include_router(file_router)


@app.get("/api/chat/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    print(f"Starting standalone analysis server...")
    print(f"  Dashboards: {DBS_DIR}")
    print(f"  API: http://localhost:8765/api/analysis/upload")
    print(f"  Refresh: /api/analysis/data/<hash>")
    print(f"  Docs: http://localhost:8765/docs")
    uvicorn.run(app, host="0.0.0.0", port=8765)

"""
Notebooks API — list, view, edit, and execute Jupyter notebooks.

Uses jupyter_client for stateful kernel execution — variables persist
across cell runs within the same session.
"""
import json
import logging
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from nbformat import v4 as nbf, read as nb_read, write as nb_write

from services.notebook_kernel_manager import get_kernel_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notebooks", tags=["notebooks"])

# Root directory for notebooks
NOTEBOOKS_DIR = Path(__file__).resolve().parent.parent.parent / "notebooks"


# ── Pydantic schemas ──────────────────────────────────────


class NotebookCell(BaseModel):
    """A single notebook cell."""
    index: int
    cell_type: str  # "code" | "markdown"
    source: str
    outputs: List[dict] = []


class NotebookSummary(BaseModel):
    """Brief info for sidebar listing."""
    module: str
    name: str
    display_name: str
    cell_count: int
    path: str


class NotebookDetail(BaseModel):
    """Full notebook content for the viewer."""
    module: str
    name: str
    display_name: str
    cells: List[NotebookCell]
    kernel: Optional[str] = None
    language: str = "python"


class ExecuteRequest(BaseModel):
    """Request to execute cells from a notebook."""
    cell_index: int


class ExecuteResponse(BaseModel):
    """Result of cell execution."""
    success: bool
    stdout: str
    stderr: str
    execute_result: str = ""
    error_name: str = ""
    error_value: str = ""


class SaveCellsRequest(BaseModel):
    """Request to save updated cells to a notebook."""
    cells: List[NotebookCell]


# ── Helpers ───────────────────────────────────────────────


def _validate_path(module: str, name: str):
    """Validate module/name to prevent directory traversal."""
    if ".." in module or ".." in name or "/" in name:
        raise HTTPException(status_code=400, detail="Invalid path")


def _resolve_nb_path(module: str, name: str) -> Path:
    """Resolve notebook path and validate existence."""
    nb_path = NOTEBOOKS_DIR / module / f"{name}.ipynb"
    if not nb_path.exists() or not nb_path.is_file():
        raise HTTPException(status_code=404, detail="Notebook not found")
    return nb_path


def _load_nb_json(path: Path) -> dict:
    """Load notebook JSON safely."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Notebook not found")
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid notebook file: {e}")


def _list_ipynb_files(base: Path) -> List[dict]:
    """Recursively find all .ipynb files, grouped by module."""
    if not base.exists():
        return []
    results = []
    for item in sorted(base.iterdir()):
        if not item.is_dir() or item.name.startswith("."):
            continue
        module = item.name
        for nb_file in sorted(item.rglob("*.ipynb")):
            if ".ipynb_checkpoints" in nb_file.parts:
                continue
            results.append({
                "module": module,
                "name": nb_file.stem,
                "display_name": nb_file.stem.replace("_", " ").replace("-", " ").title(),
                "path": str(nb_file.relative_to(base)),
                "cell_count": _count_cells(nb_file),
            })
    return results


def _count_cells(path: Path) -> int:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return len(json.load(f).get("cells", []))
    except Exception:
        return 0


def _parse_notebook(path: Path) -> NotebookDetail:
    """Parse .ipynb into NotebookDetail."""
    nb = _load_nb_json(path)
    metadata = nb.get("metadata", {})
    kernel_info = metadata.get("kernelspec", {})
    lang_info = metadata.get("language_info", {})

    cells = []
    for i, cell in enumerate(nb.get("cells", [])):
        cells.append(NotebookCell(
            index=i,
            cell_type=cell.get("cell_type", "code"),
            source="".join(cell.get("source", [])),
            outputs=cell.get("outputs", []),
        ))

    rel_path = path.relative_to(NOTEBOOKS_DIR) if NOTEBOOKS_DIR in path.parents else path
    return NotebookDetail(
        module=str(rel_path.parent),
        name=path.stem,
        display_name=path.stem.replace("_", " ").replace("-", " ").title(),
        cells=cells,
        kernel=kernel_info.get("display_name"),
        language=lang_info.get("name", "python"),
    )


def _compute_cells_hash(cells: List[dict]) -> str:
    """Simple hash of cell sources to detect changes."""
    import hashlib
    raw = json.dumps([{"type": c["cell_type"], "src": c["source"]} for c in cells], sort_keys=True)
    return hashlib.md5(raw.encode()).hexdigest()


def _session_id(module: str, name: str) -> str:
    """Generate a deterministic session ID for a notebook."""
    return f"nb_{module}_{name}"


# ── API endpoints ─────────────────────────────────────────


@router.get("", response_model=List[NotebookSummary])
def list_notebooks():
    """List all notebooks grouped by module."""
    files = _list_ipynb_files(NOTEBOOKS_DIR)
    return [NotebookSummary(**f) for f in files]


@router.get("/{module}/{name}", response_model=NotebookDetail)
def get_notebook(module: str, name: str):
    """Get full notebook content with all cells."""
    _validate_path(module, name)
    nb_path = _resolve_nb_path(module, name)
    return _parse_notebook(nb_path)


@router.post("/{module}/{name}/execute", response_model=ExecuteResponse)
def execute_notebook_cell(module: str, name: str, req: ExecuteRequest):
    """
    Execute a notebook cell using a stateful IPython kernel.

    Each notebook gets its own persistent kernel session. Variables defined
    in earlier cells remain available for later cells — just like Jupyter.
    """
    _validate_path(module, name)
    nb_path = _resolve_nb_path(module, name)
    nb = _load_nb_json(nb_path)
    cells = nb.get("cells", [])

    if req.cell_index < 0 or req.cell_index >= len(cells):
        raise HTTPException(
            status_code=400,
            detail=f"Cell index {req.cell_index} out of range (0-{len(cells) - 1})",
        )

    # Get or create the kernel session for this notebook
    sid = _session_id(module, name)
    km = get_kernel_manager()

    try:
        session = km.get_or_create_session(sid, cwd=str(nb_path.parent))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start kernel: {e}")

    # Extract only the code from the requested cell (not all preceding cells)
    # The kernel maintains state, so we only execute the single cell
    cell = cells[req.cell_index]
    if cell.get("cell_type") != "code":
        return ExecuteResponse(
            success=True, stdout="", stderr="",
            execute_result="", error_name="", error_value="",
        )

    source = "".join(cell.get("source", []))

    # Handle IPython magic commands
    code_lines = []
    for line in source.split("\n"):
        stripped = line.strip()
        if stripped.startswith("!"):
            # Shell commands — use subprocess
            import subprocess
            cmd = stripped[1:].strip()
            try:
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                code_lines.append(f"print({json.dumps(result.stdout + result.stderr)})")
            except Exception as e:
                code_lines.append(f"print({json.dumps(str(e))})")
        elif stripped.startswith("%"):
            code_lines.append(f"# IPython magic: {stripped}")
        else:
            code_lines.append(line)

    final_code = "\n".join(code_lines)

    # Execute in kernel
    result = session.execute(final_code)

    return ExecuteResponse(
        success=result["success"],
        stdout=result["stdout"],
        stderr=result["stderr"],
        execute_result=result["execute_result"],
        error_name=result["error_name"],
        error_value=result["error_value"],
    )


@router.post("/{module}/{name}/restart")
def restart_kernel(module: str, name: str):
    """
    Restart the kernel for a notebook (clears all execution state).
    Useful when variables get into a bad state or when re-running from scratch.
    """
    _validate_path(module, name)
    sid = _session_id(module, name)
    km = get_kernel_manager()
    session = km.get_session(sid)
    if session:
        session.restart()
        return {"status": "restarted"}
    return {"status": "no_session"}


@router.post("/{module}/{name}/interrupt")
def interrupt_kernel(module: str, name: str):
    """
    Interrupt the currently running cell execution (sends SIGINT to the kernel).
    Useful when a cell is stuck in an infinite loop or takes too long.
    """
    _validate_path(module, name)
    sid = _session_id(module, name)
    km = get_kernel_manager()
    session = km.get_session(sid)
    if session:
        session.interrupt()
        return {"status": "interrupted"}
    return {"status": "no_session"}


@router.put("/{module}/{name}/cells", response_model=NotebookDetail)
def save_notebook_cells(module: str, name: str, req: SaveCellsRequest):
    """
    Save updated cells to a notebook file.

    Replaces all cells in the .ipynb file with the provided cells.
    Preserves notebook metadata and kernel info.
    """
    _validate_path(module, name)
    nb_path = _resolve_nb_path(module, name)

    # Load existing notebook to preserve metadata
    try:
        nb = nb_read(str(nb_path), as_version=4)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cannot read notebook: {e}")

    # Convert our cell schema to nbformat cells
    new_cells = []
    for cell_data in req.cells:
        if cell_data.cell_type == "code":
            new_cell = nbf.new_code_cell(cell_data.source)
        elif cell_data.cell_type == "markdown":
            new_cell = nbf.new_markdown_cell(cell_data.source)
        else:
            new_cell = nbf.new_raw_cell(cell_data.source)
        new_cells.append(new_cell)

    nb.cells = new_cells

    # Write back
    try:
        nb_write(nb, str(nb_path))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save notebook: {e}")

    return _parse_notebook(nb_path)

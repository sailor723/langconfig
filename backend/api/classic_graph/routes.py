# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
REST API for classic LangGraph workflows.

Endpoints:
- GET  /api/classic-graphs          list
- POST /api/classic-graphs          create
- GET  /api/classic-graphs/{id}     get (incl. spec)
- PUT  /api/classic-graphs/{id}     update
- DELETE /api/classic-graphs/{id}   delete
- POST /api/classic-graphs/{id}/run execute (returns final state)
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.database import get_db
from models.classic_graph import ClassicGraph, ClassicGraphRun
from core.classic_graph import compile_graph, compile_state_for, GraphCompileError

router = APIRouter(prefix="/api/classic-graphs", tags=["classic-graph"])


class ClassicGraphCreate(BaseModel):
    name: str
    description: Optional[str] = None
    spec: Dict[str, Any]


class ClassicGraphUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    spec: Optional[Dict[str, Any]] = None


class ClassicGraphOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    spec: Dict[str, Any]


class ClassicRunRequest(BaseModel):
    input: Dict[str, Any] = {}
    # Optional override of which fields are emitted as "output".
    output_keys: Optional[List[str]] = None


class ClassicRunOut(BaseModel):
    id: int
    status: str
    final_state: Dict[str, Any]
    steps: List[Dict[str, Any]]
    error: Optional[str] = None


def _to_out(g: ClassicGraph) -> ClassicGraphOut:
    return ClassicGraphOut(
        id=g.id, name=g.name, description=g.description, spec=g.spec or {}
    )


@router.get("", response_model=List[ClassicGraphOut])
def list_graphs(db: Session = Depends(get_db)):
    rows = db.query(ClassicGraph).order_by(ClassicGraph.updated_at.desc()).all()
    return [_to_out(r) for r in rows]


@router.post("", response_model=ClassicGraphOut)
def create_graph(payload: ClassicGraphCreate, db: Session = Depends(get_db)):
    if db.query(ClassicGraph).filter(ClassicGraph.name == payload.name).first():
        raise HTTPException(409, f"a graph named '{payload.name}' already exists")
    # Validate the spec compiles (errors are surfaced early).
    try:
        compile_graph(payload.spec)
    except GraphCompileError as e:
        raise HTTPException(400, f"spec does not compile: {e}")
    row = ClassicGraph(
        name=payload.name,
        description=payload.description,
        spec=payload.spec,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.get("/{graph_id}", response_model=ClassicGraphOut)
def get_graph(graph_id: int, db: Session = Depends(get_db)):
    row = db.query(ClassicGraph).filter(ClassicGraph.id == graph_id).first()
    if not row:
        raise HTTPException(404, "graph not found")
    return _to_out(row)


@router.put("/{graph_id}", response_model=ClassicGraphOut)
def update_graph(graph_id: int, payload: ClassicGraphUpdate, db: Session = Depends(get_db)):
    row = db.query(ClassicGraph).filter(ClassicGraph.id == graph_id).first()
    if not row:
        raise HTTPException(404, "graph not found")
    if payload.name and payload.name != row.name:
        if db.query(ClassicGraph).filter(ClassicGraph.name == payload.name).first():
            raise HTTPException(409, f"a graph named '{payload.name}' already exists")
        row.name = payload.name
    if payload.description is not None:
        row.description = payload.description
    if payload.spec is not None:
        try:
            compile_graph(payload.spec)
        except GraphCompileError as e:
            raise HTTPException(400, f"spec does not compile: {e}")
        row.spec = payload.spec
    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.delete("/{graph_id}")
def delete_graph(graph_id: int, db: Session = Depends(get_db)):
    row = db.query(ClassicGraph).filter(ClassicGraph.id == graph_id).first()
    if not row:
        raise HTTPException(404, "graph not found")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.post("/{graph_id}/run", response_model=ClassicRunOut)
async def run_graph(graph_id: int, payload: ClassicRunRequest, db: Session = Depends(get_db)):
    row = db.query(ClassicGraph).filter(ClassicGraph.id == graph_id).first()
    if not row:
        raise HTTPException(404, "graph not found")

    spec = row.spec or {}
    try:
        compiled = compile_graph(spec)
    except GraphCompileError as e:
        raise HTTPException(400, f"spec does not compile: {e}")

    # Build initial state from spec defaults + user input.
    init_state = compile_state_for(spec)
    # User input keys go in directly (so the user can seed any state field).
    for k, v in (payload.input or {}).items():
        init_state[k] = v
    # Convenience: "input" / "query" aliases seed state["messages"] as a
    # HumanMessage so LLM nodes have something to read.
    if "messages" in init_state and not init_state["messages"]:
        text = payload.input.get("query") or payload.input.get("input")
        if text:
            from langchain_core.messages import HumanMessage
            init_state["messages"] = [HumanMessage(content=text)]

    steps: List[Dict[str, Any]] = []
    error: Optional[str] = None
    status = "completed"
    final_state: Dict[str, Any] = {}

    try:
        # Stream so we can record per-node steps. The compiled graph's
        # `.stream(..., stream_mode="updates")` yields `{node: delta}` dicts.
        async for event in compiled.astream(init_state, stream_mode="updates"):
            for node_name, delta in event.items():
                steps.append({"node": node_name, "delta": _jsonable(delta)})
        final_state = compiled.get_state({"configurable": {"thread_id": "x"}}).values
        final_state = _jsonable(final_state)
    except Exception as e:
        error = str(e)
        status = "error"

    run = ClassicGraphRun(
        graph_id=graph_id,
        input_data=payload.input or {},
        final_state=final_state,
        steps=steps,
        status=status,
        error=error,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # Trim to requested output_keys if the caller asked.
    if payload.output_keys:
        final_state = {k: final_state.get(k) for k in payload.output_keys if k in final_state}

    return ClassicRunOut(
        id=run.id,
        status=status,
        final_state=final_state,
        steps=steps,
        error=error,
    )


def _jsonable(obj: Any) -> Any:
    """Recursively convert LangChain messages / datetime etc. to JSON-safe types."""
    from datetime import datetime
    from langchain_core.messages import BaseMessage

    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, BaseMessage):
        return {"type": obj.__class__.__name__, "content": obj.content}
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj
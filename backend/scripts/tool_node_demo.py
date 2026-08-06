# LangConfig workflow demo: dedicated TOOL_NODE with state templating.
#
# Demonstrates the "assign tool calls to a dedicated tool node" design:
#   user input (workflow "query")
#     -> node-extract (LLM_NODE: pulls the number out of the free-form query,
#                      writes it to node_outputs["number"] via output_key)
#     -> node-compute (TOOL_NODE: math_sqrt with {"number": "{{number}}"})
#     -> node-compose (LLM_NODE: turns the tool result into a friendly answer)
#     -> node-end    (END_NODE)
#
# The TOOL_NODE never calls an LLM and the LLM nodes never call tools — each
# step is an explicit graph node. "{{number}}" is resolved from the workflow
# state at execution time (new backend capability).
#
# Usage: backend/.venv/bin/python backend/scripts/tool_node_demo.py "square root of 467" "sqrt 64"
import os
import sys
from pathlib import Path

# Load the project-root .env (DATABASE_URL, model API keys, etc.)
ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"
if ROOT_ENV.exists():
    for line in ROOT_ENV.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

sys.path.insert(0, "backend")

import asyncio
from db.database import SessionLocal
from models.workflow import WorkflowProfile

WORKFLOW_NAME = "Tool Node Demo"
PROJECT_ID = 1
MODEL = "minimax-m3"  # same model the demo11 agent used (key configured in .env)


def build_configuration() -> dict:
    return {
        "nodes": [
            {
                "id": "node-start",
                "type": "START_NODE",
                "data": {"label": "Start", "agentType": "START_NODE", "config": {}},
                "position": {"x": 40, "y": 180},
                "config": {"model": "none", "system_prompt": "", "control_type": "START_NODE"},
            },
            {
                "id": "node-extract",
                "type": "LLM_NODE",
                "data": {"label": "Extract Number", "agentType": "LLM_NODE", "config": {}},
                "position": {"x": 240, "y": 180},
                "config": {
                    "model": MODEL,
                    "temperature": 0.0,
                    # Strict format so the TOOL_NODE template can coerce the
                    # response into the numeric "number" argument.
                    "system_prompt": (
                        "Extract the numeric value from the user's query. "
                        "Reply with ONLY that number (e.g. 467). "
                        "No punctuation, no explanation, no extra text."
                    ),
                    # Handoff: store the LLM response in node_outputs["number"]
                    "output_key": "number",
                },
            },
            {
                "id": "node-compute",
                "type": "TOOL_NODE",
                "data": {"label": "Compute Sqrt", "agentType": "TOOL_NODE", "config": {}},
                "position": {"x": 440, "y": 180},
                "config": {
                    "tool_type": "custom",
                    "tool_id": "math_sqrt",
                    # "{{number}}" is resolved at execution time from the state
                    # (node_outputs["number"] written by the extract node).
                    "tool_params": {"number": "{{number}}"},
                },
            },
            {
                "id": "node-compose",
                "type": "LLM_NODE",
                "data": {"label": "Compose Answer", "agentType": "LLM_NODE", "config": {}},
                "position": {"x": 640, "y": 180},
                "config": {
                    "model": MODEL,
                    "temperature": 0.3,
                    "system_prompt": (
                        "The conversation contains the user's question and the result of a "
                        "square-root computation. Write a concise, friendly final answer that "
                        "states the computed result clearly."
                    ),
                },
            },
            {
                "id": "node-end",
                "type": "END_NODE",
                "data": {"label": "End", "agentType": "END_NODE", "config": {}},
                "position": {"x": 840, "y": 180},
                "config": {"model": "none", "system_prompt": "", "control_type": "END_NODE"},
            },
        ],
        "edges": [
            {"id": "e1", "source": "node-start", "target": "node-extract", "data": {}},
            {"id": "e2", "source": "node-extract", "target": "node-compute", "data": {}},
            {"id": "e3", "source": "node-compute", "target": "node-compose", "data": {}},
            {"id": "e4", "source": "node-compose", "target": "node-end", "data": {}},
        ],
    }


def upsert_workflow(db) -> WorkflowProfile:
    """Create or update the demo workflow in place (UPDATE avoids FK violations
    from execution_events rows referencing the workflow)."""
    wf = db.query(WorkflowProfile).filter(WorkflowProfile.name == WORKFLOW_NAME).first()
    if wf:
        wf.configuration = build_configuration()
        wf.description = (
            "Dedicated tool node demo: LLM extracts a number, a TOOL_NODE computes "
            "sqrt via {{number}} templating, an LLM composes the answer."
        )
        wf.strategy_type = "default_sequential"
    else:
        wf = WorkflowProfile(
            name=WORKFLOW_NAME,
            description=(
                "Dedicated tool node demo: LLM extracts a number, a TOOL_NODE computes "
                "sqrt via {{number}} templating, an LLM composes the answer."
            ),
            project_id=PROJECT_ID,
            strategy_type="default_sequential",
            configuration=build_configuration(),
            debug_mode=False,
        )
        db.add(wf)
    db.commit()
    db.refresh(wf)
    print(f"Workflow '{WORKFLOW_NAME}' ready (id={wf.id})")
    return wf


async def run_demo(wf: WorkflowProfile, queries: list[str]) -> None:
    """Run each query through the REAL LangConfig execution path."""
    from api.workflows.execution import execute_workflow_background
    from models.core import Task, TaskStatus

    db = SessionLocal()
    try:
        for q in queries:
            task = Task(
                project_id=PROJECT_ID,
                description=q,
                status=TaskStatus.QUEUED,
                assigned_model="default",
                workflow_profile_id=wf.id,
            )
            db.add(task)
            db.commit()
            db.refresh(task)

            await execute_workflow_background(
                task_id=task.id,
                project_id=PROJECT_ID,
                workflow_id=wf.id,
                input_data={"query": q},
            )

            db.expire_all()
            task = db.query(Task).filter(Task.id == task.id).first()
            result = task.result or {}
            content = str(result.get("formatted_content", ""))
            msgs = result.get("agent_messages", [])
            print("=" * 70)
            print(f"query: {q!r}  (task #{task.id}, status={task.status})")
            for m in msgs[-4:]:
                print(f"  msg[{m.get('role')}]: {str(m.get('content'))[:160]}")
            print(f"  answer: {content.strip()[:300]}")
    finally:
        db.close()


def main() -> None:
    default_queries = ["square root of 467", "sqrt of 64", "what is the square root of 2"]
    queries = sys.argv[1:] or default_queries

    db = SessionLocal()
    try:
        wf = upsert_workflow(db)
    finally:
        db.close()
    asyncio.run(run_demo(wf, queries))


if __name__ == "__main__":
    main()

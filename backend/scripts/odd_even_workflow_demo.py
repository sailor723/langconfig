# LangConfig workflow demo: the odd/even tutorial implemented as a persisted
# WorkflowProfile and executed through the REAL LangConfig API execution path
# (no LLM anywhere - only the python_execute tool).
#
# Graph:
#   user input (workflow "query" = an integer)
#     -> node-cond    (CONDITIONAL_NODE: query % 2 == 0)
#     -> node-even    (TOOL_NODE echoes "EVEN")  -> node-end-even (END_NODE)
#     -> node-odd     (TOOL_NODE echoes "ODD")   -> node-end-odd  (END_NODE)
#
# The branch terminals are TOOL_NODEs (not bare END_NODEs) so the run produces
# visible output that the API stores on the task row - otherwise a graph with
# only control nodes yields "Workflow completed with no output".
#
# Usage:  backend/.venv/bin/python backend/scripts/odd_even_workflow_demo.py 7 12 3
#         (numbers given as CLI args are the user input; defaults if omitted)
import os
import sys
from pathlib import Path

# Load the project-root .env (DATABASE_URL etc.)
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

WORKFLOW_NAME = "Odd Even Tutorial"
PROJECT_ID = 1


# ---------------------------------------------------------------------------
# Workflow definition: the same JSON the frontend canvas would save.
# type == agentType is the CURRENT schema (see useWorkflowPersistence.ts).
# ---------------------------------------------------------------------------
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
                "id": "node-cond",
                "type": "CONDITIONAL_NODE",
                "data": {"label": "Odd Even Gate", "agentType": "CONDITIONAL_NODE", "config": {}},
                "position": {"x": 240, "y": 180},
                "config": {
                    "model": "none",
                    "system_prompt": "",
                    "control_type": "CONDITIONAL_NODE",
                    # The user's integer rides in the workflow "query" (the same
                    # input the API/UI sends to POST /workflows/{id}/execute)
                    "condition": "int(str(state.get('query', '0')).strip()) % 2 == 0",
                },
            },
            {
                "id": "node-even",
                "type": "TOOL_NODE",
                "data": {"label": "Echo Even", "agentType": "TOOL_NODE", "config": {}},
                "position": {"x": 440, "y": 60},
                "config": {
                    "tool_type": "mcp",
                    "tool_id": "python_execute",
                    "tool_params": {"code": "print('EVEN')"},
                },
            },
            {
                "id": "node-odd",
                "type": "TOOL_NODE",
                "data": {"label": "Echo Odd", "agentType": "TOOL_NODE", "config": {}},
                "position": {"x": 440, "y": 300},
                "config": {
                    "tool_type": "mcp",
                    "tool_id": "python_execute",
                    "tool_params": {"code": "print('ODD')"},
                },
            },
            {
                "id": "node-end-even",
                "type": "END_NODE",
                "data": {"label": "Even Terminal", "agentType": "END_NODE", "config": {}},
                "position": {"x": 620, "y": 60},
                "config": {"model": "none", "system_prompt": "", "control_type": "END_NODE"},
            },
            {
                "id": "node-end-odd",
                "type": "END_NODE",
                "data": {"label": "Odd Terminal", "agentType": "END_NODE", "config": {}},
                "position": {"x": 620, "y": 300},
                "config": {"model": "none", "system_prompt": "", "control_type": "END_NODE"},
            },
        ],
        "edges": [
            {"id": "e1", "source": "node-start", "target": "node-cond", "data": {}},
            # Conditional edges: the label is the ROUTE KEY matched by the builder
            {"id": "e2", "source": "node-cond", "target": "node-even", "data": {"label": "true"}},
            {"id": "e3", "source": "node-cond", "target": "node-odd", "data": {"label": "false"}},
            {"id": "e4", "source": "node-even", "target": "node-end-even", "data": {}},
            {"id": "e5", "source": "node-odd", "target": "node-end-odd", "data": {}},
        ],
    }


def upsert_workflow(db) -> WorkflowProfile:
    """Create or update the demo workflow in place (UPDATE avoids FK violations
    from execution_events rows referencing the workflow)."""
    wf = db.query(WorkflowProfile).filter(WorkflowProfile.name == WORKFLOW_NAME).first()
    if wf:
        wf.configuration = build_configuration()
        wf.description = "Odd/even branching demo (no LLM): a user-input integer is routed to Even/Odd terminals"
        wf.strategy_type = "default_sequential"
    else:
        wf = WorkflowProfile(
            name=WORKFLOW_NAME,
            description="Odd/even branching demo (no LLM): a user-input integer is routed to Even/Odd terminals",
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


async def run_demo(wf: WorkflowProfile, numbers: list[int]) -> None:
    """
    Run each user input through the REAL LangConfig execution path.

    Mirrors POST /api/orchestration/execute -> execute_workflow_background():
      1. create a `tasks` row (queued)
      2. run execute_workflow_background() - exactly what the API background
         task runs: it persists execution events, sums tokens and stores the
         result JSON on the task row
      3. read the persisted task result to observe which branch ran
         (the branch TOOL_NODE echoed "EVEN"/"ODD" into agent_messages)
    """
    from api.workflows.execution import execute_workflow_background
    from models.core import Task, TaskStatus
    from models.execution_event import ExecutionEvent

    evens: list[int] = []
    odds: list[int] = []
    db = SessionLocal()
    try:
        for num in numbers:
            # Step 1: create the task record (like the API endpoint does)
            task = Task(
                project_id=PROJECT_ID,
                description=str(num),  # the user input is stored on the task
                status=TaskStatus.QUEUED,
                assigned_model="default",
                workflow_profile_id=wf.id,
            )
            db.add(task)
            db.commit()
            db.refresh(task)

            # Step 2: run the real background execution path
            await execute_workflow_background(
                task_id=task.id,
                project_id=PROJECT_ID,
                workflow_id=wf.id,
                input_data={"query": str(num)},
            )

            # Step 3: read the persisted result - the branch node echoed
            # "EVEN"/"ODD" via python_execute, so it is in formatted_content.
            # expire_all() forces a real DB re-fetch (the identity map would
            # otherwise return the stale row created above, before execution).
            db.expire_all()
            task = db.query(Task).filter(Task.id == task.id).first()
            content = str((task.result or {}).get("formatted_content", ""))
            branch = "odd" if "ODD" in content.upper() else "even"
            (evens if branch == "even" else odds).append(num)
            n_events = db.query(ExecutionEvent).filter(ExecutionEvent.task_id == task.id).count()
            print(f"input {num:>4} -> {branch:4} (task #{task.id}, {n_events} events, output: {content.strip()!r})")
    finally:
        db.close()

    print("=" * 60)
    print(f"evens collected: {sorted(evens)}")
    print(f"odds  collected: {sorted(odds)}")


def main() -> None:
    # User input: integers from the command line (defaults if none given)
    default_numbers = [5, 8, 3, 10, 1, 6, 9, 2, 7, 4]
    try:
        numbers = [int(a) for a in sys.argv[1:]]
    except ValueError:
        print("Error: all arguments must be integers, e.g. 7 12 3")
        sys.exit(1)
    if not numbers:
        numbers = default_numbers

    db = SessionLocal()
    try:
        wf = upsert_workflow(db)
    finally:
        db.close()
    asyncio.run(run_demo(wf, numbers))


if __name__ == "__main__":
    main()

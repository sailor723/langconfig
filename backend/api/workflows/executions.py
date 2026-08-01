import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from collections import defaultdict
import io
import re
import requests

from db.database import get_db
from models.workflow import WorkflowProfile, WorkflowVersion, WorkflowExecution
from models.execution_event import ExecutionEvent
from core.session_manager import managed_transaction
from .schemas import (
    AgentCostBreakdown,
    ExecutionHistoryEntry,
    ToolUsageBreakdown,
    WorkflowCostMetrics,
    WorkflowExecutionCreate,
    WorkflowExecutionResponse,
)

logger = logging.getLogger(__name__)
# No prefix here: this router is included into routes.router, which already
# carries the "/api/workflows" prefix (FastAPI would otherwise stack prefixes).
router = APIRouter(tags=["workflows"])


def cleanup_execution_history(
    db: Session,
    workflow_id: int,
    max_count: Optional[int] = None,
    retention_days: Optional[int] = None
) -> Dict[str, int]:
    """
    Clean up old execution history for a workflow.

    Removes executions that exceed configured limits:
    - Count-based: Keep only the N most recent executions
    - Age-based: Remove executions older than retention period

    Configurable execution history limits
    - Prevents unbounded growth of execution records
    - Improves query performance for execution history
    - Configurable via environment variables

    Args:
        db: Database session
        workflow_id: ID of the workflow to clean up
        max_count: Maximum executions to keep (defaults to settings value)
        retention_days: Max age in days (defaults to settings value)

    Returns:
        Dict with cleanup statistics:
        {
            "removed_by_count": int,
            "removed_by_age": int,
            "total_removed": int,
            "remaining": int
        }
    """
    from config import settings

    max_count = max_count or settings.max_execution_history_per_workflow
    retention_days = retention_days or settings.execution_history_retention_days

    removed_by_count = 0
    removed_by_age = 0

    try:
        # Cleanup 1: Remove executions beyond max count
        # Keep the N most recent executions, delete the rest
        if max_count > 0:
            # Get all executions for this workflow, ordered by completion time
            all_executions = db.query(WorkflowExecution).filter(
                WorkflowExecution.workflow_id == workflow_id
            ).order_by(desc(WorkflowExecution.completed_at)).all()

            # If we have more than max_count, delete the excess
            if len(all_executions) > max_count:
                executions_to_delete = all_executions[max_count:]
                execution_ids_to_delete = [e.id for e in executions_to_delete]

                # Delete in batch
                deleted = db.query(WorkflowExecution).filter(
                    WorkflowExecution.id.in_(execution_ids_to_delete)
                ).delete(synchronize_session=False)

                removed_by_count = deleted
                logger.info(
                    f"Removed {deleted} old executions for workflow {workflow_id} (count limit: {max_count})",
                    extra={
                        "workflow_id": workflow_id,
                        "removed_count": deleted,
                        "max_count": max_count
                    }
                )

        # Cleanup 2: Remove executions older than retention period
        if retention_days > 0:
            cutoff_date = datetime.utcnow() - timedelta(days=retention_days)

            deleted = db.query(WorkflowExecution).filter(
                WorkflowExecution.workflow_id == workflow_id,
                WorkflowExecution.completed_at < cutoff_date
            ).delete(synchronize_session=False)

            removed_by_age = deleted
            logger.info(
                f"Removed {deleted} expired executions for workflow {workflow_id} (older than {retention_days} days)",
                extra={
                    "workflow_id": workflow_id,
                    "removed_count": deleted,
                    "retention_days": retention_days,
                    "cutoff_date": cutoff_date.isoformat()
                }
            )

        # Commit cleanup changes
        db.commit()

        # Count remaining executions
        remaining = db.query(WorkflowExecution).filter(
            WorkflowExecution.workflow_id == workflow_id
        ).count()

        total_removed = removed_by_count + removed_by_age

        logger.info(
            f"Execution history cleanup completed for workflow {workflow_id}",
            extra={
                "workflow_id": workflow_id,
                "removed_by_count": removed_by_count,
                "removed_by_age": removed_by_age,
                "total_removed": total_removed,
                "remaining": remaining
            }
        )

        return {
            "removed_by_count": removed_by_count,
            "removed_by_age": removed_by_age,
            "total_removed": total_removed,
            "remaining": remaining
        }

    except Exception as e:
        db.rollback()
        logger.error(
            f"Failed to cleanup execution history for workflow {workflow_id}: {e}",
            exc_info=True,
            extra={"workflow_id": workflow_id}
        )
        # Return empty stats on error
        return {
            "removed_by_count": 0,
            "removed_by_age": 0,
            "total_removed": 0,
            "remaining": 0
        }


@router.post("/{workflow_id}/executions", response_model=WorkflowExecutionResponse, status_code=201)
async def create_workflow_execution(
    workflow_id: int,
    execution_data: WorkflowExecutionCreate,
    db: Session = Depends(get_db)
):
    """
    Record a workflow execution tied to a specific version.

    This tracks execution results, performance metrics, and costs.

    Raises:
        HTTPException 404: Workflow or version not found
        HTTPException 400: Version does not belong to workflow
        HTTPException 500: Server error
    """
    try:
        with managed_transaction(db, f"create_execution_{workflow_id}"):
            # Check if workflow exists
            workflow = db.query(WorkflowProfile).filter(
                WorkflowProfile.id == workflow_id
            ).first()

            if not workflow:
                raise HTTPException(status_code=404, detail="Workflow not found")

            # CRITICAL FIX: Check version exists AND belongs to this workflow
            # This prevents creating executions with versions from different workflows
            version = db.query(WorkflowVersion).filter(
                WorkflowVersion.id == execution_data.version_id,
                WorkflowVersion.workflow_id == workflow_id  # ← ADDED VALIDATION
            ).first()

            if not version:
                raise HTTPException(
                    status_code=404,
                    detail=f"Version {execution_data.version_id} not found for workflow {workflow_id}"
                )

            # Create execution record (now guaranteed to have valid foreign keys)
            execution = WorkflowExecution(
                workflow_id=workflow_id,
                version_id=execution_data.version_id,
                execution_results=execution_data.execution_results,
                token_usage=execution_data.token_usage,
                cost=execution_data.cost,
                execution_time=execution_data.execution_time,
                status=execution_data.status,
                error_message=execution_data.error_message,
                started_at=execution_data.started_at
            )

            db.add(execution)

        # Transaction commits here
        db.refresh(execution)

        logger.info(
            f"Created execution for workflow {workflow_id}, version {execution_data.version_id}",
            extra={
                "workflow_id": workflow_id,
                "version_id": execution_data.version_id,
                "execution_id": execution.id,
                "status": execution.status
            }
        )

        # Auto-cleanup old execution history if enabled
        from config import settings
        if settings.auto_cleanup_execution_history:
            try:
                cleanup_stats = cleanup_execution_history(db, workflow_id)
                if cleanup_stats["total_removed"] > 0:
                    logger.info(
                        f"Auto-cleanup removed {cleanup_stats['total_removed']} old executions for workflow {workflow_id}",
                        extra=cleanup_stats
                    )
            except Exception as cleanup_error:
                # Don't fail the request if cleanup fails
                logger.warning(
                    f"Auto-cleanup failed for workflow {workflow_id}: {cleanup_error}",
                    exc_info=True
                )

        return execution

    except HTTPException:
        # Re-raise HTTP exceptions (they're intentional)
        raise

    except Exception as e:
        # Unexpected error
        logger.error(
            f"Failed to create execution for workflow {workflow_id}: {e}",
            exc_info=True,
            extra={"workflow_id": workflow_id}
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create execution: {str(e)}"
        )


@router.get("/{workflow_id}/executions", response_model=List[WorkflowExecutionResponse])
async def list_workflow_executions(
    workflow_id: int,
    version_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """
    List executions for a workflow, optionally filtered by version.

    Returns executions in reverse chronological order (newest first).
    """
    query = db.query(WorkflowExecution).filter(WorkflowExecution.workflow_id == workflow_id)

    if version_id:
        query = query.filter(WorkflowExecution.version_id == version_id)

    executions = query.order_by(desc(WorkflowExecution.completed_at)).offset(skip).limit(limit).all()

    return executions


@router.post("/{workflow_id}/executions/cleanup")
async def cleanup_workflow_executions(
    workflow_id: int,
    max_count: Optional[int] = None,
    retention_days: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """
    Manually trigger execution history cleanup for a workflow.

    Configurable execution history limits
    - Allows manual cleanup of old execution records
    - Accepts optional overrides for max_count and retention_days
    - Returns statistics about what was cleaned up

    Args:
        workflow_id: ID of the workflow to clean up
        max_count: Override max executions to keep (defaults to config)
        retention_days: Override max age in days (defaults to config)

    Returns:
        Cleanup statistics with removed counts and remaining executions
    """
    # Verify workflow exists
    workflow = db.query(WorkflowProfile).filter(
        WorkflowProfile.id == workflow_id
    ).first()

    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Trigger cleanup
    try:
        cleanup_stats = cleanup_execution_history(
            db,
            workflow_id,
            max_count=max_count,
            retention_days=retention_days
        )

        logger.info(
            f"Manual cleanup triggered for workflow {workflow_id}",
            extra={
                "workflow_id": workflow_id,
                "stats": cleanup_stats
            }
        )

        return {
            "workflow_id": workflow_id,
            "cleanup_stats": cleanup_stats,
            "message": f"Cleaned up {cleanup_stats['total_removed']} old executions"
        }

    except Exception as e:
        logger.error(
            f"Failed to cleanup executions for workflow {workflow_id}: {e}",
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to cleanup executions: {str(e)}"
        )


@router.get("/{workflow_id}/metrics/cost", response_model=WorkflowCostMetrics)
async def get_workflow_cost_metrics(
    workflow_id: int,
    days: int = 30,
    db: Session = Depends(get_db)
):
    """
    Get aggregated cost metrics for a workflow over a specified period.

    Returns:
    - Total cost and token usage
    - Cost breakdown by agent
    - Tool usage statistics
    - Recent execution history

    Args:
        workflow_id: ID of the workflow
        days: Number of days to include in metrics (default: 30)
    """
    # Check if workflow exists
    workflow = db.query(WorkflowProfile).filter(WorkflowProfile.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Calculate date threshold
    cutoff_date = datetime.utcnow() - timedelta(days=days)

    # Try to get executions (may be empty if orchestration doesn't create them)
    executions = db.query(WorkflowExecution).filter(
        WorkflowExecution.workflow_id == workflow_id,
        WorkflowExecution.completed_at >= cutoff_date
    ).order_by(desc(WorkflowExecution.completed_at)).all()

    # Initialize aggregation variables
    total_cost = 0.0
    total_tokens = 0
    prompt_tokens = 0
    completion_tokens = 0
    agent_costs: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"cost": 0.0, "tokens": 0})
    tool_usage: Dict[str, int] = defaultdict(int)
    execution_history = []

    # If no workflow_executions exist, aggregate from execution_events (LLM_END events)
    # This is the primary data source for workflows using the custom tracing system
    if not executions:
        logger.info(f"No workflow_executions found for workflow {workflow_id}, aggregating from execution_events")

        # Query LLM_END events for token/cost data
        llm_events = db.query(ExecutionEvent).filter(
            ExecutionEvent.workflow_id == workflow_id,
            ExecutionEvent.event_type == "LLM_END",
            ExecutionEvent.timestamp >= cutoff_date
        ).all()

        # Query tool events for tool usage tracking
        tool_events = db.query(ExecutionEvent).filter(
            ExecutionEvent.workflow_id == workflow_id,
            ExecutionEvent.event_type == "on_tool_start",
            ExecutionEvent.timestamp >= cutoff_date
        ).all()

        # Count completed tasks as execution count
        from models.core import Task
        completed_tasks = db.query(Task).filter(
            Task.workflow_profile_id == workflow_id,
            Task.status == 'completed',
            Task.completed_at >= cutoff_date
        ).count()

        # Aggregate tokens and costs by agent
        for event in llm_events:
            event_data = event.event_data or {}
            agent_name = event_data.get("agent_label", "Unknown")
            model = event_data.get("model", "unknown")
            tokens = event_data.get("tokens_used", 0)
            prompt = event_data.get("prompt_tokens", 0)
            completion = event_data.get("completion_tokens", 0)

            # Aggregate totals
            total_tokens += tokens
            prompt_tokens += prompt
            completion_tokens += completion

            # Aggregate by agent
            if agent_name not in agent_costs:
                agent_costs[agent_name] = {"cost": 0.0, "tokens": 0, "model": model}
            agent_costs[agent_name]["tokens"] += tokens

        # Aggregate tool usage
        for event in tool_events:
            event_data = event.event_data or {}
            tool_name = event_data.get("tool_name", "unknown")
            if tool_name and tool_name != "unknown":
                tool_usage[tool_name] += 1

        # Calculate costs using pricing table (Updated December 2025)
        cost_per_1m_tokens = {
            # OpenAI Reasoning Models
            "o3": 20.00,
            "o3-mini": 4.00,
            "o4-mini": 3.00,
            # OpenAI GPT-4o Series
            "gpt-4o": 2.50,
            "gpt-4o-mini": 0.15,
            # Anthropic Claude 4.5
            "claude-opus-4-5": 15.00,
            "claude-sonnet-4-5": 3.00,
            "claude-sonnet-4-5-20250929": 3.00,
            "claude-haiku-4-5": 1.00,
            # Google Gemini 3
            "gemini-3-pro-preview": 2.00,
            # Google Gemini 2.5
            "gemini-2.5-flash": 0.075,
            # Google Gemini 2.0
            "gemini-2.0-flash": 0.075,
            "default": 1.00
        }

        for agent_name, data in agent_costs.items():
            model = data.get("model", "unknown").lower()
            rate = next((v for k, v in cost_per_1m_tokens.items() if k in model), cost_per_1m_tokens["default"])
            agent_cost = (data["tokens"] / 1_000_000) * rate
            data["cost"] = round(agent_cost, 4)
            total_cost += agent_cost

        total_cost = round(total_cost, 4)

        # Convert to response format
        agents_list = [
            AgentCostBreakdown(name=name, cost=data["cost"], tokens=data["tokens"])
            for name, data in agent_costs.items()
        ]
        agents_list.sort(key=lambda x: x.cost, reverse=True)

        tools_list = [
            ToolUsageBreakdown(name=tool_name, count=count)
            for tool_name, count in tool_usage.items()
        ]
        tools_list.sort(key=lambda x: x.count, reverse=True)

        logger.info(f"Aggregated from events: {len(llm_events)} LLM calls, {len(tool_events)} tool calls, {total_tokens} tokens, ${total_cost}")

        return WorkflowCostMetrics(
            workflow_id=workflow_id,
            workflow_name=workflow.name,
            totalCost=total_cost,
            totalTokens=total_tokens,
            promptTokens=prompt_tokens,
            completionTokens=completion_tokens,
            executionCount=completed_tasks,
            agents=agents_list,
            tools=tools_list,
            executionHistory=[],
            period_days=days
        )

    # Aggregate data from executions
    for execution in executions:
        # Aggregate costs and tokens
        if execution.cost:
            total_cost += execution.cost

        if execution.token_usage:
            token_data = execution.token_usage
            exec_total = token_data.get("total_tokens", 0)
            exec_prompt = token_data.get("input_tokens", 0) or token_data.get("prompt_tokens", 0)
            exec_completion = token_data.get("output_tokens", 0) or token_data.get("completion_tokens", 0)

            total_tokens += exec_total
            prompt_tokens += exec_prompt
            completion_tokens += exec_completion

        # Extract agent-level data from execution_results if available
        if execution.execution_results:
            results = execution.execution_results

            # Try to extract agent-specific costs
            # Structure may vary, check common patterns
            if "agent_outputs" in results:
                for agent_name, agent_data in results["agent_outputs"].items():
                    if isinstance(agent_data, dict):
                        agent_cost = agent_data.get("cost", 0)
                        agent_tokens = agent_data.get("tokens", 0)
                        agent_costs[agent_name]["cost"] += agent_cost
                        agent_costs[agent_name]["tokens"] += agent_tokens

            # Extract tool usage
            if "tool_calls" in results:
                for tool_call in results["tool_calls"]:
                    if isinstance(tool_call, dict):
                        tool_name = tool_call.get("tool", tool_call.get("name", "unknown"))
                        tool_usage[tool_name] += 1
            elif "tools_used" in results:
                for tool_name in results["tools_used"]:
                    tool_usage[tool_name] += 1

        # Add to execution history
        execution_history.append({
            "timestamp": execution.completed_at.isoformat() if execution.completed_at else datetime.utcnow().isoformat(),
            "cost": execution.cost or 0.0,
            "tokens": (execution.token_usage or {}).get("total_tokens", 0)
        })

    # Convert agent costs dict to list
    agents_list = [
        AgentCostBreakdown(
            name=agent_name,
            cost=data["cost"],
            tokens=data["tokens"]
        )
        for agent_name, data in agent_costs.items()
    ]

    # Convert tool usage dict to list
    tools_list = [
        ToolUsageBreakdown(name=tool_name, count=count)
        for tool_name, count in tool_usage.items()
    ]

    # Sort by cost/count descending
    agents_list.sort(key=lambda x: x.cost, reverse=True)
    tools_list.sort(key=lambda x: x.count, reverse=True)

    return WorkflowCostMetrics(
        workflow_id=workflow_id,
        workflow_name=workflow.name,
        totalCost=total_cost,
        totalTokens=total_tokens,
        promptTokens=prompt_tokens,
        completionTokens=completion_tokens,
        executionCount=len(executions),
        agents=agents_list,
        tools=tools_list,
        executionHistory=execution_history[:10],  # Limit to 10 most recent
        period_days=days
    )


@router.get("/executions/{execution_id}/export/docx")
async def export_execution_to_word(
    execution_id: int,
    db: Session = Depends(get_db)
):
    """
    Export a workflow execution result to a Word document (.docx)
    This endpoint uses Task IDs from the orchestration system
    """
    try:
        from docx import Document
        from docx.shared import Inches, Pt, RGBColor
        from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
        from models.core import Task

        # Fetch the task (using execution_id which is actually a task_id)
        task = db.query(Task).filter(Task.id == execution_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        # Get the workflow
        workflow = db.query(WorkflowProfile).filter(WorkflowProfile.id == task.workflow_profile_id).first()

        # Log task data for debugging
        logger.info(f"Exporting task {execution_id} with status: {task.status}")
        logger.info(f"Task result type: {type(task.result)}")
        if task.result:
            logger.info(f"Task result keys: {task.result.keys() if isinstance(task.result, dict) else 'Not a dict'}")

        # Create document
        doc = Document()

        # Add title
        title = doc.add_heading(workflow.name if workflow else "Workflow Results", 0)
        title.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER

        # Add metadata section
        doc.add_heading('Execution Details', level=1)

        metadata_table = doc.add_table(rows=5, cols=2)
        # Use a simpler table style that's guaranteed to exist
        try:
            metadata_table.style = 'Light Grid Accent 1'
        except:
            # Fallback to basic table style
            metadata_table.style = 'Table Grid'

        # Date
        metadata_table.rows[0].cells[0].text = 'Date:'
        metadata_table.rows[0].cells[1].text = task.completed_at.strftime('%Y-%m-%d %H:%M:%S') if task.completed_at else (task.created_at.strftime('%Y-%m-%d %H:%M:%S') if task.created_at else 'N/A')

        # Status
        metadata_table.rows[1].cells[0].text = 'Status:'
        metadata_table.rows[1].cells[1].text = task.status.value if hasattr(task.status, 'value') else str(task.status)

        # Duration
        duration_text = 'N/A'
        if task.created_at and task.completed_at:
            duration_seconds = (task.completed_at - task.created_at).total_seconds()
            if duration_seconds < 60:
                duration_text = f"{round(duration_seconds)}s"
            else:
                minutes = int(duration_seconds // 60)
                seconds = int(duration_seconds % 60)
                duration_text = f"{minutes}m {seconds}s"
        metadata_table.rows[2].cells[0].text = 'Duration:'
        metadata_table.rows[2].cells[1].text = duration_text

        # Tokens
        tokens = 'N/A'
        if task.result and isinstance(task.result, dict):
            workflow_summary = task.result.get('workflow_summary', {})
            if workflow_summary.get('total_tokens'):
                tokens = f"{workflow_summary['total_tokens']:,}"
        metadata_table.rows[3].cells[0].text = 'Tokens:'
        metadata_table.rows[3].cells[1].text = tokens

        # Cost
        cost = 'N/A'
        if task.result and isinstance(task.result, dict):
            workflow_summary = task.result.get('workflow_summary', {})
            if workflow_summary.get('total_cost_usd') is not None:
                cost = f"${workflow_summary['total_cost_usd']:.4f}"
        metadata_table.rows[4].cells[0].text = 'Cost:'
        metadata_table.rows[4].cells[1].text = cost

        doc.add_paragraph()  # Add space

        # Add results section
        doc.add_heading('Results', level=1)

        # Get the formatted content
        content = ''
        if task.result and isinstance(task.result, dict):
            content = task.result.get('formatted_content', '') or task.result.get('final_output', '')
            logger.info(f"Content length: {len(content) if content else 0}")

        if not content:
            content = 'No output available'

        # Ensure content is a string
        if not isinstance(content, str):
            logger.warning(f"Content is not a string, converting: {type(content)}")
            content = str(content)

        # Parse markdown-like content and add to document
        try:
            lines = content.split('\n')
        except Exception as e:
            logger.error(f"Error splitting content: {e}")
            lines = ['Error processing content']

        for i, line in enumerate(lines):
            try:
                # Handle headers
                if line.startswith('# '):
                    doc.add_heading(line[2:], level=1)
                elif line.startswith('## '):
                    doc.add_heading(line[3:], level=2)
                elif line.startswith('### '):
                    doc.add_heading(line[4:], level=3)
                # Handle images ![alt](url)
                elif re.match(r'!\[.*?\]\((.*?)\)', line):
                    match = re.match(r'!\[.*?\]\((.*?)\)', line)
                    if match:
                        image_url = match.group(1)
                        try:
                            # Download image
                            response = requests.get(image_url, timeout=10)
                            if response.status_code == 200:
                                image_stream = io.BytesIO(response.content)
                                doc.add_picture(image_stream, width=Inches(5))
                                # Add caption
                                caption = doc.add_paragraph()
                                caption.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
                        except Exception as e:
                            logger.warning(f"Failed to download image {image_url}: {e}")
                            doc.add_paragraph(f"[Image: {image_url}]")
                # Handle regular text
                elif line.strip():
                    # Remove markdown formatting
                    clean_line = line
                    clean_line = re.sub(r'\*\*(.*?)\*\*', r'\1', clean_line)  # Bold
                    clean_line = re.sub(r'\*(.*?)\*', r'\1', clean_line)  # Italic
                    clean_line = re.sub(r'`(.*?)`', r'\1', clean_line)  # Code
                    doc.add_paragraph(clean_line)
                else:
                    # Empty line - add small space
                    doc.add_paragraph()
            except Exception as line_error:
                logger.warning(f"Error processing line {i}: {line_error}")
                # Continue with next line instead of failing entirely
                continue

        # Save to BytesIO
        file_stream = io.BytesIO()
        doc.save(file_stream)
        file_stream.seek(0)

        # Create filename
        filename = f"{workflow.name.replace(' ', '_')}_{execution_id}.docx" if workflow else f"workflow_results_{execution_id}.docx"

        return StreamingResponse(
            file_stream,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    except HTTPException:
        # Re-raise HTTP exceptions as-is (404, etc.)
        raise
    except ImportError as e:
        logger.error(f"Import error in Word export: {e}")
        raise HTTPException(status_code=500, detail="python-docx library not installed")
    except Exception as e:
        logger.error(f"Error exporting to Word: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")

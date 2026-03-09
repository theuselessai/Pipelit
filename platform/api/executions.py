"""Execution list/detail/cancel endpoint."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import logging

from auth import get_current_user
from database import get_db
from models.execution import ExecutionLog, WorkflowExecution
from models.user import UserProfile
from models.workflow import Workflow
from schemas.execution import ExecutionDetailOut, ExecutionOut

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/")
def list_executions(
    workflow_slug: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    q = (
        db.query(WorkflowExecution)
        .join(Workflow, Workflow.id == WorkflowExecution.workflow_id)
        .filter(Workflow.owner_id == profile.id)
    )
    if workflow_slug:
        q = q.filter(Workflow.slug == workflow_slug)
    if status:
        q = q.filter(WorkflowExecution.status == status)
    total = q.count()
    executions = q.order_by(WorkflowExecution.started_at.desc()).offset(offset).limit(limit).all()
    return {"items": [_serialize_execution(e, db) for e in executions], "total": total}


@router.get("/{execution_id}/", response_model=ExecutionDetailOut)
def get_execution(
    execution_id: str,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    execution = (
        db.query(WorkflowExecution)
        .join(Workflow, Workflow.id == WorkflowExecution.workflow_id)
        .filter(
            WorkflowExecution.execution_id == execution_id,
            Workflow.owner_id == profile.id,
        )
        .first()
    )
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found.")
    logs = db.query(ExecutionLog).filter(ExecutionLog.execution_id == execution_id).all()
    data = _serialize_execution(execution, db)
    data["final_output"] = execution.final_output
    data["trigger_payload"] = execution.trigger_payload
    data["logs"] = [
        {
            "id": log.id,
            "node_id": log.node_id,
            "status": log.status,
            "input": log.input,
            "output": log.output,
            "error": log.error,
            "error_code": log.error_code,
            "metadata": log.log_metadata,
            "duration_ms": log.duration_ms,
            "timestamp": log.timestamp,
        }
        for log in logs
    ]
    return data


@router.post("/{execution_id}/cancel/", response_model=ExecutionOut)
def cancel_execution(
    execution_id: str,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    execution = (
        db.query(WorkflowExecution)
        .join(Workflow, Workflow.id == WorkflowExecution.workflow_id)
        .filter(
            WorkflowExecution.execution_id == execution_id,
            Workflow.owner_id == profile.id,
        )
        .first()
    )
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found.")
    if execution.status in ("pending", "running", "interrupted"):
        execution.status = "cancelled"
        execution.completed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(execution)

        # Clean up Redis keys for this execution
        from services.execution_recovery import _cleanup_redis
        _cleanup_redis(execution.execution_id)

        # Clear stale LangGraph checkpoints to prevent INVALID_CHAT_HISTORY
        # on the next conversation turn (agent mid-tool-call leaves orphaned tool_calls)
        try:
            from services.orchestrator import _clear_stale_checkpoints
            _clear_stale_checkpoints(execution.execution_id, db)
        except Exception:
            logger.exception("Failed to clear stale checkpoints for %s", execution.execution_id)

        # Notify frontend via WebSocket (best-effort)
        try:
            from ws.broadcast import broadcast
            wf = db.query(Workflow).filter(Workflow.id == execution.workflow_id).first()
            if wf:
                broadcast(f"workflow:{wf.slug}", "execution_cancelled",
                          {"execution_id": execution.execution_id})
        except Exception:
            logger.exception("Failed to broadcast execution_cancelled for %s", execution.execution_id)

    return _serialize_execution(execution, db)


class BatchDeleteExecutionsIn(BaseModel):
    execution_ids: list[str]


@router.post("/batch-delete/", status_code=204)
def batch_delete_executions(
    payload: BatchDeleteExecutionsIn,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    if not payload.execution_ids:
        return
    # Only delete executions belonging to workflows owned by this user
    owned_exec_ids = [
        e.execution_id for e in
        db.query(WorkflowExecution.execution_id)
        .join(Workflow, Workflow.id == WorkflowExecution.workflow_id)
        .filter(
            WorkflowExecution.execution_id.in_(payload.execution_ids),
            Workflow.owner_id == profile.id,
        )
        .all()
    ]
    if not owned_exec_ids:
        return
    db.query(ExecutionLog).filter(
        ExecutionLog.execution_id.in_(owned_exec_ids),
    ).delete(synchronize_session=False)
    db.query(WorkflowExecution).filter(
        WorkflowExecution.execution_id.in_(owned_exec_ids),
    ).delete(synchronize_session=False)
    db.commit()


def _serialize_execution(execution: WorkflowExecution, db: Session) -> dict:
    workflow = db.query(Workflow).filter(Workflow.id == execution.workflow_id).first()
    return {
        "execution_id": execution.execution_id,
        "workflow_slug": workflow.slug if workflow else "",
        "status": execution.status,
        "error_message": execution.error_message or "",
        "started_at": execution.started_at,
        "completed_at": execution.completed_at,
        "total_tokens": execution.total_tokens or 0,
        "total_cost_usd": float(execution.total_cost_usd) if execution.total_cost_usd is not None else 0.0,
        "llm_calls": execution.llm_calls or 0,
    }

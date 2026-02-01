"""Execution list/detail/cancel + chat endpoint."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models.execution import ExecutionLog, WorkflowExecution
from models.node import WorkflowNode
from models.user import UserProfile
from models.workflow import Workflow
from schemas.execution import ChatMessageIn, ChatMessageOut, ExecutionDetailOut, ExecutionOut

router = APIRouter()


@router.get("/", response_model=list[ExecutionOut])
def list_executions(
    workflow_slug: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    q = db.query(WorkflowExecution).filter(WorkflowExecution.user_profile_id == profile.id)
    if workflow_slug:
        q = q.join(Workflow).filter(Workflow.slug == workflow_slug)
    if status:
        q = q.filter(WorkflowExecution.status == status)
    executions = q.all()
    return [_serialize_execution(e, db) for e in executions]


@router.get("/{execution_id}/", response_model=ExecutionDetailOut)
def get_execution(
    execution_id: str,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    execution = (
        db.query(WorkflowExecution)
        .filter(
            WorkflowExecution.execution_id == execution_id,
            WorkflowExecution.user_profile_id == profile.id,
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
        .filter(
            WorkflowExecution.execution_id == execution_id,
            WorkflowExecution.user_profile_id == profile.id,
        )
        .first()
    )
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found.")
    if execution.status in ("pending", "running", "interrupted"):
        execution.status = "cancelled"
        db.commit()
        db.refresh(execution)
    return _serialize_execution(execution, db)


# ── Chat endpoint (nested under workflows) ────────────────────────────────────

from fastapi import APIRouter as _AR

chat_router = _AR(tags=["chat"])


@chat_router.post("/{slug}/chat/", response_model=ChatMessageOut)
def send_chat_message(
    slug: str,
    payload: ChatMessageIn,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    workflow = db.query(Workflow).filter(Workflow.slug == slug, Workflow.deleted_at.is_(None)).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found.")

    if payload.trigger_node_id:
        trigger_node = (
            db.query(WorkflowNode)
            .filter(
                WorkflowNode.workflow_id == workflow.id,
                WorkflowNode.node_id == payload.trigger_node_id,
                WorkflowNode.component_type == "trigger_chat",
            )
            .first()
        )
    else:
        trigger_node = (
            db.query(WorkflowNode)
            .filter(WorkflowNode.workflow_id == workflow.id, WorkflowNode.component_type == "trigger_chat")
            .first()
        )
    if not trigger_node:
        raise HTTPException(status_code=404, detail="No chat trigger found.")

    execution = WorkflowExecution(
        workflow_id=workflow.id,
        trigger_node_id=trigger_node.id,
        user_profile_id=profile.id,
        thread_id=uuid.uuid4().hex,
        trigger_payload={"text": payload.text},
    )
    db.add(execution)
    db.commit()
    db.refresh(execution)

    # Enqueue via RQ — frontend connects via WebSocket to stream results
    import redis
    from rq import Queue

    from config import settings
    from tasks import execute_workflow_job

    conn = redis.from_url(settings.REDIS_URL)
    queue = Queue("workflows", connection=conn)
    queue.enqueue(execute_workflow_job, str(execution.execution_id))

    return ChatMessageOut(
        execution_id=execution.execution_id,
        status="pending",
        response="",
    )


def _serialize_execution(execution: WorkflowExecution, db: Session) -> dict:
    workflow = db.query(Workflow).filter(Workflow.id == execution.workflow_id).first()
    return {
        "execution_id": execution.execution_id,
        "workflow_slug": workflow.slug if workflow else "",
        "status": execution.status,
        "error_message": execution.error_message or "",
        "started_at": execution.started_at,
        "completed_at": execution.completed_at,
    }

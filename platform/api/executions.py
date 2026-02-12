"""Execution list/detail/cancel + chat endpoint."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models.execution import ExecutionLog, WorkflowExecution
from models.node import WorkflowNode
from models.user import UserProfile
from models.workflow import Workflow
from schemas.execution import ChatMessageIn, ChatMessageOut, ExecutionDetailOut, ExecutionOut

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
    q = db.query(WorkflowExecution).filter(WorkflowExecution.user_profile_id == profile.id)
    if workflow_slug:
        q = q.join(Workflow).filter(Workflow.slug == workflow_slug)
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
    db.query(ExecutionLog).filter(
        ExecutionLog.execution_id.in_(payload.execution_ids),
    ).delete(synchronize_session=False)
    db.query(WorkflowExecution).filter(
        WorkflowExecution.execution_id.in_(payload.execution_ids),
        WorkflowExecution.user_profile_id == profile.id,
    ).delete(synchronize_session=False)
    db.commit()


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


class ChatHistoryMessageOut(BaseModel):
    role: str
    text: str
    timestamp: str | None = None


class ChatHistoryOut(BaseModel):
    messages: list[ChatHistoryMessageOut]
    thread_id: str
    has_more: bool = False


@chat_router.get("/{slug}/chat/history")
def get_chat_history(
    slug: str,
    limit: int = 10,
    before: str | None = None,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    """Load chat history from LangGraph checkpoints.

    Args:
        slug: Workflow slug
        limit: Max messages to return (default 10)
        before: ISO datetime string - only return messages before this time
    """
    from datetime import datetime

    workflow = db.query(Workflow).filter(Workflow.slug == slug, Workflow.deleted_at.is_(None)).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found.")

    # Construct thread_id (same logic as agent.py)
    # For chat triggers, there's no telegram_chat_id
    thread_id = f"{profile.id}:{workflow.id}"

    # Get checkpoint
    from components.agent import _get_checkpointer

    checkpointer = _get_checkpointer()
    config = {"configurable": {"thread_id": thread_id}}

    try:
        checkpoint_tuple = checkpointer.get_tuple(config)
    except Exception:
        return ChatHistoryOut(messages=[], thread_id=thread_id, has_more=False)

    if not checkpoint_tuple or not checkpoint_tuple.checkpoint:
        return ChatHistoryOut(messages=[], thread_id=thread_id, has_more=False)

    # Extract messages from checkpoint
    state = checkpoint_tuple.checkpoint.get("channel_values", {})
    messages = state.get("messages", [])

    # Parse before datetime if provided
    before_dt = None
    if before:
        try:
            before_dt = datetime.fromisoformat(before.replace("Z", "+00:00"))
        except ValueError:
            pass

    # Convert to frontend format with timestamps
    all_messages = []
    for msg in messages:
        if hasattr(msg, "type") and hasattr(msg, "content"):
            # Skip system prompt fallback message
            if getattr(msg, "id", None) == "system_prompt_fallback":
                continue

            # Extract timestamp from additional_kwargs if available
            timestamp = None
            if hasattr(msg, "additional_kwargs"):
                ts = msg.additional_kwargs.get("timestamp")
                if ts:
                    timestamp = ts
            # Fallback: use response_metadata.created for AI messages
            if not timestamp and hasattr(msg, "response_metadata"):
                created = msg.response_metadata.get("created")
                if created:
                    # Convert Unix timestamp to ISO
                    timestamp = datetime.fromtimestamp(created).isoformat()

            if msg.type == "human":
                all_messages.append(ChatHistoryMessageOut(
                    role="user",
                    text=msg.content,
                    timestamp=timestamp,
                ))
            elif msg.type == "ai":
                # Skip empty AI messages (often tool calls)
                if msg.content:
                    all_messages.append(ChatHistoryMessageOut(
                        role="assistant",
                        text=msg.content,
                        timestamp=timestamp,
                    ))

    # Filter by before datetime if provided
    if before_dt:
        filtered = []
        for msg in all_messages:
            if msg.timestamp:
                try:
                    msg_dt = datetime.fromisoformat(msg.timestamp.replace("Z", "+00:00"))
                    if msg_dt < before_dt:
                        filtered.append(msg)
                except ValueError:
                    filtered.append(msg)
            else:
                filtered.append(msg)
        all_messages = filtered

    # Return last N messages
    has_more = len(all_messages) > limit
    result = all_messages[-limit:] if limit > 0 else all_messages

    return ChatHistoryOut(messages=result, thread_id=thread_id, has_more=has_more)


@chat_router.delete("/{slug}/chat/history", status_code=204)
def delete_chat_history(
    slug: str,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    """Delete chat history from LangGraph checkpoints for this workflow."""
    workflow = db.query(Workflow).filter(Workflow.slug == slug, Workflow.deleted_at.is_(None)).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found.")

    thread_id = f"{profile.id}:{workflow.id}"

    from components.agent import _get_checkpointer

    checkpointer = _get_checkpointer()
    conn = checkpointer.conn

    conn.execute("DELETE FROM writes WHERE thread_id = ?", (thread_id,))
    conn.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
    conn.commit()


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

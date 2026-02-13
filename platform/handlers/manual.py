"""Manual trigger handler — FastAPI endpoints."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from handlers import dispatch_event
from models.execution import WorkflowExecution
from models.node import WorkflowNode
from models.user import UserProfile
from models.workflow import Workflow

logger = logging.getLogger(__name__)

router = APIRouter()


class ManualExecuteIn(BaseModel):
    text: str = ""
    trigger_node_id: str | None = None


@router.post("/workflows/{workflow_slug}/execute/")
def manual_execute_view(
    workflow_slug: str,
    payload: ManualExecuteIn = ManualExecuteIn(),
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    workflow = db.query(Workflow).filter(Workflow.slug == workflow_slug, Workflow.is_active == True).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if payload.trigger_node_id:
        # Direct lookup — bypass dispatch_event and resolver
        trigger_node = (
            db.query(WorkflowNode)
            .filter(
                WorkflowNode.workflow_id == workflow.id,
                WorkflowNode.node_id == payload.trigger_node_id,
                WorkflowNode.component_type == "trigger_manual",
            )
            .first()
        )
        if not trigger_node:
            raise HTTPException(status_code=404, detail="Manual trigger node not found")

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

        import redis
        from rq import Queue

        from config import settings
        from tasks import execute_workflow_job

        conn = redis.from_url(settings.REDIS_URL)
        queue = Queue("workflows", connection=conn)
        from services.execution_recovery import on_execution_job_failure
        queue.enqueue(execute_workflow_job, str(execution.execution_id),
                      on_failure=on_execution_job_failure)
    else:
        # Fallback — existing dispatch_event path
        event_data = {"text": payload.text, "workflow_slug": workflow_slug}
        execution = dispatch_event("manual", event_data, profile, db)

    if execution is None:
        raise HTTPException(status_code=404, detail="No trigger configured for manual execution")

    return {
        "execution_id": str(execution.execution_id),
        "status": execution.status,
    }


@router.get("/executions/{execution_id}/status/")
def execution_status_view(
    execution_id: str,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    execution = db.query(WorkflowExecution).filter(WorkflowExecution.execution_id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")

    workflow = db.query(Workflow).filter(Workflow.id == execution.workflow_id).first()
    return {
        "execution_id": str(execution.execution_id),
        "workflow": workflow.slug if workflow else "",
        "status": execution.status,
        "started_at": execution.started_at.isoformat() if execution.started_at else None,
        "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
        "final_output": execution.final_output,
        "error_message": execution.error_message or None,
    }

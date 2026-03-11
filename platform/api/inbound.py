"""Inbound webhook endpoint — receives messages from msg-gateway."""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone

import redis
from sqlalchemy.exc import IntegrityError
from fastapi import APIRouter, Depends, HTTPException, Response, status
from rq import Queue
from sqlalchemy.orm import Session

from auth import verify_gateway_token
from config import settings
from database import get_db
from handlers import dispatch_event
from models.execution import PendingTask
from models.node import WorkflowNode
from models.user import UserProfile
from models.workflow import Workflow
from schemas.inbound import GatewayInboundMessage
from services.gateway_client import get_gateway_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["inbound"])

# Regex for /confirm_<task_id> and /cancel_<task_id>
_CONFIRM_RE = re.compile(r"^/confirm_(\w+)$")
_CANCEL_RE = re.compile(r"^/cancel_(\w+)$")


@router.post("/inbound")
def inbound_webhook(
    payload: GatewayInboundMessage,
    response: Response,
    db: Session = Depends(get_db),
    _auth: None = Depends(verify_gateway_token),
):
    """Receive a normalized message from msg-gateway and dispatch to workflow."""

    # 1. Extract and validate route fields
    workflow_slug = payload.route.get("workflow_slug")
    trigger_node_id = payload.route.get("trigger_node_id")
    if not workflow_slug or not trigger_node_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="route must contain workflow_slug and trigger_node_id",
        )

    # 2. Look up workflow
    wf = db.query(Workflow).filter(Workflow.slug == workflow_slug).first()
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # 3. Check workflow is active
    if not wf.is_active:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Workflow is inactive",
        )

    # 4. Look up trigger node
    node = (
        db.query(WorkflowNode)
        .filter(
            WorkflowNode.workflow_id == wf.id,
            WorkflowNode.node_id == trigger_node_id,
        )
        .first()
    )
    if not node:
        raise HTTPException(status_code=404, detail="Trigger node not found")

    # 5. Handle /confirm_xxx and /cancel_xxx commands
    text_stripped = payload.text.strip()
    confirm_match = _CONFIRM_RE.match(text_stripped)
    cancel_match = _CANCEL_RE.match(text_stripped)

    if confirm_match or cancel_match:
        match = confirm_match or cancel_match
        task_id = match.group(1)  # type: ignore[union-attr]
        action = "confirm" if confirm_match else "cancel"
        response.status_code = 200
        return _handle_confirmation(
            task_id=task_id,
            action=action,
            credential_id=payload.credential_id,
            chat_id=payload.source.chat_id,
            db=db,
        )

    # 6. Get or create user profile
    user_profile = _get_or_create_profile(payload.source.from_, db)

    # 7. Build event_data with attachment tags
    text = payload.text
    for att in payload.attachments:
        text += f"\n[Attached file: {att.filename} | url: {att.download_url} | type: {att.mime_type}]"

    event_data = {
        "text": text,
        "chat_id": payload.source.chat_id,
        "message_id": payload.source.message_id,
        "credential_id": payload.credential_id,
        "user_id": payload.source.from_.id if payload.source.from_ else "",
        "files": [
            {
                "filename": a.filename,
                "mime_type": a.mime_type,
                "size_bytes": a.size_bytes,
                "url": a.download_url,
            }
            for a in payload.attachments
        ],
    }

    # 8. Dispatch event
    execution = dispatch_event(
        "gateway_inbound",
        event_data,
        user_profile,
        db,
        workflow_id=wf.id,
        trigger_node_id=node.node_id,
    )

    if execution is None:
        raise HTTPException(
            status_code=500,
            detail="Execution failed to start",
        )

    response.status_code = 202
    return {
        "execution_id": str(execution.execution_id),
        "status": "pending",
    }


def _handle_confirmation(
    task_id: str,
    action: str,
    credential_id: str,
    chat_id: str,
    db: Session,
) -> dict:
    """Handle /confirm_xxx or /cancel_xxx commands."""
    from tasks import resume_workflow_job

    pending = db.query(PendingTask).filter(PendingTask.task_id == task_id).first()
    if not pending:
        return {"status": "not_found", "task_id": task_id}

    # Check expiry
    if pending.expires_at < datetime.now(timezone.utc):
        db.delete(pending)
        db.commit()

        # Notify user via gateway
        try:
            gw = get_gateway_client()
            gw.send_message(
                credential_id=pending.credential_id or credential_id,
                chat_id=pending.chat_id or chat_id,
                text="This confirmation has expired.",
            )
        except Exception:
            logger.warning("Failed to send expiry notification via gateway", exc_info=True)

        return {"status": "expired", "task_id": task_id}

    execution = pending.execution
    use_credential_id = pending.credential_id or credential_id
    use_chat_id = pending.chat_id or chat_id

    if action == "cancel":
        db.delete(pending)
        db.commit()

        execution.status = "cancelled"
        execution.completed_at = datetime.now(timezone.utc)
        db.commit()

        try:
            gw = get_gateway_client()
            gw.send_message(
                credential_id=use_credential_id,
                chat_id=use_chat_id,
                text="Action cancelled.",
            )
        except Exception:
            logger.warning("Failed to send cancellation notification via gateway", exc_info=True)

        return {"status": "cancelled", "task_id": task_id}

    # confirm → resume execution
    # Enqueue BEFORE committing the delete so we don't lose the task on crash
    conn = redis.from_url(settings.REDIS_URL)
    try:
        queue = Queue("workflows", connection=conn)
        queue.enqueue(resume_workflow_job, str(execution.execution_id), action)
    finally:
        conn.close()

    db.delete(pending)
    db.commit()

    try:
        gw = get_gateway_client()
        gw.send_message(
            credential_id=use_credential_id,
            chat_id=use_chat_id,
            text="Action confirmed. Resuming execution...",
        )
    except Exception:
        logger.warning("Failed to send confirmation notification via gateway", exc_info=True)

    return {"status": "confirmed", "task_id": task_id}


def _get_or_create_profile(from_user, db: Session) -> UserProfile:
    """Get or create a UserProfile from the inbound message source.from field."""
    if from_user is None:
        # Anonymous profile
        profile = db.query(UserProfile).filter(UserProfile.username == "gateway_anonymous").first()
        if profile:
            return profile
        import bcrypt

        profile = UserProfile(
            username="gateway_anonymous",
            password_hash=bcrypt.hashpw(uuid.uuid4().hex.encode(), bcrypt.gensalt()).decode(),
        )
        db.add(profile)
        try:
            db.commit()
            db.refresh(profile)
            return profile
        except IntegrityError:
            db.rollback()
            profile = db.query(UserProfile).filter(UserProfile.username == "gateway_anonymous").first()
            if profile:
                return profile
            raise

    ext_id = from_user.id
    profile = db.query(UserProfile).filter(UserProfile.external_user_id == ext_id).first()
    if profile:
        return profile

    # Create new profile
    username = from_user.username or f"gw_{ext_id}"

    import bcrypt

    # Ensure username uniqueness with retry on race condition
    base_username = username
    counter = 1
    max_retries = 5
    for attempt in range(max_retries):
        while db.query(UserProfile).filter(UserProfile.username == username).first():
            username = f"{base_username}_{counter}"
            counter += 1

        profile = UserProfile(
            username=username,
            external_user_id=ext_id,
            password_hash=bcrypt.hashpw(uuid.uuid4().hex.encode(), bcrypt.gensalt()).decode(),
        )
        db.add(profile)
        try:
            db.commit()
            db.refresh(profile)
            return profile
        except IntegrityError:
            db.rollback()
            if attempt == max_retries - 1:
                raise
            # Another request created this username concurrently; retry with next suffix
            username = f"{base_username}_{counter}"
            counter += 1

    raise RuntimeError("Unreachable: username retry loop exhausted")

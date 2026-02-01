"""Webhook handler — FastAPI endpoint for incoming webhooks."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from handlers import dispatch_event
from models.user import UserProfile

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/webhooks/{webhook_path}/")
def webhook_view(
    webhook_path: str,
    request: Request,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    import json
    try:
        body = json.loads(request._body) if hasattr(request, "_body") else {}
    except (json.JSONDecodeError, AttributeError):
        body = {}

    event_data = {
        "path": webhook_path,
        "body": body,
        "headers": dict(request.headers),
    }

    secret_header = request.headers.get("x-webhook-secret", "")
    if secret_header:
        event_data["provided_secret"] = secret_header

    execution = dispatch_event("webhook", event_data, profile, db)

    if execution is None:
        raise HTTPException(status_code=404, detail="No workflow matched this webhook path")

    return {
        "execution_id": str(execution.execution_id),
        "status": execution.status,
    }

"""Users API — manage agent users."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models.user import APIKey, UserProfile
from schemas.auth import AgentUserResponse

router = APIRouter()


@router.get("/agents/")
def list_agent_users(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
):
    """List all agent users."""
    base = (
        db.query(UserProfile)
        .filter(UserProfile.is_agent == True)  # noqa: E712
        .order_by(UserProfile.created_at.desc())
    )
    total = base.count()
    agent_users = base.offset(offset).limit(limit).all()

    result = []
    for agent in agent_users:
        # Get API key preview (last 8 chars)
        api_key_preview = ""
        if agent.api_key:
            api_key_preview = f"...{agent.api_key.key[-8:]}"

        # Get creator username
        created_by = None
        if agent.created_by_agent_id:
            creator = db.query(UserProfile).filter(UserProfile.id == agent.created_by_agent_id).first()
            if creator:
                created_by = creator.username

        result.append(AgentUserResponse(
            id=agent.id,
            username=agent.username,
            purpose=agent.first_name or "",
            api_key_preview=api_key_preview,
            created_at=agent.created_at,
            created_by=created_by,
        ))

    return {"items": result, "total": total}


@router.delete("/agents/{user_id}/", status_code=204)
def delete_agent_user(
    user_id: int,
    db: Session = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
):
    """Delete an agent user and revoke their API key."""
    agent = (
        db.query(UserProfile)
        .filter(UserProfile.id == user_id, UserProfile.is_agent == True)  # noqa: E712
        .first()
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent user not found")

    # Delete API key first (due to FK constraint)
    db.query(APIKey).filter(APIKey.user_id == user_id).delete()

    # Delete the user
    db.delete(agent)
    db.commit()


class BatchDeleteAgentUsersIn(BaseModel):
    ids: list[int]


@router.post("/agents/batch-delete/", status_code=204)
def batch_delete_agent_users(
    payload: BatchDeleteAgentUsersIn,
    db: Session = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
):
    if not payload.ids:
        return
    # Delete API keys first
    db.query(APIKey).filter(APIKey.user_id.in_(payload.ids)).delete(synchronize_session=False)
    db.query(UserProfile).filter(
        UserProfile.id.in_(payload.ids),
        UserProfile.is_agent == True,  # noqa: E712
    ).delete(synchronize_session=False)
    db.commit()

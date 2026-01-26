"""Session REST API endpoints (for future web UI)."""
from fastapi import APIRouter, HTTPException

from app.services.sessions import SessionService

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("/{user_id}/stats")
async def get_session_stats(user_id: int) -> dict:
    """Get session statistics for a user."""
    service = SessionService()
    return service.get_stats(user_id)


@router.delete("/{user_id}")
async def clear_session(user_id: int) -> dict:
    """Clear session for a user."""
    service = SessionService()
    service.clear_conversation(user_id)
    return {"status": "cleared", "user_id": user_id}


@router.get("/{user_id}/messages")
async def get_messages(user_id: int) -> dict:
    """Get conversation messages for a user."""
    service = SessionService()
    messages = service.get_conversation(user_id)
    return {"user_id": user_id, "messages": messages, "count": len(messages)}

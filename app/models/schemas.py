"""Pydantic schemas for data validation."""
from datetime import datetime

from pydantic import BaseModel


class Message(BaseModel):
    """Chat message schema."""

    role: str  # "user", "assistant", "system"
    content: str


class ConversationStats(BaseModel):
    """Conversation statistics."""

    user_id: int
    message_count: int
    token_count: int
    created_at: datetime | None
    updated_at: datetime | None


class ChatRequest(BaseModel):
    """Chat request from user."""

    user_id: int
    chat_id: int
    message_id: int
    text: str


class ChatResponse(BaseModel):
    """Chat response to user."""

    status: str
    response: str
    token_count: int


class JobStatus(BaseModel):
    """Background job status."""

    job_id: str
    status: str  # "queued", "started", "finished", "failed"
    result: str | None = None

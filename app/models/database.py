"""Database model definitions."""
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Conversation:
    """Conversation database model."""

    user_id: int
    messages: str  # JSON-encoded list of messages
    token_count: int
    created_at: datetime
    updated_at: datetime

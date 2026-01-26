"""Data access layer for SQLite database."""
import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Generator

from app.config import settings

logger = logging.getLogger(__name__)


class ConversationRepository:
    """Repository for conversation data operations."""

    def __init__(self, db_path: str | None = None):
        """Initialize repository with database path."""
        self.db_path = db_path or settings.DB_PATH
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    user_id INTEGER PRIMARY KEY,
                    messages TEXT NOT NULL,
                    token_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
        logger.info(f"Database initialized: {self.db_path}")

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Get database connection context manager."""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def get_conversation(self, user_id: int) -> list[dict]:
        """Load conversation messages for a user."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT messages FROM conversations WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            return json.loads(row["messages"]) if row else []

    def save_conversation(
        self, user_id: int, messages: list[dict], token_count: int
    ) -> None:
        """Save conversation for a user."""
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO conversations (user_id, messages, token_count, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    messages = excluded.messages,
                    token_count = excluded.token_count,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, json.dumps(messages), token_count),
            )
            conn.commit()

    def clear_conversation(self, user_id: int) -> None:
        """Clear conversation for a user."""
        with self._get_connection() as conn:
            conn.execute(
                "DELETE FROM conversations WHERE user_id = ?", (user_id,)
            )
            conn.commit()

    def get_stats(self, user_id: int) -> dict:
        """Get conversation statistics for a user."""
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT messages, token_count, created_at, updated_at
                FROM conversations WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()

            if not row:
                return {
                    "user_id": user_id,
                    "message_count": 0,
                    "token_count": 0,
                    "created_at": None,
                    "updated_at": None,
                }

            messages = json.loads(row["messages"])
            return {
                "user_id": user_id,
                "message_count": len(messages),
                "token_count": row["token_count"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }


# Singleton instance for convenience
_repository: ConversationRepository | None = None


def get_repository() -> ConversationRepository:
    """Get or create repository instance."""
    global _repository
    if _repository is None:
        _repository = ConversationRepository()
    return _repository

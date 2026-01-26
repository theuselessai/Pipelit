"""
Session management with SQLite persistence and automatic context compression.
"""
import json
import logging
import re
import sqlite3

import httpx
import tiktoken

from config import config

logger = logging.getLogger(__name__)

# Token encoder (cl100k_base works for most modern models)
_encoding = tiktoken.get_encoding("cl100k_base")

# Cache for model context windows
_model_context_windows: dict[str, int] = {}


def init_db() -> sqlite3.Connection:
    """Initialize database and return connection."""
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
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
    logger.info(f"Database initialized: {config.DB_PATH}")
    return conn


def get_conversation(conn: sqlite3.Connection, user_id: int) -> list[dict]:
    """Load conversation for a user."""
    row = conn.execute(
        "SELECT messages FROM conversations WHERE user_id = ?",
        (user_id,)
    ).fetchone()
    return json.loads(row[0]) if row else []


def save_conversation(
    conn: sqlite3.Connection,
    user_id: int,
    messages: list[dict],
    token_count: int
) -> None:
    """Save conversation for a user."""
    conn.execute("""
        INSERT INTO conversations (user_id, messages, token_count, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET
            messages = excluded.messages,
            token_count = excluded.token_count,
            updated_at = CURRENT_TIMESTAMP
    """, (user_id, json.dumps(messages), token_count))
    conn.commit()


def clear_conversation(conn: sqlite3.Connection, user_id: int) -> None:
    """Clear conversation for a user."""
    conn.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))
    conn.commit()


def get_stats(conn: sqlite3.Connection, user_id: int) -> dict:
    """Get conversation stats for a user."""
    row = conn.execute(
        "SELECT messages, token_count, created_at, updated_at FROM conversations WHERE user_id = ?",
        (user_id,)
    ).fetchone()

    if not row:
        return {"message_count": 0, "token_count": 0, "created_at": None, "updated_at": None}

    messages = json.loads(row[0])
    return {
        "message_count": len(messages),
        "token_count": row[1],
        "created_at": row[2],
        "updated_at": row[3],
    }


def count_tokens(messages: list[dict]) -> int:
    """Count tokens in a conversation."""
    total = 0
    for message in messages:
        # ~4 tokens per message for role/formatting overhead
        total += 4
        total += len(_encoding.encode(message.get("content", "")))
    return total


def strip_thinking_tags(text: str) -> str:
    """Remove <think>...</think> blocks from response."""
    # Remove thinking blocks (handles multiline)
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # Clean up extra whitespace
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


async def fetch_model_context_windows(http_client: httpx.AsyncClient) -> dict[str, int]:
    """Fetch context windows from Venice.ai API."""
    global _model_context_windows

    if not config.VENICE_API_KEY:
        logger.warning("VENICE_API_KEY not set, using default context window")
        return {}

    try:
        response = await http_client.get(
            f"{config.VENICE_API_BASE}/models",
            headers={"Authorization": f"Bearer {config.VENICE_API_KEY}"}
        )
        response.raise_for_status()

        _model_context_windows = {
            model["id"]: model["model_spec"]["availableContextTokens"]
            for model in response.json()["data"]
            if "model_spec" in model and "availableContextTokens" in model["model_spec"]
        }

        logger.info(f"Fetched context windows for {len(_model_context_windows)} models")
        return _model_context_windows

    except Exception as e:
        logger.error(f"Failed to fetch model context windows: {e}")
        return {}


def get_context_window(model: str) -> int:
    """Get context window for a model."""
    # Strip provider prefix if present (e.g., "venice:glm-4.7" -> "glm-4.7")
    model_id = model.split(":")[-1] if ":" in model else model
    return _model_context_windows.get(model_id, config.DEFAULT_CONTEXT_WINDOW)


def get_compress_threshold(model: str) -> int:
    """Get compression threshold for a model."""
    return int(get_context_window(model) * config.COMPRESS_RATIO)


async def compress_conversation(
    messages: list[dict],
    http_client: httpx.AsyncClient,
) -> list[dict]:
    """Compress conversation by summarizing old messages."""
    if len(messages) <= config.KEEP_RECENT_MESSAGES:
        return messages

    # Separate system messages and conversation
    system_msgs = [m for m in messages if m["role"] == "system"]
    conversation = [m for m in messages if m["role"] != "system"]

    # Keep recent messages
    recent = conversation[-config.KEEP_RECENT_MESSAGES:]
    old = conversation[:-config.KEEP_RECENT_MESSAGES]

    if not old:
        return messages

    # Format old messages for summarization
    old_text = "\n".join(
        f"{m['role'].upper()}: {m['content']}"
        for m in old
    )

    summarize_prompt = (
        "Summarize this conversation in 200 words or less. "
        "Focus on key topics, decisions, and context needed to continue.\n\n"
        f"{old_text}"
    )

    try:
        response = await http_client.post(
            f"{config.AICHAT_BASE_URL}/v1/chat/completions",
            json={
                "model": config.AICHAT_MODEL,
                "messages": [{"role": "user", "content": summarize_prompt}],
                "stream": False,
            },
        )
        response.raise_for_status()
        summary = response.json()["choices"][0]["message"]["content"]

        logger.info(f"Compressed {len(old)} messages into summary")

        # Rebuild conversation with summary
        compressed = system_msgs + [
            {"role": "system", "content": f"Previous conversation summary:\n{summary}"}
        ] + recent

        return compressed

    except Exception as e:
        logger.error(f"Compression failed: {e}")
        # Fallback: just keep recent messages
        return system_msgs + recent


async def process_message(
    conn: sqlite3.Connection,
    http_client: httpx.AsyncClient,
    user_id: int,
    user_message: str,
) -> str:
    """Process a user message with session management."""
    # Load existing conversation
    messages = get_conversation(conn, user_id)

    # Add user message
    messages.append({"role": "user", "content": user_message})

    # Check if compression is needed
    token_count = count_tokens(messages)
    threshold = get_compress_threshold(config.AICHAT_MODEL)

    if token_count > threshold:
        logger.info(f"Token count {token_count} exceeds threshold {threshold}, compressing...")
        messages = await compress_conversation(messages, http_client)
        token_count = count_tokens(messages)

    # Send to AIChat
    try:
        response = await http_client.post(
            f"{config.AICHAT_BASE_URL}/v1/chat/completions",
            json={
                "model": config.AICHAT_MODEL,
                "messages": messages,
                "stream": False,
            },
        )
        response.raise_for_status()
        assistant_message = response.json()["choices"][0]["message"]["content"]

        # Strip thinking tags for display
        display_message = strip_thinking_tags(assistant_message)

        # Store full message (with thinking) for context continuity
        messages.append({"role": "assistant", "content": assistant_message})
        token_count = count_tokens(messages)

        # Save conversation
        save_conversation(conn, user_id, messages, token_count)

        return display_message

    except httpx.TimeoutException:
        # Save the user message so it's not lost
        save_conversation(conn, user_id, messages, count_tokens(messages))
        logger.warning(f"Request timed out for user {user_id}")
        raise

    except httpx.HTTPStatusError as e:
        error_text = str(e.response.text).lower()
        if "context length" in error_text or "too many tokens" in error_text:
            # Emergency compression: keep only last few messages
            logger.warning("Context overflow, performing emergency compression")
            messages = messages[-4:]
            save_conversation(conn, user_id, messages, count_tokens(messages))
            return "Context was too long. I've cleared some history. Please try again."
        raise

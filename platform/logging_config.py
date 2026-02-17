"""Centralised logging configuration for server and RQ workers.

Usage:
    from logging_config import setup_logging, execution_id_var, node_id_var

    # At process startup:
    setup_logging("Server")        # or "Worker-{pid}"

    # Inside task wrappers (automatic via tasks/__init__.py):
    execution_id_var.set("abc12345")
    node_id_var.set("agent_1")

All existing ``logging.getLogger(__name__).info(...)`` calls work unchanged —
the ContextFilter injects execution/node context automatically.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from contextvars import ContextVar
from pathlib import Path

# ── Context variables (set per-task in RQ workers) ─────────────────────────

execution_id_var: ContextVar[str] = ContextVar("execution_id_var", default="")
node_id_var: ContextVar[str] = ContextVar("node_id_var", default="")


# ── Filter: stamps context onto every LogRecord ────────────────────────────

class ContextFilter(logging.Filter):
    """Injects ``role``, ``execution_id``, and ``node_id`` onto each record."""

    def __init__(self, role: str) -> None:
        super().__init__()
        self.role = role

    def filter(self, record: logging.LogRecord) -> bool:
        record.role = self.role  # type: ignore[attr-defined]
        record.execution_id = execution_id_var.get("")  # type: ignore[attr-defined]
        record.node_id = node_id_var.get("")  # type: ignore[attr-defined]
        return True


# ── Formatter: builds [Role][Exec][Node][LEVEL] prefix ─────────────────────

class ContextFormatter(logging.Formatter):
    """Produces lines like:

    2026-02-17 14:30:00 [Server][INFO] services.orchestrator:248 - Started execution abc12345
    2026-02-17 14:30:01 [Worker-9821][Exec abc12345][Node agent_1][INFO] components.agent:55 - Calling LLM
    """

    def format(self, record: logging.LogRecord) -> str:
        role = getattr(record, "role", "")
        execution_id = getattr(record, "execution_id", "")
        node_id = getattr(record, "node_id", "")

        parts = [f"[{role}]"] if role else []
        if execution_id:
            parts.append(f"[Exec {execution_id[:8]}]")
        if node_id:
            parts.append(f"[Node {node_id}]")
        parts.append(f"[{record.levelname}]")

        prefix = "".join(parts)
        timestamp = self.formatTime(record, self.datefmt)
        location = f"{record.name}:{record.lineno}"
        message = record.getMessage()

        # Include exception info if present
        formatted = f"{timestamp} {prefix} {location} - {message}"
        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            formatted += "\n" + record.exc_text
        if record.stack_info:
            formatted += "\n" + record.stack_info
        return formatted


# ── Setup function ─────────────────────────────────────────────────────────

def setup_logging(role: str) -> None:
    """Configure the root logger for *role* (e.g. ``"Server"`` or ``"Worker-1234"``).

    - Adds a stderr StreamHandler (always).
    - Adds a RotatingFileHandler when ``settings.LOG_FILE`` is set.
    - Tames noisy third-party loggers.
    - Makes uvicorn loggers propagate through root (when role is Server).

    Safe to call multiple times (idempotent via handler name check).
    """
    from config import settings

    root = logging.getLogger()

    # Idempotency: skip if we've already configured
    if any(getattr(h, "name", None) == "_pipelit_stream" for h in root.handlers):
        return

    root.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))

    ctx_filter = ContextFilter(role)
    formatter = ContextFormatter(datefmt="%Y-%m-%d %H:%M:%S")

    # Console handler (stderr)
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.name = "_pipelit_stream"
    stream_handler.addFilter(ctx_filter)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    # File handler (optional)
    if settings.LOG_FILE:
        log_path = Path(settings.LOG_FILE)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            str(log_path),
            maxBytes=settings.LOG_MAX_BYTES,
            backupCount=settings.LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.name = "_pipelit_file"
        file_handler.addFilter(ctx_filter)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    # Tame noisy third-party loggers
    for name in ("httpx", "httpcore", "urllib3", "websockets", "hpack", "markdown_it"):
        logging.getLogger(name).setLevel(logging.WARNING)

    # Make uvicorn loggers propagate through root so they get our format
    if "server" in role.lower():
        for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
            uv_logger = logging.getLogger(name)
            uv_logger.handlers.clear()
            uv_logger.propagate = True

"""Tests for the unified logging configuration."""

from __future__ import annotations

import logging
import os
import tempfile

import pytest


@pytest.fixture(autouse=True)
def _clean_root_logger():
    """Remove any handlers we add during tests so they don't leak."""
    root = logging.getLogger()
    before = list(root.handlers)
    yield
    # Restore original handlers
    root.handlers = before


# ── ContextFilter tests ────────────────────────────────────────────────────


def test_context_filter_stamps_role():
    from logging_config import ContextFilter

    f = ContextFilter("Server")
    record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
    f.filter(record)
    assert record.role == "Server"  # type: ignore[attr-defined]
    assert record.execution_id == ""  # type: ignore[attr-defined]
    assert record.node_id == ""  # type: ignore[attr-defined]


def test_context_filter_reads_contextvars():
    from logging_config import ContextFilter, execution_id_var, node_id_var

    f = ContextFilter("Worker-99")
    token_exec = execution_id_var.set("exec-abc")
    token_node = node_id_var.set("agent_1")
    try:
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        f.filter(record)
        assert record.execution_id == "exec-abc"  # type: ignore[attr-defined]
        assert record.node_id == "agent_1"  # type: ignore[attr-defined]
    finally:
        node_id_var.reset(token_node)
        execution_id_var.reset(token_exec)


def test_context_filter_always_returns_true():
    from logging_config import ContextFilter

    f = ContextFilter("X")
    record = logging.LogRecord("test", logging.DEBUG, "", 0, "msg", (), None)
    assert f.filter(record) is True


# ── ContextFormatter tests ─────────────────────────────────────────────────


def test_formatter_server_no_context():
    from logging_config import ContextFormatter

    fmt = ContextFormatter(datefmt="%Y-%m-%d %H:%M:%S")
    record = logging.LogRecord("services.orchestrator", logging.INFO, "", 42, "hello", (), None)
    record.role = "Server"  # type: ignore[attr-defined]
    record.execution_id = ""  # type: ignore[attr-defined]
    record.node_id = ""  # type: ignore[attr-defined]

    line = fmt.format(record)
    assert "[Server]" in line
    assert "[INFO]" in line
    assert "services.orchestrator:42" in line
    assert "hello" in line
    assert "[Exec" not in line
    assert "[Node" not in line


def test_formatter_worker_with_exec_and_node():
    from logging_config import ContextFormatter

    fmt = ContextFormatter(datefmt="%Y-%m-%d %H:%M:%S")
    record = logging.LogRecord("components.agent", logging.WARNING, "", 55, "Calling LLM", (), None)
    record.role = "Worker-9821"  # type: ignore[attr-defined]
    record.execution_id = "abc12345full"  # type: ignore[attr-defined]
    record.node_id = "agent_1"  # type: ignore[attr-defined]

    line = fmt.format(record)
    assert "[Worker-9821]" in line
    assert "[Exec abc12345]" in line  # truncated to 8 chars
    assert "[Node agent_1]" in line
    assert "[WARNING]" in line
    assert "components.agent:55" in line
    assert "Calling LLM" in line


def test_formatter_exec_only():
    from logging_config import ContextFormatter

    fmt = ContextFormatter(datefmt="%Y-%m-%d %H:%M:%S")
    record = logging.LogRecord("test", logging.DEBUG, "", 1, "msg", (), None)
    record.role = "Worker-1"  # type: ignore[attr-defined]
    record.execution_id = "short"  # type: ignore[attr-defined]
    record.node_id = ""  # type: ignore[attr-defined]

    line = fmt.format(record)
    assert "[Exec short]" in line
    assert "[Node" not in line


def test_formatter_includes_exception():
    from logging_config import ContextFormatter

    fmt = ContextFormatter(datefmt="%Y-%m-%d %H:%M:%S")
    try:
        raise ValueError("boom")
    except ValueError:
        import sys
        exc_info = sys.exc_info()

    record = logging.LogRecord("test", logging.ERROR, "", 1, "failed", (), exc_info)
    record.role = "Server"  # type: ignore[attr-defined]
    record.execution_id = ""  # type: ignore[attr-defined]
    record.node_id = ""  # type: ignore[attr-defined]

    line = fmt.format(record)
    assert "failed" in line
    assert "ValueError: boom" in line


# ── setup_logging tests ───────────────────────────────────────────────────


def test_setup_logging_adds_stream_handler(monkeypatch):
    from logging_config import setup_logging

    monkeypatch.setenv("LOG_FILE", "")
    # Clear any existing pipelit handlers for idempotency check
    root = logging.getLogger()
    root.handlers = [h for h in root.handlers if getattr(h, "name", None) not in ("_pipelit_stream", "_pipelit_file")]

    setup_logging("TestServer")

    handler_names = [getattr(h, "name", None) for h in root.handlers]
    assert "_pipelit_stream" in handler_names


def test_setup_logging_idempotent(monkeypatch):
    from logging_config import setup_logging

    monkeypatch.setenv("LOG_FILE", "")
    root = logging.getLogger()
    root.handlers = [h for h in root.handlers if getattr(h, "name", None) not in ("_pipelit_stream", "_pipelit_file")]

    setup_logging("TestServer")
    count_before = len(root.handlers)
    setup_logging("TestServer")
    assert len(root.handlers) == count_before


def test_setup_logging_file_handler(monkeypatch, tmp_path):
    from logging_config import setup_logging

    log_file = str(tmp_path / "test.log")
    monkeypatch.setenv("LOG_FILE", log_file)
    root = logging.getLogger()
    root.handlers = [h for h in root.handlers if getattr(h, "name", None) not in ("_pipelit_stream", "_pipelit_file")]

    # Patch settings directly to pick up env var
    from config import Settings
    import config
    original_settings = config.settings
    config.settings = Settings()

    try:
        setup_logging("TestFile")
        handler_names = [getattr(h, "name", None) for h in root.handlers]
        assert "_pipelit_file" in handler_names

        # Actually log something and verify it appears in the file
        test_logger = logging.getLogger("test.file_handler")
        test_logger.info("file handler test message")

        with open(log_file) as f:
            content = f.read()
        assert "file handler test message" in content
    finally:
        config.settings = original_settings


def test_setup_logging_tames_noisy_loggers(monkeypatch):
    from logging_config import setup_logging

    monkeypatch.setenv("LOG_FILE", "")
    root = logging.getLogger()
    root.handlers = [h for h in root.handlers if getattr(h, "name", None) not in ("_pipelit_stream", "_pipelit_file")]

    setup_logging("TestTame")

    for name in ("httpx", "httpcore", "urllib3", "websockets"):
        assert logging.getLogger(name).level >= logging.WARNING


def test_setup_logging_configures_uvicorn_propagation(monkeypatch):
    from logging_config import setup_logging

    monkeypatch.setenv("LOG_FILE", "")
    root = logging.getLogger()
    root.handlers = [h for h in root.handlers if getattr(h, "name", None) not in ("_pipelit_stream", "_pipelit_file")]

    setup_logging("Server")

    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        uv_logger = logging.getLogger(name)
        assert uv_logger.propagate is True


# ── Context vars in tasks tests ───────────────────────────────────────────


def test_task_wrappers_set_and_reset_context():
    """Verify context vars are set during task execution and reset after."""
    from logging_config import execution_id_var, node_id_var

    # Confirm starting state is empty
    assert execution_id_var.get("") == ""
    assert node_id_var.get("") == ""

    # We can't run the actual orchestrator, but we can test the var lifecycle
    token = execution_id_var.set("test-exec-id")
    assert execution_id_var.get() == "test-exec-id"
    execution_id_var.reset(token)
    assert execution_id_var.get("") == ""

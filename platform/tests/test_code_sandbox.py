"""Tests for code node sandboxing and code_execute removal."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

_platform_dir = str(Path(__file__).resolve().parent.parent)
if _platform_dir not in sys.path:
    sys.path.insert(0, _platform_dir)


def _make_node(component_type="code", extra_config=None, node_id="test_node_1", workflow_id=1):
    """Build a minimal node-like object for component factories."""
    config = SimpleNamespace(
        component_type=component_type,
        extra_config=extra_config or {},
        system_prompt="",
    )
    return SimpleNamespace(
        node_id=node_id,
        workflow_id=workflow_id,
        component_type=component_type,
        component_config=config,
    )


def _make_fake_execute(tmp_path, env=None):
    """Create a fake backend.execute that runs commands via subprocess in tmp_path."""
    def fake_execute(cmd, timeout=None):
        kwargs = dict(
            capture_output=True,
            text=True,
            timeout=timeout or 60,
            cwd=str(tmp_path),
        )
        if env is not None:
            kwargs["env"] = env
        result = subprocess.run(["bash", "-c", cmd], **kwargs)
        resp = MagicMock()
        resp.exit_code = result.returncode
        resp.output = (result.stdout or "") + (result.stderr or "")
        return resp
    return fake_execute


# ---------------------------------------------------------------------------
# code_execute removal verification
# ---------------------------------------------------------------------------


class TestCodeExecuteRemoved:
    def test_code_execute_not_in_registry(self):
        from components import COMPONENT_REGISTRY
        assert "code_execute" not in COMPONENT_REGISTRY

    def test_code_execute_not_in_node_types(self):
        from schemas.node_types import NODE_TYPE_REGISTRY
        assert "code_execute" not in NODE_TYPE_REGISTRY


# ---------------------------------------------------------------------------
# Code node subprocess execution
# ---------------------------------------------------------------------------


class TestCodeNodeSubprocess:
    def test_code_node_runs_in_subprocess(self, tmp_path):
        """Code output comes from subprocess, not in-process exec()."""
        code = "result = 2 + 2"
        node = _make_node(extra_config={"code": code, "language": "python"})

        mock_backend = MagicMock()
        mock_backend.cwd = tmp_path
        mock_backend.execute = _make_fake_execute(tmp_path)

        with patch("components.code._build_backend", return_value=mock_backend):
            from components.code import code_factory
            fn = code_factory(node)
            result = fn({"node_outputs": {}, "messages": []})

        assert result["output"] == "4"

    def test_code_node_cannot_access_server_env(self, tmp_path):
        """FIELD_ENCRYPTION_KEY should not be visible in the subprocess."""
        code = "import os; result = os.environ.get('FIELD_ENCRYPTION_KEY', 'NOT_FOUND')"
        node = _make_node(extra_config={"code": code, "language": "python"})

        mock_backend = MagicMock()
        mock_backend.cwd = tmp_path
        env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
        mock_backend.execute = _make_fake_execute(tmp_path, env=env)

        with patch("components.code._build_backend", return_value=mock_backend):
            from components.code import code_factory
            fn = code_factory(node)
            result = fn({"node_outputs": {}, "messages": []})

        assert result["output"] == "NOT_FOUND"

    def test_code_node_timeout(self, tmp_path):
        """Long-running code hits timeout."""
        code = "import time; time.sleep(30)"
        node = _make_node(extra_config={"code": code, "language": "python", "timeout": 2})

        mock_backend = MagicMock()
        mock_backend.cwd = tmp_path

        def fake_execute(cmd, timeout=None):
            raise subprocess.TimeoutExpired(cmd, timeout)

        # Actually simulate the timeout happening in _build_backend
        mock_backend.execute = fake_execute

        # Need to also handle the subprocess.TimeoutExpired being re-raised
        with patch("components.code._build_backend", return_value=mock_backend):
            from components.code import code_factory
            fn = code_factory(node)
            # The code node wraps TimeoutExpired only from subprocess.run path;
            # backend.execute raises it which gets caught by the except block
            with pytest.raises(Exception, match="timed out|TimeoutExpired"):
                fn({"node_outputs": {}, "messages": []})

    def test_code_node_state_access(self, tmp_path):
        """Code reads state/node_outputs via JSON input."""
        code = 'result = node_outputs.get("upstream", {}).get("value", "missing")'
        node = _make_node(extra_config={"code": code, "language": "python"})

        mock_backend = MagicMock()
        mock_backend.cwd = tmp_path
        mock_backend.execute = _make_fake_execute(tmp_path)

        with patch("components.code._build_backend", return_value=mock_backend):
            from components.code import code_factory
            fn = code_factory(node)
            result = fn({
                "node_outputs": {"upstream": {"value": "hello_from_upstream"}},
                "messages": [],
            })

        assert result["output"] == "hello_from_upstream"

    def test_code_node_error_handling(self, tmp_path):
        """Exception returns error, no server crash."""
        code = "raise ValueError('test error')"
        node = _make_node(extra_config={"code": code, "language": "python"})

        mock_backend = MagicMock()
        mock_backend.cwd = tmp_path
        mock_backend.execute = _make_fake_execute(tmp_path)

        with patch("components.code._build_backend", return_value=mock_backend):
            from components.code import code_factory
            fn = code_factory(node)
            with pytest.raises(RuntimeError, match="Code execution failed"):
                fn({"node_outputs": {}, "messages": []})

    def test_code_node_no_code_raises(self):
        """Empty code raises ValueError."""
        node = _make_node(extra_config={"code": "", "language": "python"})

        with patch("components.code._build_backend", return_value=MagicMock(cwd="/tmp")):
            from components.code import code_factory
            fn = code_factory(node)
            with pytest.raises(ValueError, match="No code provided"):
                fn({})

    def test_code_node_unsupported_language(self):
        """Non-python language raises ValueError."""
        node = _make_node(extra_config={"code": "echo hi", "language": "bash"})

        with patch("components.code._build_backend", return_value=MagicMock(cwd="/tmp")):
            from components.code import code_factory
            fn = code_factory(node)
            with pytest.raises(ValueError, match="not yet supported"):
                fn({})

    def test_code_node_stdout_capture(self, tmp_path):
        """print() output captured when no explicit result variable."""
        code = 'print("hello from print")'
        node = _make_node(extra_config={"code": code, "language": "python"})

        mock_backend = MagicMock()
        mock_backend.cwd = tmp_path
        mock_backend.execute = _make_fake_execute(tmp_path)

        with patch("components.code._build_backend", return_value=mock_backend):
            from components.code import code_factory
            fn = code_factory(node)
            result = fn({"node_outputs": {}, "messages": []})

        assert result["output"] == "hello from print"


# ---------------------------------------------------------------------------
# run_command sandbox integration
# ---------------------------------------------------------------------------


class TestRunCommandSandbox:
    def test_run_command_uses_sandbox(self):
        """When parent has workspace_id, sandbox backend is built."""
        node = _make_node("run_command", extra_config={})

        mock_backend = MagicMock()
        resp = MagicMock()
        resp.output = "sandbox_output"
        resp.exit_code = 0
        mock_backend.execute = MagicMock(return_value=resp)

        with patch("components.run_command._resolve_parent_workspace", return_value={"workspace_id": 1}), \
             patch("components._agent_shared._build_backend", return_value=mock_backend):
            from components.run_command import run_command_factory
            tool = run_command_factory(node)
            result = tool.invoke({"command": "echo test"})

        assert "sandbox_output" in result
        mock_backend.execute.assert_called_once()

    def test_run_command_no_workspace_returns_error(self):
        """When no workspace is configured, an error is returned (no subprocess fallback)."""
        node = _make_node("run_command", extra_config={})

        with patch("components.run_command._resolve_parent_workspace", return_value={}):
            from components.run_command import run_command_factory
            tool = run_command_factory(node)
            result = tool.invoke({"command": "echo test"})

        assert "No sandbox backend available" in result

    def test_run_command_backend_build_failure_returns_error(self):
        """When _build_backend raises, an error is returned (no subprocess fallback)."""
        node = _make_node("run_command", extra_config={})

        with patch("components.run_command._resolve_parent_workspace", return_value={"workspace_id": 1}), \
             patch("components._agent_shared._build_backend", side_effect=RuntimeError("boom")):
            from components.run_command import run_command_factory
            tool = run_command_factory(node)
            result = tool.invoke({"command": "echo test"})

        assert "No sandbox backend available" in result

    def test_run_command_sandbox_nonzero_exit(self):
        """Backend returning non-zero exit code includes [exit code: N]."""
        node = _make_node("run_command", extra_config={})

        mock_backend = MagicMock()
        resp = MagicMock()
        resp.output = "some error output"
        resp.exit_code = 1
        mock_backend.execute = MagicMock(return_value=resp)

        with patch("components.run_command._resolve_parent_workspace", return_value={"workspace_id": 1}), \
             patch("components._agent_shared._build_backend", return_value=mock_backend):
            from components.run_command import run_command_factory
            tool = run_command_factory(node)
            result = tool.invoke({"command": "false"})

        assert "[exit code: 1]" in result


# ---------------------------------------------------------------------------
# Code node subprocess fallback (backend=None)
# ---------------------------------------------------------------------------


class TestCodeNodeNoSandbox:
    """Tests that code node raises RuntimeError when no sandbox backend is available."""

    def test_code_node_no_sandbox_raises(self):
        """When _build_backend raises, code node raises RuntimeError (no subprocess fallback)."""
        code = "result = 2 + 2"
        node = _make_node(extra_config={"code": code, "language": "python"})

        with patch("components.code._build_backend", side_effect=RuntimeError("no sandbox")):
            from components.code import code_factory
            fn = code_factory(node)
            with pytest.raises(RuntimeError, match="No sandbox backend available"):
                fn({"node_outputs": {}, "messages": []})


# ---------------------------------------------------------------------------
# _safe_serialize edge cases
# ---------------------------------------------------------------------------


class TestSafeSerialize:
    """Tests for non-JSON-serializable fallback paths in _safe_serialize."""

    def test_non_serializable_dict_values(self):
        """Dict with non-serializable values falls back to str() per value."""
        from components.code import _safe_serialize
        result = _safe_serialize({"key": {1, 2, 3}})
        assert isinstance(result, dict)
        assert isinstance(result["key"], str)

    def test_non_serializable_custom_class(self):
        """Custom object falls back to str()."""
        class Custom:
            def __str__(self):
                return "custom_str"

        from components.code import _safe_serialize
        result = _safe_serialize(Custom())
        assert result == "custom_str"

    def test_non_serializable_list(self):
        """List with non-serializable items falls back per element."""
        from components.code import _safe_serialize
        result = _safe_serialize([{1, 2}, "ok"])
        assert result[1] == "ok"
        assert isinstance(result[0], str)

    def test_non_serializable_str_fails(self):
        """Object where str() also fails returns None."""
        class Broken:
            def __str__(self):
                raise RuntimeError("cannot stringify")

        from components.code import _safe_serialize
        result = _safe_serialize(Broken())
        assert result is None

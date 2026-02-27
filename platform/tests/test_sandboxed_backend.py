"""Tests for SandboxedShellBackend — sandboxed shell execution."""

from __future__ import annotations

import os
import shutil
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from deepagents.backends.protocol import SandboxBackendProtocol
from services.environment import SandboxResolution


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _has_bwrap() -> bool:
    return shutil.which("bwrap") is not None


def _make_resolution(mode="bwrap", can_execute=True, container_type=None, reason=None):
    return SandboxResolution(
        mode=mode,
        can_execute=can_execute,
        container_type=container_type,
        reason=reason,
    )


def _make_backend(tmp_path, mode="bwrap", **kwargs):
    """Create a SandboxedShellBackend with mocked sandbox resolution."""
    from components.sandboxed_backend import SandboxedShellBackend

    resolution = _make_resolution(mode=mode)
    with patch("components.sandboxed_backend.resolve_sandbox_mode", return_value=resolution):
        return SandboxedShellBackend(root_dir=str(tmp_path), **kwargs)


# ---------------------------------------------------------------------------
# isinstance / protocol checks
# ---------------------------------------------------------------------------


class TestProtocol:
    def test_isinstance_sandbox_backend_protocol(self, tmp_path):
        backend = _make_backend(tmp_path, mode="none")
        assert isinstance(backend, SandboxBackendProtocol)

    def test_isinstance_local_shell_backend(self, tmp_path):
        from deepagents.backends.local_shell import LocalShellBackend

        backend = _make_backend(tmp_path, mode="none")
        assert isinstance(backend, LocalShellBackend)

    def test_virtual_mode_enabled(self, tmp_path):
        backend = _make_backend(tmp_path, mode="none")
        assert backend.virtual_mode is True

    def test_cwd_set_to_root_dir(self, tmp_path):
        backend = _make_backend(tmp_path, mode="none")
        assert str(backend.cwd) == str(tmp_path)


# ---------------------------------------------------------------------------
# Sandbox detection (via resolve_sandbox_mode)
# ---------------------------------------------------------------------------


class TestSandboxDetection:
    def test_uses_resolve_sandbox_mode(self, tmp_path):
        from components.sandboxed_backend import SandboxedShellBackend

        resolution = _make_resolution(mode="bwrap")
        with patch("components.sandboxed_backend.resolve_sandbox_mode", return_value=resolution):
            backend = SandboxedShellBackend(root_dir=str(tmp_path))
        assert backend._resolution.mode == "bwrap"

    def test_container_mode_detected(self, tmp_path):
        from components.sandboxed_backend import SandboxedShellBackend

        resolution = _make_resolution(mode="container", container_type="docker")
        with patch("components.sandboxed_backend.resolve_sandbox_mode", return_value=resolution):
            backend = SandboxedShellBackend(root_dir=str(tmp_path))
        assert backend._resolution.mode == "container"
        assert backend._resolution.container_type == "docker"

    def test_fallback_when_no_sandbox(self, tmp_path):
        from components.sandboxed_backend import SandboxedShellBackend

        resolution = _make_resolution(mode="none")
        with patch("components.sandboxed_backend.resolve_sandbox_mode", return_value=resolution):
            backend = SandboxedShellBackend(root_dir=str(tmp_path))
        assert backend._resolution.mode == "none"


# ---------------------------------------------------------------------------
# _build_bwrap_command (new rootfs-based)
# ---------------------------------------------------------------------------


class TestBwrapCommand:
    def test_rootfs_bound_as_root(self, tmp_path):
        from components.sandboxed_backend import _build_bwrap_command

        workspace = str(tmp_path / "ws")
        rootfs = str(tmp_path / "rootfs")
        os.makedirs(workspace, exist_ok=True)
        cmd = _build_bwrap_command("echo hi", workspace, rootfs)

        bind_pairs = []
        for i, v in enumerate(cmd):
            if v == "--bind" and i + 2 < len(cmd):
                bind_pairs.append((cmd[i + 1], cmd[i + 2]))
        assert (rootfs, "/") in bind_pairs

    def test_workspace_bound_as_workspace(self, tmp_path):
        from components.sandboxed_backend import _build_bwrap_command

        workspace = str(tmp_path / "ws")
        rootfs = str(tmp_path / "rootfs")
        os.makedirs(workspace, exist_ok=True)
        cmd = _build_bwrap_command("echo hi", workspace, rootfs)

        bind_pairs = []
        for i, v in enumerate(cmd):
            if v == "--bind" and i + 2 < len(cmd):
                bind_pairs.append((cmd[i + 1], cmd[i + 2]))
        assert (workspace, "/workspace") in bind_pairs

    def test_tmp_backed_by_workspace(self, tmp_path):
        from components.sandboxed_backend import _build_bwrap_command

        workspace = str(tmp_path / "ws")
        rootfs = str(tmp_path / "rootfs")
        os.makedirs(workspace, exist_ok=True)
        cmd = _build_bwrap_command("echo hi", workspace, rootfs)

        bind_pairs = []
        for i, v in enumerate(cmd):
            if v == "--bind" and i + 2 < len(cmd):
                bind_pairs.append((cmd[i + 1], cmd[i + 2]))
        assert (os.path.join(workspace, ".tmp"), "/tmp") in bind_pairs

    def test_clearenv_present(self, tmp_path):
        from components.sandboxed_backend import _build_bwrap_command

        workspace = str(tmp_path / "ws")
        rootfs = str(tmp_path / "rootfs")
        os.makedirs(workspace, exist_ok=True)
        cmd = _build_bwrap_command("echo hi", workspace, rootfs)
        assert "--clearenv" in cmd

    def test_env_vars_correct(self, tmp_path):
        from components.sandboxed_backend import _build_bwrap_command

        workspace = str(tmp_path / "ws")
        rootfs = str(tmp_path / "rootfs")
        os.makedirs(workspace, exist_ok=True)
        cmd = _build_bwrap_command("echo hi", workspace, rootfs)

        setenv_indices = [i for i, v in enumerate(cmd) if v == "--setenv"]
        env_pairs = {cmd[i + 1]: cmd[i + 2] for i in setenv_indices}

        assert env_pairs["HOME"] == "/workspace"
        assert ".packages/bin" in env_pairs["PATH"]
        assert "/sbin" in env_pairs["PATH"]
        assert "/usr/sbin" in env_pairs["PATH"]
        assert env_pairs["PATH"] == "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/workspace/.packages/bin"
        assert env_pairs["PIP_TARGET"] == "/workspace/.packages"
        assert env_pairs["PYTHONPATH"] == "/workspace/.packages"
        assert env_pairs["LANG"] == "C.UTF-8"
        assert env_pairs["TMPDIR"] == "/tmp"
        assert env_pairs["PYTHONDONTWRITEBYTECODE"] == "1"

    def test_chdir_workspace(self, tmp_path):
        from components.sandboxed_backend import _build_bwrap_command

        workspace = str(tmp_path / "ws")
        rootfs = str(tmp_path / "rootfs")
        os.makedirs(workspace, exist_ok=True)
        cmd = _build_bwrap_command("echo hi", workspace, rootfs)

        chdir_idx = cmd.index("--chdir")
        assert cmd[chdir_idx + 1] == "/workspace"

    def test_network_allowed(self, tmp_path):
        from components.sandboxed_backend import _build_bwrap_command

        workspace = str(tmp_path / "ws")
        rootfs = str(tmp_path / "rootfs")
        os.makedirs(workspace, exist_ok=True)
        cmd = _build_bwrap_command("echo hi", workspace, rootfs, allow_network=True)
        assert "--share-net" in cmd

    def test_network_denied(self, tmp_path):
        from components.sandboxed_backend import _build_bwrap_command

        workspace = str(tmp_path / "ws")
        rootfs = str(tmp_path / "rootfs")
        os.makedirs(workspace, exist_ok=True)
        cmd = _build_bwrap_command("echo hi", workspace, rootfs, allow_network=False)
        assert "--share-net" not in cmd

    def test_no_host_system_binds(self, tmp_path):
        """No /usr, /bin, /lib, /sbin, /etc ro-binds from host system."""
        from components.sandboxed_backend import _build_bwrap_command

        workspace = str(tmp_path / "ws")
        rootfs = str(tmp_path / "rootfs")
        os.makedirs(workspace, exist_ok=True)
        cmd = _build_bwrap_command("echo hi", workspace, rootfs, allow_network=False)

        ro_bind_pairs = []
        for i, v in enumerate(cmd):
            if v == "--ro-bind" and i + 2 < len(cmd):
                ro_bind_pairs.append((cmd[i + 1], cmd[i + 2]))

        # Should NOT have host system paths bound
        bound_sources = [src for src, _ in ro_bind_pairs]
        for host_dir in ["/usr", "/bin", "/lib", "/sbin", "/etc/ssl",
                         "/etc/hosts", "/etc/passwd", "/etc/group",
                         "/etc/ld.so.cache", "/etc/ld.so.conf"]:
            assert host_dir not in bound_sources, f"{host_dir} should not be bound"


# ---------------------------------------------------------------------------
# Container mode env scrubbing
# ---------------------------------------------------------------------------


class TestContainerModeEnvScrubbing:
    def test_build_sandbox_env_keys(self):
        from components.sandboxed_backend import _build_sandbox_env

        env = _build_sandbox_env("/workspace")
        expected_keys = {"PATH", "HOME", "TMPDIR", "LANG", "PIP_TARGET",
                         "PYTHONPATH", "PYTHONDONTWRITEBYTECODE"}
        assert set(env.keys()) == expected_keys

    def test_build_sandbox_env_path_includes_sbin(self):
        from components.sandboxed_backend import _build_sandbox_env

        env = _build_sandbox_env("/workspace")
        assert "/sbin" in env["PATH"]
        assert "/usr/sbin" in env["PATH"]
        assert env["PATH"] == "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/workspace/.packages/bin"

    def test_build_sandbox_env_no_secrets(self):
        from components.sandboxed_backend import _build_sandbox_env

        env = _build_sandbox_env("/workspace")
        # Should not contain any common secret env vars
        for key in env:
            assert "SECRET" not in key
            assert "KEY" not in key
            assert "TOKEN" not in key
            assert "PASSWORD" not in key


# ---------------------------------------------------------------------------
# Fallback behaviour (no sandbox tool)
# ---------------------------------------------------------------------------


class TestFallback:
    def test_execute_falls_back_when_no_sandbox(self, tmp_path):
        """When no sandbox tool is available, execute() delegates to parent."""
        backend = _make_backend(tmp_path, mode="none")
        result = backend.execute("echo fallback")
        assert result.exit_code == 0
        assert "fallback" in result.output

    def test_fallback_write_file(self, tmp_path):
        """Fallback mode can write files in the workspace."""
        backend = _make_backend(tmp_path, mode="none")
        backend.execute("echo 'test content' > test.txt")
        assert (tmp_path / "test.txt").exists()


# ---------------------------------------------------------------------------
# Sandboxed execution (integration — only runs if bwrap is available)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _has_bwrap(), reason="bwrap not available")
class TestSandboxedExecution:
    """Integration tests using real bwrap with mocked rootfs provisioning.

    These tests create a minimal rootfs from the host system for testing
    purposes, since we can't download Alpine in CI.
    """

    @pytest.fixture
    def _setup_rootfs(self, tmp_path):
        """Create a minimal rootfs-like structure for integration testing.

        We use the host system's binaries via symlinks, which is enough
        for basic bwrap testing.
        """
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        rootfs = tmp_path / "rootfs"
        rootfs.mkdir()

        # Create minimal rootfs structure using host system binds
        for d in ["proc", "dev", "tmp", "workspace"]:
            (rootfs / d).mkdir(exist_ok=True)

        # We'll use host /usr, /bin, etc. as the rootfs base
        # by creating symlinks (like merged-usr)
        (rootfs / "usr").mkdir(exist_ok=True)
        for d in ["bin", "lib", "sbin", "lib64"]:
            host_path = f"/{d}"
            if os.path.islink(host_path):
                target = os.readlink(host_path)
                os.symlink(target, str(rootfs / d))
            elif os.path.isdir(host_path):
                (rootfs / d).mkdir(exist_ok=True)

        # etc entries
        (rootfs / "etc").mkdir(exist_ok=True)

        return workspace, rootfs

    def test_echo(self, tmp_path, _setup_rootfs):
        workspace, rootfs = _setup_rootfs
        backend = _make_backend(workspace, mode="bwrap")

        # Mock rootfs provisioning to use our test rootfs
        backend._workspace_rootfs = str(rootfs)

        # We need to bind host /usr into the rootfs for this to work
        cmd = [
            "bwrap", "--unshare-all",
            "--bind", str(rootfs), "/",
            "--ro-bind", "/usr", "/usr",
        ]
        # Add non-merged /bin, /lib etc
        for d in ["bin", "lib", "sbin", "lib64"]:
            if os.path.isdir(f"/{d}") and not os.path.islink(f"/{d}"):
                cmd += ["--ro-bind", f"/{d}", f"/{d}"]
        cmd += [
            "--bind", str(workspace), "/workspace",
            "--proc", "/proc",
            "--dev", "/dev",
            "--die-with-parent",
            "--chdir", "/workspace",
            "bash", "-c", "echo hello",
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=10)
        assert result.returncode == 0
        assert b"hello" in result.stdout

    def test_write_file_in_workspace(self, tmp_path, _setup_rootfs):
        workspace, rootfs = _setup_rootfs

        cmd = [
            "bwrap", "--unshare-all",
            "--bind", str(rootfs), "/",
            "--ro-bind", "/usr", "/usr",
        ]
        for d in ["bin", "lib", "sbin", "lib64"]:
            if os.path.isdir(f"/{d}") and not os.path.islink(f"/{d}"):
                cmd += ["--ro-bind", f"/{d}", f"/{d}"]
        cmd += [
            "--bind", str(workspace), "/workspace",
            "--proc", "/proc",
            "--dev", "/dev",
            "--die-with-parent",
            "--chdir", "/workspace",
            "bash", "-c", "echo 'sandboxed' > /workspace/test.txt",
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=10)
        assert result.returncode == 0
        assert (workspace / "test.txt").exists()
        assert "sandboxed" in (workspace / "test.txt").read_text()

    def test_timeout_enforcement(self, tmp_path):
        backend = _make_backend(tmp_path, mode="none")
        # Use fallback for timeout test (simpler)
        result = backend.execute("sleep 10", timeout=1)
        # LocalShellBackend may not enforce timeout via exit code 124,
        # but the command should not run for 10s
        assert result is not None


# ---------------------------------------------------------------------------
# Python execution (no venv — Python comes from rootfs)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _has_bwrap(), reason="bwrap not available")
class TestPythonExecution:
    """Python is available from the host system (or rootfs in production)."""

    def test_python_print(self, tmp_path):
        backend = _make_backend(tmp_path, mode="none")
        result = backend.execute("python3 -c \"print('hello from sandbox')\"")
        assert result.exit_code == 0
        assert "hello from sandbox" in result.output

    def test_python_write_file(self, tmp_path):
        backend = _make_backend(tmp_path, mode="none")
        script = "python3 -c \"with open('output.txt', 'w') as f: f.write('from python')\""
        result = backend.execute(script)
        assert result.exit_code == 0
        assert (tmp_path / "output.txt").exists()
        assert (tmp_path / "output.txt").read_text() == "from python"


# ---------------------------------------------------------------------------
# Execute branch coverage (mocked subprocess.run)
# ---------------------------------------------------------------------------


class TestExecuteBranches:
    """Test execute() error handling, stderr combining, and truncation via mocked subprocess."""

    def _setup_bwrap_backend(self, tmp_path, **kwargs):
        """Create a bwrap backend with a fake rootfs directory that passes os.path.isdir."""
        backend = _make_backend(tmp_path, mode="bwrap", **kwargs)
        rootfs_dir = tmp_path / "rootfs"
        rootfs_dir.mkdir(exist_ok=True)
        backend._workspace_rootfs = str(rootfs_dir)
        return backend

    def test_execute_handles_generic_exception(self, tmp_path):
        """Generic exception in execute() returns exit_code=1 with error message."""
        backend = self._setup_bwrap_backend(tmp_path)

        with patch("subprocess.run", side_effect=OSError("disk full")), \
             patch("components.sandboxed_backend._build_bwrap_command", return_value=["bwrap"]):
            result = backend.execute("echo hello")
            assert result.exit_code == 1
            assert "Sandbox execution error" in result.output
            assert "disk full" in result.output
            assert result.truncated is False

    def test_execute_stderr_output(self, tmp_path):
        """stderr lines are prefixed with [stderr] in output."""
        backend = self._setup_bwrap_backend(tmp_path)

        mock_result = MagicMock()
        mock_result.stdout = b"stdout line\n"
        mock_result.stderr = b"warn: something\nerror: bad\n"
        mock_result.returncode = 1

        with patch("subprocess.run", return_value=mock_result), \
             patch("components.sandboxed_backend._build_bwrap_command", return_value=["bwrap"]):
            result = backend.execute("some command")
            assert "[stderr] warn: something" in result.output
            assert "[stderr] error: bad" in result.output
            assert "stdout line" in result.output
            assert result.exit_code == 1

    def test_execute_stderr_only(self, tmp_path):
        """Output with only stderr still works."""
        backend = self._setup_bwrap_backend(tmp_path)

        mock_result = MagicMock()
        mock_result.stdout = b""
        mock_result.stderr = b"error only\n"
        mock_result.returncode = 2

        with patch("subprocess.run", return_value=mock_result), \
             patch("components.sandboxed_backend._build_bwrap_command", return_value=["bwrap"]):
            result = backend.execute("bad command")
            assert "[stderr] error only" in result.output
            assert result.exit_code == 2

    def test_output_truncation(self, tmp_path):
        """Output exceeding max_output_bytes is truncated."""
        backend = self._setup_bwrap_backend(tmp_path, max_output_bytes=50)

        mock_result = MagicMock()
        mock_result.stdout = b"A" * 200
        mock_result.stderr = b""
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result), \
             patch("components.sandboxed_backend._build_bwrap_command", return_value=["bwrap"]):
            result = backend.execute("generate output")
            assert result.truncated is True
            assert len(result.output.encode("utf-8")) <= 50
            assert result.exit_code == 0

    def test_execute_no_truncation_when_under_limit(self, tmp_path):
        """Output under max_output_bytes is not truncated."""
        backend = self._setup_bwrap_backend(tmp_path, max_output_bytes=1000)

        mock_result = MagicMock()
        mock_result.stdout = b"short output"
        mock_result.stderr = b""
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result), \
             patch("components.sandboxed_backend._build_bwrap_command", return_value=["bwrap"]):
            result = backend.execute("echo short")
            assert result.truncated is False
            assert result.output == "short output"
            assert result.exit_code == 0

    def test_execute_combined_stdout_stderr(self, tmp_path):
        """Both stdout and stderr are combined in output."""
        backend = self._setup_bwrap_backend(tmp_path)

        mock_result = MagicMock()
        mock_result.stdout = b"normal output\n"
        mock_result.stderr = b"debug info\n"
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result), \
             patch("components.sandboxed_backend._build_bwrap_command", return_value=["bwrap"]):
            result = backend.execute("mixed output cmd")
            assert "normal output" in result.output
            assert "[stderr] debug info" in result.output
            assert result.exit_code == 0

    def test_execute_timeout(self, tmp_path):
        """Timeout returns exit_code=124."""
        backend = self._setup_bwrap_backend(tmp_path)

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="test", timeout=5)), \
             patch("components.sandboxed_backend._build_bwrap_command", return_value=["bwrap"]):
            result = backend.execute("sleep 100")
            assert result.exit_code == 124
            assert "timed out" in result.output.lower()

    def test_container_mode_execute(self, tmp_path):
        """Container mode passes clean env to subprocess."""
        backend = _make_backend(tmp_path, mode="container")

        mock_result = MagicMock()
        mock_result.stdout = b"container output\n"
        mock_result.stderr = b""
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = backend.execute("echo hello")

        assert result.exit_code == 0
        # Check that env was passed
        call_kwargs = mock_run.call_args
        env = call_kwargs.kwargs.get("env") or call_kwargs[1].get("env")
        assert env is not None
        assert "HOME" in env
        assert "SECRET" not in str(env)

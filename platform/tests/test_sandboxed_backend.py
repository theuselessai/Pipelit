"""Tests for SandboxedShellBackend — sandboxed shell execution."""

from __future__ import annotations

import os
import shutil
from unittest.mock import patch

import pytest

from deepagents.backends.protocol import SandboxBackendProtocol


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _has_bwrap() -> bool:
    return shutil.which("bwrap") is not None


def _has_sandbox() -> bool:
    return _has_bwrap()


# ---------------------------------------------------------------------------
# isinstance / protocol checks
# ---------------------------------------------------------------------------


class TestProtocol:
    def test_isinstance_sandbox_backend_protocol(self, tmp_path):
        from components.sandboxed_backend import SandboxedShellBackend

        backend = SandboxedShellBackend(root_dir=str(tmp_path))
        assert isinstance(backend, SandboxBackendProtocol)

    def test_isinstance_local_shell_backend(self, tmp_path):
        from deepagents.backends.local_shell import LocalShellBackend
        from components.sandboxed_backend import SandboxedShellBackend

        backend = SandboxedShellBackend(root_dir=str(tmp_path))
        assert isinstance(backend, LocalShellBackend)

    def test_virtual_mode_enabled(self, tmp_path):
        from components.sandboxed_backend import SandboxedShellBackend

        backend = SandboxedShellBackend(root_dir=str(tmp_path))
        assert backend.virtual_mode is True

    def test_cwd_set_to_root_dir(self, tmp_path):
        from components.sandboxed_backend import SandboxedShellBackend

        backend = SandboxedShellBackend(root_dir=str(tmp_path))
        assert str(backend.cwd) == str(tmp_path)


# ---------------------------------------------------------------------------
# Sandbox detection
# ---------------------------------------------------------------------------


class TestSandboxDetection:
    def test_detects_bwrap(self, tmp_path):
        with patch("components.sandboxed_backend.shutil.which") as mock_which:
            mock_which.side_effect = lambda cmd: "/usr/bin/bwrap" if cmd == "bwrap" else None
            from components.sandboxed_backend import SandboxedShellBackend

            backend = SandboxedShellBackend(root_dir=str(tmp_path))
            assert backend._sandbox_tool == "bwrap"

    def test_fallback_when_no_sandbox(self, tmp_path):
        with patch("components.sandboxed_backend._detect_sandbox", return_value=None):
            from components.sandboxed_backend import SandboxedShellBackend

            backend = SandboxedShellBackend(root_dir=str(tmp_path))
            assert backend._sandbox_tool is None


# ---------------------------------------------------------------------------
# _prepare_sandbox_root
# ---------------------------------------------------------------------------


class TestPrepareSandboxRoot:
    def test_creates_mount_points(self, tmp_path):
        from components.sandboxed_backend import _prepare_sandbox_root

        workspace = str(tmp_path / "ws")
        os.makedirs(workspace)
        _prepare_sandbox_root(workspace)

        assert os.path.isdir(os.path.join(workspace, "usr"))
        assert os.path.isdir(os.path.join(workspace, "etc"))
        assert os.path.isdir(os.path.join(workspace, "proc"))
        assert os.path.isdir(os.path.join(workspace, "dev"))
        assert os.path.isdir(os.path.join(workspace, "tmp"))

    def test_creates_merged_usr_symlinks(self, tmp_path):
        from components.sandboxed_backend import _prepare_sandbox_root

        workspace = str(tmp_path / "ws")
        os.makedirs(workspace)
        _prepare_sandbox_root(workspace)

        # On merged-usr systems (Debian/Ubuntu), /bin is a symlink to usr/bin
        for dir_name in ["bin", "lib", "sbin"]:
            host_path = f"/{dir_name}"
            ws_path = os.path.join(workspace, dir_name)
            if os.path.islink(host_path):
                assert os.path.islink(ws_path), f"{ws_path} should be a symlink"
                assert os.readlink(ws_path) == os.readlink(host_path)
            elif os.path.isdir(host_path):
                assert os.path.isdir(ws_path), f"{ws_path} should be a directory"

    def test_creates_etc_entries(self, tmp_path):
        from components.sandboxed_backend import _prepare_sandbox_root

        workspace = str(tmp_path / "ws")
        os.makedirs(workspace)
        _prepare_sandbox_root(workspace)

        etc_ws = os.path.join(workspace, "etc")
        # /etc/ssl is a directory on most systems
        if os.path.isdir("/etc/ssl"):
            assert os.path.isdir(os.path.join(etc_ws, "ssl"))
        # /etc/resolv.conf is a file
        if os.path.exists("/etc/resolv.conf"):
            assert os.path.exists(os.path.join(etc_ws, "resolv.conf"))

    def test_idempotent(self, tmp_path):
        from components.sandboxed_backend import _prepare_sandbox_root

        workspace = str(tmp_path / "ws")
        os.makedirs(workspace)
        _prepare_sandbox_root(workspace)
        # Running again should not raise
        _prepare_sandbox_root(workspace)


# ---------------------------------------------------------------------------
# Command building
# ---------------------------------------------------------------------------


class TestBwrapCommand:
    def test_build_bwrap_command_basic(self, tmp_path):
        from components.sandboxed_backend import _build_bwrap_command

        workspace = str(tmp_path)
        cmd = _build_bwrap_command("echo hello", workspace)

        assert cmd[0] == "bwrap"
        assert "--unshare-all" in cmd
        assert "--die-with-parent" in cmd
        # The actual command is at the end
        assert cmd[-1] == "echo hello"
        assert cmd[-2] == "-c"
        assert cmd[-3] == "bash"

        # Workspace is bound as root
        bind_pairs = []
        for i, v in enumerate(cmd):
            if v == "--bind" and i + 2 < len(cmd):
                bind_pairs.append((cmd[i + 1], cmd[i + 2]))
        assert (workspace, "/") in bind_pairs

        # --chdir /
        chdir_idx = cmd.index("--chdir")
        assert cmd[chdir_idx + 1] == "/"

        # No --tmpfs (workspace IS the root)
        assert "--tmpfs" not in cmd

    def test_build_bwrap_uses_root_bind(self, tmp_path):
        from components.sandboxed_backend import _build_bwrap_command

        workspace = str(tmp_path / "ws")
        os.makedirs(workspace)
        cmd = _build_bwrap_command("echo hi", workspace)

        bind_pairs = []
        for i, v in enumerate(cmd):
            if v == "--bind" and i + 2 < len(cmd):
                bind_pairs.append((cmd[i + 1], cmd[i + 2]))
        assert (workspace, "/") in bind_pairs

        # Mount points should have been created by _prepare_sandbox_root
        assert os.path.isdir(os.path.join(workspace, "usr"))
        assert os.path.isdir(os.path.join(workspace, "tmp"))

    def test_build_bwrap_command_with_network(self, tmp_path):
        from components.sandboxed_backend import _build_bwrap_command

        workspace = str(tmp_path)
        cmd = _build_bwrap_command("curl example.com", workspace, allow_network=True)
        assert "--share-net" in cmd

    def test_build_bwrap_command_without_network(self, tmp_path):
        from components.sandboxed_backend import _build_bwrap_command

        workspace = str(tmp_path)
        cmd = _build_bwrap_command("echo hi", workspace, allow_network=False)
        assert "--share-net" not in cmd

    def test_build_bwrap_command_extra_ro_binds(self, tmp_path):
        from components.sandboxed_backend import _build_bwrap_command

        workspace = str(tmp_path)
        skill_dir = str(tmp_path / "skills")
        os.makedirs(skill_dir, exist_ok=True)
        cmd = _build_bwrap_command("ls", workspace, extra_ro_binds=[skill_dir])
        # Should have --ro-bind for skill dir
        ro_bind_indices = [i for i, v in enumerate(cmd) if v == "--ro-bind"]
        bound_paths = [cmd[i + 1] for i in ro_bind_indices]
        assert skill_dir in bound_paths

    def test_build_bwrap_sets_env(self, tmp_path):
        from components.sandboxed_backend import _build_bwrap_command

        workspace = str(tmp_path)
        cmd = _build_bwrap_command("echo hi", workspace)

        # Check HOME is set to /
        setenv_indices = [i for i, v in enumerate(cmd) if v == "--setenv"]
        env_pairs = {cmd[i + 1]: cmd[i + 2] for i in setenv_indices}
        assert env_pairs.get("HOME") == "/"
        assert env_pairs.get("TMPDIR") == "/tmp"
        assert env_pairs.get("PATH", "").startswith("/.venv/bin:")


# ---------------------------------------------------------------------------
# Fallback behaviour (no sandbox tool)
# ---------------------------------------------------------------------------


class TestFallback:
    def test_execute_falls_back_when_no_sandbox(self, tmp_path):
        """When no sandbox tool is available, execute() delegates to parent."""
        from components.sandboxed_backend import SandboxedShellBackend

        with patch("components.sandboxed_backend._detect_sandbox", return_value=None):
            backend = SandboxedShellBackend(root_dir=str(tmp_path))

        result = backend.execute("echo fallback")
        assert result.exit_code == 0
        assert "fallback" in result.output

    def test_fallback_write_file(self, tmp_path):
        """Fallback mode can write files in the workspace."""
        from components.sandboxed_backend import SandboxedShellBackend

        with patch("components.sandboxed_backend._detect_sandbox", return_value=None):
            backend = SandboxedShellBackend(root_dir=str(tmp_path))

        backend.execute("echo 'test content' > test.txt")
        assert (tmp_path / "test.txt").exists()


# ---------------------------------------------------------------------------
# Sandboxed execution (integration — only runs if bwrap is available)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _has_bwrap(), reason="bwrap not available")
class TestSandboxedExecution:
    def test_echo(self, tmp_path):
        from components.sandboxed_backend import SandboxedShellBackend

        backend = SandboxedShellBackend(root_dir=str(tmp_path))
        result = backend.execute("echo hello")
        assert result.exit_code == 0
        assert "hello" in result.output

    def test_write_file_in_workspace(self, tmp_path):
        from components.sandboxed_backend import SandboxedShellBackend

        backend = SandboxedShellBackend(root_dir=str(tmp_path))
        result = backend.execute("echo 'sandboxed' > /test.txt")
        assert result.exit_code == 0
        assert (tmp_path / "test.txt").exists()
        assert "sandboxed" in (tmp_path / "test.txt").read_text()

    def test_read_file_in_workspace(self, tmp_path):
        from components.sandboxed_backend import SandboxedShellBackend

        (tmp_path / "input.txt").write_text("workspace data")
        backend = SandboxedShellBackend(root_dir=str(tmp_path))
        result = backend.execute("cat /input.txt")
        assert result.exit_code == 0
        assert "workspace data" in result.output

    def test_cannot_read_outside_workspace(self, tmp_path):
        from components.sandboxed_backend import SandboxedShellBackend

        backend = SandboxedShellBackend(root_dir=str(tmp_path))
        # /etc/shadow is bound read-only, but real /root/.bashrc is not visible
        result = backend.execute("cat /root/.bashrc 2>&1 || echo 'DENIED'")
        assert result.exit_code != 0 or "DENIED" in result.output or "No such file" in result.output

    def test_write_to_arbitrary_path_persists_in_workspace(self, tmp_path):
        """Writes to /root/evil inside sandbox persist as workspace/root/evil."""
        from components.sandboxed_backend import SandboxedShellBackend

        backend = SandboxedShellBackend(root_dir=str(tmp_path))
        result = backend.execute("mkdir -p /root && echo 'captured' > /root/evil")
        assert result.exit_code == 0
        # File should persist in workspace
        assert (tmp_path / "root" / "evil").exists()
        assert "captured" in (tmp_path / "root" / "evil").read_text()

    def test_cannot_see_real_home_dir(self, tmp_path):
        from components.sandboxed_backend import SandboxedShellBackend

        backend = SandboxedShellBackend(root_dir=str(tmp_path))
        # Real user's home files should not be visible
        real_home = os.path.expanduser("~")
        home_user = os.path.basename(real_home)
        result = backend.execute(f"ls /home/{home_user}/.ssh 2>&1 || echo 'DENIED'")
        assert result.exit_code != 0 or "DENIED" in result.output or "No such file" in result.output

    def test_timeout_enforcement(self, tmp_path):
        from components.sandboxed_backend import SandboxedShellBackend

        backend = SandboxedShellBackend(root_dir=str(tmp_path))
        result = backend.execute("sleep 10", timeout=1)
        assert result.exit_code == 124
        assert "timed out" in result.output.lower()

    def test_exit_code_propagated(self, tmp_path):
        from components.sandboxed_backend import SandboxedShellBackend

        backend = SandboxedShellBackend(root_dir=str(tmp_path))
        result = backend.execute("exit 42")
        assert result.exit_code == 42

    def test_tmp_files_persist_in_workspace(self, tmp_path):
        """Files written to /tmp inside the sandbox persist in <workspace>/tmp."""
        from components.sandboxed_backend import SandboxedShellBackend

        backend = SandboxedShellBackend(root_dir=str(tmp_path))
        result = backend.execute("echo 'persistent' > /tmp/test.txt")
        assert result.exit_code == 0
        persisted = tmp_path / "tmp" / "test.txt"
        assert persisted.exists()
        assert "persistent" in persisted.read_text()

    def test_workspace_tmp_created_automatically(self, tmp_path):
        """The workspace/tmp directory is created automatically by _prepare_sandbox_root."""
        from components.sandboxed_backend import SandboxedShellBackend

        workspace = tmp_path / "ws"
        workspace.mkdir()
        assert not (workspace / "tmp").exists()
        backend = SandboxedShellBackend(root_dir=str(workspace))
        backend.execute("echo hi")
        assert (workspace / "tmp").is_dir()

    def test_arbitrary_path_write_persists(self, tmp_path):
        """Write to /opt/output/result.txt persists as workspace/opt/output/result.txt."""
        from components.sandboxed_backend import SandboxedShellBackend

        backend = SandboxedShellBackend(root_dir=str(tmp_path))
        result = backend.execute("mkdir -p /opt/output && echo 'result data' > /opt/output/result.txt")
        assert result.exit_code == 0
        persisted = tmp_path / "opt" / "output" / "result.txt"
        assert persisted.exists()
        assert "result data" in persisted.read_text()

    def test_home_dir_write_persists(self, tmp_path):
        """Write to /home/user/file.pdf persists as workspace/home/user/file.pdf."""
        from components.sandboxed_backend import SandboxedShellBackend

        backend = SandboxedShellBackend(root_dir=str(tmp_path))
        result = backend.execute("mkdir -p /home/user && echo 'pdf content' > /home/user/file.pdf")
        assert result.exit_code == 0
        persisted = tmp_path / "home" / "user" / "file.pdf"
        assert persisted.exists()
        assert "pdf content" in persisted.read_text()


# ---------------------------------------------------------------------------
# Python execution with workspace venv
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _has_bwrap(), reason="bwrap not available")
class TestPythonExecution:
    @pytest.fixture(autouse=True)
    def _setup_venv(self, tmp_path):
        """Create a minimal venv in the workspace for testing."""
        import subprocess
        subprocess.run(
            ["python3", "-m", "venv", str(tmp_path / ".venv")],
            check=True,
            capture_output=True,
            timeout=60,
        )

    def test_python_print(self, tmp_path):
        from components.sandboxed_backend import SandboxedShellBackend

        backend = SandboxedShellBackend(root_dir=str(tmp_path))
        result = backend.execute("python3 -c \"print('hello from sandbox')\"")
        assert result.exit_code == 0
        assert "hello from sandbox" in result.output

    def test_python_write_file(self, tmp_path):
        from components.sandboxed_backend import SandboxedShellBackend

        backend = SandboxedShellBackend(root_dir=str(tmp_path))
        script = "python3 -c \"with open('/output.txt', 'w') as f: f.write('from python')\""
        result = backend.execute(script)
        assert result.exit_code == 0
        assert (tmp_path / "output.txt").exists()
        assert (tmp_path / "output.txt").read_text() == "from python"


# ---------------------------------------------------------------------------
# Extra read-only binds
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _has_bwrap(), reason="bwrap required")
class TestExtraRoBinds:
    def test_can_read_extra_ro_bind(self, tmp_path):
        from components.sandboxed_backend import SandboxedShellBackend

        skill_dir = tmp_path / "skills"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# My Skill")

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        backend = SandboxedShellBackend(
            root_dir=str(workspace),
            extra_ro_binds=[str(skill_dir)],
        )
        result = backend.execute(f"cat {skill_dir}/SKILL.md")
        assert result.exit_code == 0
        assert "My Skill" in result.output

    def test_cannot_write_to_extra_ro_bind(self, tmp_path):
        from components.sandboxed_backend import SandboxedShellBackend

        skill_dir = tmp_path / "skills"
        skill_dir.mkdir()

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        backend = SandboxedShellBackend(
            root_dir=str(workspace),
            extra_ro_binds=[str(skill_dir)],
        )
        result = backend.execute(f"touch {skill_dir}/evil.txt 2>&1 || echo 'DENIED'")
        assert result.exit_code != 0 or "DENIED" in result.output or "Read-only" in result.output


# ---------------------------------------------------------------------------
# _ensure_workspace_venv
# ---------------------------------------------------------------------------


class TestEnsureWorkspaceVenv:
    def test_creates_venv(self, tmp_path):
        from components.deep_agent import _ensure_workspace_venv

        workspace = str(tmp_path / "ws")
        os.makedirs(workspace)
        _ensure_workspace_venv(workspace)
        assert os.path.isdir(os.path.join(workspace, ".venv"))
        assert os.path.isfile(os.path.join(workspace, ".venv", "bin", "python3"))

    def test_skips_if_venv_exists(self, tmp_path):
        from components.deep_agent import _ensure_workspace_venv

        workspace = str(tmp_path / "ws")
        venv_path = os.path.join(workspace, ".venv")
        os.makedirs(venv_path)

        # Should not attempt to create (directory already exists)
        _ensure_workspace_venv(workspace)
        # No bin/python3 since we just made a bare dir — but no error either
        assert os.path.isdir(venv_path)

    def test_handles_failure_gracefully(self, tmp_path):
        from components.deep_agent import _ensure_workspace_venv

        workspace = str(tmp_path / "ws")
        os.makedirs(workspace)

        with patch("subprocess.run", side_effect=OSError("mock failure")):
            # Should not raise
            _ensure_workspace_venv(workspace)

        # Venv should not exist
        assert not os.path.isdir(os.path.join(workspace, ".venv"))

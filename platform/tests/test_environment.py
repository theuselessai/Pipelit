"""Tests for services.environment — container detection, sandbox resolution, capabilities."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_pipelit_dir(tmp_path, monkeypatch):
    """Point PIPELIT_DIR to tmp_path so tests never touch the real config."""
    monkeypatch.setenv("PIPELIT_DIR", str(tmp_path / "pipelit"))


@pytest.fixture(autouse=True)
def _clear_capabilities_cache():
    """Reset the capabilities cache before each test."""
    import services.environment as env
    env._cached_capabilities = None
    yield
    env._cached_capabilities = None


# ---------------------------------------------------------------------------
# detect_container
# ---------------------------------------------------------------------------


class TestDetectContainer:
    def test_dockerenv_file(self, monkeypatch):
        from services.environment import detect_container

        monkeypatch.delenv("CODESPACES", raising=False)
        monkeypatch.delenv("GITPOD_WORKSPACE_ID", raising=False)
        monkeypatch.delenv("container", raising=False)
        with patch("os.path.exists", side_effect=lambda p: p == "/.dockerenv"):
            with patch("pathlib.Path.exists", return_value=False):
                result = detect_container()
        assert result == "docker"

    def test_codespaces(self, monkeypatch):
        from services.environment import detect_container

        monkeypatch.setenv("CODESPACES", "true")
        result = detect_container()
        assert result == "codespaces"

    def test_gitpod(self, monkeypatch):
        from services.environment import detect_container

        monkeypatch.delenv("CODESPACES", raising=False)
        monkeypatch.setenv("GITPOD_WORKSPACE_ID", "abc123")
        result = detect_container()
        assert result == "gitpod"

    def test_cgroup_docker(self, monkeypatch):
        from services.environment import detect_container

        monkeypatch.delenv("CODESPACES", raising=False)
        monkeypatch.delenv("GITPOD_WORKSPACE_ID", raising=False)
        monkeypatch.delenv("container", raising=False)
        with patch("os.path.exists", return_value=False):
            mock_path = MagicMock()
            mock_path.exists.return_value = True
            mock_path.read_text.return_value = "12:pids:/docker/abc123\n"
            with patch("pathlib.Path.__new__", return_value=mock_path):
                # Use direct cgroup parsing
                with patch("services.environment.Path") as MockPath:
                    mock_cgroup = MagicMock()
                    mock_cgroup.exists.return_value = True
                    mock_cgroup.read_text.return_value = "12:pids:/docker/abc123\n"
                    MockPath.return_value = mock_cgroup
                    result = detect_container()
        assert result == "docker"

    def test_cgroup_kubepods(self, monkeypatch):
        from services.environment import detect_container

        monkeypatch.delenv("CODESPACES", raising=False)
        monkeypatch.delenv("GITPOD_WORKSPACE_ID", raising=False)
        monkeypatch.delenv("container", raising=False)
        with patch("os.path.exists", return_value=False), \
             patch("services.environment.Path") as MockPath:
            mock_cgroup = MagicMock()
            mock_cgroup.exists.return_value = True
            mock_cgroup.read_text.return_value = "12:pids:/kubepods/besteffort\n"
            MockPath.return_value = mock_cgroup
            result = detect_container()
        assert result == "kubernetes"

    def test_cgroup_containerd(self, monkeypatch):
        from services.environment import detect_container

        monkeypatch.delenv("CODESPACES", raising=False)
        monkeypatch.delenv("GITPOD_WORKSPACE_ID", raising=False)
        monkeypatch.delenv("container", raising=False)
        with patch("os.path.exists", return_value=False), \
             patch("services.environment.Path") as MockPath:
            mock_cgroup = MagicMock()
            mock_cgroup.exists.return_value = True
            mock_cgroup.read_text.return_value = "1:name=containerd:/containerd/abc\n"
            MockPath.return_value = mock_cgroup
            result = detect_container()
        assert result == "containerd"

    def test_podman(self, monkeypatch):
        from services.environment import detect_container

        monkeypatch.delenv("CODESPACES", raising=False)
        monkeypatch.delenv("GITPOD_WORKSPACE_ID", raising=False)
        monkeypatch.setenv("container", "podman")
        with patch("os.path.exists", return_value=False):
            result = detect_container()
        assert result == "podman"

    def test_bare_metal(self, monkeypatch):
        from services.environment import detect_container

        monkeypatch.delenv("CODESPACES", raising=False)
        monkeypatch.delenv("GITPOD_WORKSPACE_ID", raising=False)
        monkeypatch.delenv("container", raising=False)
        with patch("os.path.exists", return_value=False), \
             patch("services.environment.Path") as MockPath:
            mock_cgroup = MagicMock()
            mock_cgroup.exists.return_value = True
            mock_cgroup.read_text.return_value = "12:pids:/\n0::/init.scope\n"
            MockPath.return_value = mock_cgroup
            result = detect_container()
        assert result is None

    def test_priority_codespaces_over_docker(self, monkeypatch):
        """Codespaces env var takes priority over /.dockerenv."""
        from services.environment import detect_container

        monkeypatch.setenv("CODESPACES", "true")
        with patch("os.path.exists", return_value=True):  # /.dockerenv exists too
            result = detect_container()
        assert result == "codespaces"


# ---------------------------------------------------------------------------
# resolve_sandbox_mode
# ---------------------------------------------------------------------------


class TestSandboxResolution:
    def test_auto_with_bwrap(self, monkeypatch):
        from services.environment import resolve_sandbox_mode

        with patch("shutil.which", side_effect=lambda c: "/usr/bin/bwrap" if c == "bwrap" else None), \
             patch("services.environment.detect_container", return_value=None):
            result = resolve_sandbox_mode("auto")
        assert result.mode == "bwrap"
        assert result.can_execute is True

    def test_auto_with_container(self, monkeypatch):
        from services.environment import resolve_sandbox_mode

        with patch("shutil.which", return_value=None), \
             patch("services.environment.detect_container", return_value="docker"):
            result = resolve_sandbox_mode("auto")
        assert result.mode == "container"
        assert result.can_execute is True
        assert result.container_type == "docker"

    def test_auto_with_nothing(self, monkeypatch):
        from services.environment import resolve_sandbox_mode

        with patch("shutil.which", return_value=None), \
             patch("services.environment.detect_container", return_value=None):
            result = resolve_sandbox_mode("auto")
        assert result.mode == "none"
        assert result.can_execute is True
        assert result.reason is not None

    def test_bwrap_present(self):
        from services.environment import resolve_sandbox_mode

        with patch("shutil.which", side_effect=lambda c: "/usr/bin/bwrap" if c == "bwrap" else None), \
             patch("services.environment.detect_container", return_value=None):
            result = resolve_sandbox_mode("bwrap")
        assert result.mode == "bwrap"
        assert result.can_execute is True

    def test_bwrap_missing(self):
        from services.environment import resolve_sandbox_mode

        with patch("shutil.which", return_value=None), \
             patch("services.environment.detect_container", return_value=None):
            result = resolve_sandbox_mode("bwrap")
        assert result.mode == "bwrap"
        assert result.can_execute is False
        assert "not found" in result.reason

    def test_container_present(self):
        from services.environment import resolve_sandbox_mode

        with patch("services.environment.detect_container", return_value="docker"):
            result = resolve_sandbox_mode("container")
        assert result.mode == "container"
        assert result.can_execute is True
        assert result.container_type == "docker"

    def test_container_absent(self):
        from services.environment import resolve_sandbox_mode

        with patch("services.environment.detect_container", return_value=None):
            result = resolve_sandbox_mode("container")
        assert result.mode == "container"
        assert result.can_execute is False
        assert "no container detected" in result.reason


# ---------------------------------------------------------------------------
# _detect_runtimes
# ---------------------------------------------------------------------------


class TestDetectRuntimes:
    def test_python3_available(self):
        from services.environment import _detect_runtimes

        with patch("shutil.which", side_effect=lambda c: "/usr/bin/python3" if c == "python3" else None), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout=b"Python 3.11.2\n", stderr=b"", returncode=0
            )
            runtimes = _detect_runtimes()

        assert runtimes["python3"]["available"] is True
        assert runtimes["python3"]["path"] == "/usr/bin/python3"
        assert "3.11" in runtimes["python3"]["version"]

    def test_node_missing(self):
        from services.environment import _detect_runtimes

        with patch("shutil.which", return_value=None):
            runtimes = _detect_runtimes()

        assert runtimes["node"]["available"] is False
        assert runtimes["node"]["version"] is None

    def test_version_timeout(self):
        from services.environment import _detect_runtimes

        with patch("shutil.which", side_effect=lambda c: f"/usr/bin/{c}"), \
             patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="test", timeout=3)):
            runtimes = _detect_runtimes()

        # Should not raise, version should be None
        assert runtimes["python3"]["available"] is True
        assert runtimes["python3"]["version"] is None

    def test_all_keys_present(self):
        from services.environment import _detect_runtimes

        with patch("shutil.which", return_value=None):
            runtimes = _detect_runtimes()

        assert "python3" in runtimes
        assert "node" in runtimes
        assert "pip3" in runtimes


# ---------------------------------------------------------------------------
# _detect_shell_tools
# ---------------------------------------------------------------------------


class TestDetectShellTools:
    def test_tools_present(self):
        from services.environment import _detect_shell_tools, TIER1_TOOLS, TIER2_TOOLS

        with patch("shutil.which", side_effect=lambda c: f"/usr/bin/{c}"):
            tools = _detect_shell_tools()

        for tool_name in TIER1_TOOLS:
            assert tools[tool_name]["available"] is True
            assert tools[tool_name]["tier"] == 1

        for tool_name in TIER2_TOOLS:
            assert tools[tool_name]["available"] is True
            assert tools[tool_name]["tier"] == 2

    def test_tool_missing(self):
        from services.environment import _detect_shell_tools

        with patch("shutil.which", return_value=None):
            tools = _detect_shell_tools()

        assert tools["bash"]["available"] is False
        assert tools["git"]["available"] is False


# ---------------------------------------------------------------------------
# _detect_network
# ---------------------------------------------------------------------------


class TestDetectNetwork:
    def test_dns_ok(self):
        from services.environment import _detect_network

        with patch("subprocess.run") as mock_run, \
             patch("shutil.which", return_value=None):
            mock_run.return_value = MagicMock(returncode=0)
            network = _detect_network()

        assert network["dns"] is True

    def test_dns_fail(self):
        from services.environment import _detect_network

        with patch("subprocess.run") as mock_run, \
             patch("shutil.which", return_value=None):
            mock_run.return_value = MagicMock(returncode=2)
            network = _detect_network()

        assert network["dns"] is False
        assert network["http"] is False

    def test_http_ok_with_curl(self):
        from services.environment import _detect_network

        call_count = 0

        def mock_run(args, **kwargs):
            nonlocal call_count
            call_count += 1
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=mock_run), \
             patch("shutil.which", side_effect=lambda c: f"/usr/bin/{c}" if c == "curl" else None):
            network = _detect_network()

        assert network["http"] is True

    def test_http_fail(self):
        from services.environment import _detect_network

        with patch("subprocess.run") as mock_run, \
             patch("shutil.which", side_effect=lambda c: "/usr/bin/curl" if c == "curl" else None):
            mock_run.return_value = MagicMock(returncode=1)
            network = _detect_network()

        assert network["http"] is False


# ---------------------------------------------------------------------------
# _detect_system
# ---------------------------------------------------------------------------


class TestDetectSystem:
    def test_os(self):
        from services.environment import _detect_system

        with patch("platform.system", return_value="Linux"):
            system = _detect_system()
        assert system["os"] == "Linux"

    def test_arch(self):
        from services.environment import _detect_system

        with patch("platform.machine", return_value="x86_64"):
            system = _detect_system()
        assert system["arch"] == "x86_64"


# ---------------------------------------------------------------------------
# Capabilities cache
# ---------------------------------------------------------------------------


class TestCapabilitiesCache:
    def test_cached_after_first_call(self):
        from services.environment import detect_capabilities, get_cached_capabilities

        with patch("services.environment._detect_runtimes", return_value={}), \
             patch("services.environment._detect_shell_tools", return_value={}), \
             patch("services.environment._detect_network", return_value={}), \
             patch("services.environment._detect_filesystem", return_value={}), \
             patch("services.environment._detect_system", return_value={}):
            first = detect_capabilities()
            cached = get_cached_capabilities()

        assert cached is first

    def test_refresh_replaces(self):
        from services.environment import detect_capabilities, refresh_capabilities, get_cached_capabilities

        with patch("services.environment._detect_runtimes", return_value={"v": 1}), \
             patch("services.environment._detect_shell_tools", return_value={}), \
             patch("services.environment._detect_network", return_value={}), \
             patch("services.environment._detect_filesystem", return_value={}), \
             patch("services.environment._detect_system", return_value={}):
            first = detect_capabilities()

        with patch("services.environment._detect_runtimes", return_value={"v": 2}), \
             patch("services.environment._detect_shell_tools", return_value={}), \
             patch("services.environment._detect_network", return_value={}), \
             patch("services.environment._detect_filesystem", return_value={}), \
             patch("services.environment._detect_system", return_value={}):
            refreshed = refresh_capabilities()

        assert refreshed is not first
        assert refreshed["runtimes"]["v"] == 2
        assert get_cached_capabilities() is refreshed


# ---------------------------------------------------------------------------
# validate_environment_on_startup
# ---------------------------------------------------------------------------


class TestStartupValidation:
    def test_returns_resolution(self, tmp_path, monkeypatch):
        from services.environment import validate_environment_on_startup, SandboxResolution

        monkeypatch.setenv("PIPELIT_DIR", str(tmp_path / "pipelit"))

        with patch("services.environment.resolve_sandbox_mode") as mock_resolve, \
             patch("services.environment.refresh_capabilities", return_value={"system": {}}):
            mock_resolve.return_value = SandboxResolution(
                mode="none", can_execute=True
            )
            result = validate_environment_on_startup()

        assert isinstance(result, SandboxResolution)
        assert result.mode == "none"

    def test_warns_bwrap_gone(self, tmp_path, monkeypatch, caplog):
        import json
        from services.environment import validate_environment_on_startup, SandboxResolution

        pipelit_dir = tmp_path / "pipelit"
        pipelit_dir.mkdir(parents=True)
        monkeypatch.setenv("PIPELIT_DIR", str(pipelit_dir))

        # Previous state had bwrap
        prev_conf = {
            "detected_environment": {"sandbox_mode": "bwrap", "container_type": None}
        }
        (pipelit_dir / "conf.json").write_text(json.dumps(prev_conf))

        with patch("services.environment.resolve_sandbox_mode") as mock_resolve, \
             patch("services.environment.refresh_capabilities", return_value={"system": {}}):
            mock_resolve.return_value = SandboxResolution(
                mode="none", can_execute=True
            )
            with caplog.at_level("WARNING"):
                validate_environment_on_startup()

        assert "bwrap" in caplog.text

    def test_warns_container_gone(self, tmp_path, monkeypatch, caplog):
        import json
        from services.environment import validate_environment_on_startup, SandboxResolution

        pipelit_dir = tmp_path / "pipelit"
        pipelit_dir.mkdir(parents=True)
        monkeypatch.setenv("PIPELIT_DIR", str(pipelit_dir))

        prev_conf = {
            "detected_environment": {"sandbox_mode": "container", "container_type": "docker"}
        }
        (pipelit_dir / "conf.json").write_text(json.dumps(prev_conf))

        with patch("services.environment.resolve_sandbox_mode") as mock_resolve, \
             patch("services.environment.refresh_capabilities", return_value={"system": {}}):
            mock_resolve.return_value = SandboxResolution(
                mode="none", can_execute=True, container_type=None
            )
            with caplog.at_level("WARNING"):
                validate_environment_on_startup()

        assert "bare metal" in caplog.text

    def test_updates_conf_json(self, tmp_path, monkeypatch):
        import json
        from services.environment import validate_environment_on_startup, SandboxResolution

        pipelit_dir = tmp_path / "pipelit"
        pipelit_dir.mkdir(parents=True)
        monkeypatch.setenv("PIPELIT_DIR", str(pipelit_dir))

        with patch("services.environment.resolve_sandbox_mode") as mock_resolve, \
             patch("services.environment.refresh_capabilities", return_value={"system": {"os": "Linux"}}):
            mock_resolve.return_value = SandboxResolution(
                mode="bwrap", can_execute=True, container_type=None
            )
            with patch("services.rootfs.is_rootfs_ready", return_value=False), \
                 patch("services.rootfs.get_golden_dir", return_value=tmp_path / "rootfs"):
                validate_environment_on_startup()

        conf_data = json.loads((pipelit_dir / "conf.json").read_text())
        assert conf_data["detected_environment"]["sandbox_mode"] == "bwrap"
        assert conf_data["detected_environment"]["can_execute"] is True

    def test_checks_rootfs_when_bwrap(self, tmp_path, monkeypatch, caplog):
        import json
        from services.environment import validate_environment_on_startup, SandboxResolution

        pipelit_dir = tmp_path / "pipelit"
        pipelit_dir.mkdir(parents=True)
        monkeypatch.setenv("PIPELIT_DIR", str(pipelit_dir))

        with patch("services.environment.resolve_sandbox_mode") as mock_resolve, \
             patch("services.environment.refresh_capabilities", return_value={"system": {}}), \
             patch("services.rootfs.is_rootfs_ready", return_value=True) as mock_ready, \
             patch("services.rootfs.get_golden_dir", return_value=tmp_path / "rootfs"):
            mock_resolve.return_value = SandboxResolution(
                mode="bwrap", can_execute=True, container_type=None
            )
            with caplog.at_level("INFO"):
                validate_environment_on_startup()

        mock_ready.assert_called_once()
        assert "Golden rootfs ready" in caplog.text

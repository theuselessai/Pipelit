"""Tests for services/capabilities.py — runtime/tool detection and formatting."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_platform_dir = str(Path(__file__).resolve().parent.parent)
if _platform_dir not in sys.path:
    sys.path.insert(0, _platform_dir)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Reset the module-level cache before each test."""
    import services.capabilities as cap_mod
    cap_mod._cached_capabilities = None
    yield
    cap_mod._cached_capabilities = None


class TestDetectRuntimes:
    def test_detect_runtimes(self):
        """Mocked shutil.which + subprocess for runtime detection."""
        def fake_which(name):
            if name in ("python3", "node"):
                return f"/usr/bin/{name}"
            return None

        def fake_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            name = cmd[0] if cmd else ""
            result = MagicMock()
            result.returncode = 0
            if name == "python3":
                result.stdout = "Python 3.11.0"
                result.stderr = ""
            elif name == "node":
                result.stdout = "v20.10.0"
                result.stderr = ""
            else:
                result.stdout = ""
                result.stderr = ""
            return result

        with patch("services.capabilities.shutil.which", side_effect=fake_which), \
             patch("services.capabilities.subprocess.run", side_effect=fake_run), \
             patch("services.capabilities._check_dns", return_value=False), \
             patch("services.capabilities._check_http", return_value=False), \
             patch("services.capabilities._check_writable", return_value=True):
            from services.capabilities import detect_capabilities
            caps = detect_capabilities()

        assert caps["runtimes"]["python3"]["available"] is True
        assert "3.11" in caps["runtimes"]["python3"]["version"]
        assert caps["runtimes"]["node"]["available"] is True
        assert caps["runtimes"]["pip"]["available"] is False
        assert caps["runtimes"]["ruby"]["available"] is False


class TestDetectShellTools:
    def test_detect_shell_tools(self):
        """Mocked shutil.which for shell tool detection."""
        found_tools = {"bash", "cat", "ls", "grep", "curl", "git"}

        def fake_which(name):
            if name in found_tools:
                return f"/usr/bin/{name}"
            return None

        with patch("services.capabilities.shutil.which", side_effect=fake_which), \
             patch("services.capabilities.subprocess.run", return_value=MagicMock(stdout="", stderr="", returncode=0)), \
             patch("services.capabilities._check_dns", return_value=False), \
             patch("services.capabilities._check_http", return_value=False), \
             patch("services.capabilities._check_writable", return_value=False):
            from services.capabilities import detect_capabilities
            caps = detect_capabilities()

        for tool in found_tools:
            assert caps["shell_tools"][tool]["available"] is True
        assert caps["shell_tools"]["wget"]["available"] is False
        assert caps["shell_tools"]["jq"]["available"] is False


class TestFormatCapabilityContext:
    def test_format_includes_available_tools(self):
        """Output includes available/missing tools."""
        caps = {
            "runtimes": {
                "python3": {"available": True, "version": "Python 3.11.0", "path": "/usr/bin/python3"},
                "node": {"available": False, "version": None, "path": None},
            },
            "shell_tools": {
                "bash": {"available": True},
                "curl": {"available": True},
                "wget": {"available": False},
            },
            "network": {"dns": True, "http": True},
            "filesystem": {"workspace_writable": False, "tmp_writable": True},
        }

        from services.capabilities import format_capability_context
        output = format_capability_context(caps)

        assert "python3" in output
        assert "bash" in output
        assert "curl" in output
        assert "DNS" in output
        assert "HTTP" in output
        assert "/tmp writable" in output

    def test_format_no_runtimes(self):
        """When no runtimes available, says 'none detected'."""
        caps = {
            "runtimes": {
                "python3": {"available": False, "version": None, "path": None},
            },
            "shell_tools": {},
            "network": {"dns": False, "http": False},
            "filesystem": {},
        }

        from services.capabilities import format_capability_context
        output = format_capability_context(caps)

        assert "none detected" in output


class TestCapabilitiesCached:
    def test_second_call_returns_cache(self):
        """Second call doesn't re-probe — returns cached result."""
        call_count = 0

        original_which = __import__("shutil").which

        def counting_which(name):
            nonlocal call_count
            call_count += 1
            return original_which(name)

        with patch("services.capabilities.shutil.which", side_effect=counting_which), \
             patch("services.capabilities._check_dns", return_value=False), \
             patch("services.capabilities._check_http", return_value=False), \
             patch("services.capabilities._check_writable", return_value=False):
            from services.capabilities import detect_capabilities
            caps1 = detect_capabilities()
            first_count = call_count
            caps2 = detect_capabilities()

        # Second call should not increment call_count
        assert call_count == first_count
        assert caps1 is caps2

"""Tests for services.rootfs — Alpine rootfs provisioning and per-workspace copy."""

from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_pipelit_dir(tmp_path, monkeypatch):
    """Point PIPELIT_DIR to tmp_path so tests never touch the real config."""
    monkeypatch.setenv("PIPELIT_DIR", str(tmp_path / "pipelit"))


# ---------------------------------------------------------------------------
# detect_arch
# ---------------------------------------------------------------------------


class TestDetectArch:
    def test_x86_64(self):
        from services.rootfs import detect_arch

        with patch("platform.machine", return_value="x86_64"):
            assert detect_arch() == "x86_64"

    def test_aarch64(self):
        from services.rootfs import detect_arch

        with patch("platform.machine", return_value="aarch64"):
            assert detect_arch() == "aarch64"

    def test_arm64_maps_to_aarch64(self):
        from services.rootfs import detect_arch

        with patch("platform.machine", return_value="arm64"):
            assert detect_arch() == "aarch64"

    def test_unsupported_raises(self):
        from services.rootfs import detect_arch

        with patch("platform.machine", return_value="mips64"):
            with pytest.raises(RuntimeError, match="Unsupported architecture"):
                detect_arch()


# ---------------------------------------------------------------------------
# get_latest_version
# ---------------------------------------------------------------------------


SAMPLE_YAML = """\
---
- flavor: alpine-minirootfs
  version: "3.21.3"
  file: alpine-minirootfs-3.21.3-x86_64.tar.gz
  sha256: abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890
- flavor: alpine-standard
  version: "3.21.3"
  file: alpine-standard-3.21.3-x86_64.iso
  sha256: 1111111111111111111111111111111111111111111111111111111111111111
"""


class TestGetLatestVersion:
    def test_parses_yaml(self):
        from services.rootfs import get_latest_version

        mock_resp = MagicMock()
        mock_resp.read.return_value = SAMPLE_YAML.encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            version, filename, sha256 = get_latest_version("x86_64")

        assert version == "3.21.3"
        assert "minirootfs" in filename
        assert sha256 == "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"

    def test_no_minirootfs_raises(self):
        from services.rootfs import get_latest_version

        yaml_no_mini = """\
- flavor: alpine-standard
  version: "3.21.3"
  file: alpine-standard-3.21.3-x86_64.iso
  sha256: 1111111111111111111111111111111111111111111111111111111111111111
"""
        mock_resp = MagicMock()
        mock_resp.read.return_value = yaml_no_mini.encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="No minirootfs"):
                get_latest_version("x86_64")


# ---------------------------------------------------------------------------
# is_rootfs_ready
# ---------------------------------------------------------------------------


class TestRootfsReadiness:
    def test_ready(self, tmp_path):
        from services.rootfs import is_rootfs_ready

        rootfs = tmp_path / "rootfs"
        (rootfs / "bin").mkdir(parents=True)
        (rootfs / "bin" / "sh").touch()
        (rootfs / "usr" / "bin").mkdir(parents=True)
        (rootfs / "usr" / "bin" / "python3").touch()
        (rootfs / ".alpine-version").write_text("3.21.3")

        assert is_rootfs_ready(rootfs) is True

    def test_empty_dir(self, tmp_path):
        from services.rootfs import is_rootfs_ready

        rootfs = tmp_path / "rootfs"
        rootfs.mkdir()
        assert is_rootfs_ready(rootfs) is False

    def test_no_python(self, tmp_path):
        from services.rootfs import is_rootfs_ready

        rootfs = tmp_path / "rootfs"
        (rootfs / "bin").mkdir(parents=True)
        (rootfs / "bin" / "sh").touch()
        (rootfs / ".alpine-version").write_text("3.21.3")

        assert is_rootfs_ready(rootfs) is False

    def test_no_version_file(self, tmp_path):
        from services.rootfs import is_rootfs_ready

        rootfs = tmp_path / "rootfs"
        (rootfs / "bin").mkdir(parents=True)
        (rootfs / "bin" / "sh").touch()
        (rootfs / "usr" / "bin").mkdir(parents=True)
        (rootfs / "usr" / "bin" / "python3").touch()

        assert is_rootfs_ready(rootfs) is False


# ---------------------------------------------------------------------------
# download_rootfs
# ---------------------------------------------------------------------------


class TestDownloadRootfs:
    def test_success(self, tmp_path):
        import hashlib
        from services.rootfs import download_rootfs

        data = b"fake tarball data"
        sha256 = hashlib.sha256(data).hexdigest()

        mock_resp = MagicMock()
        mock_resp.read.return_value = data
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("services.rootfs.get_latest_version", return_value=("3.21", "mini.tar.gz", sha256)), \
             patch("urllib.request.urlopen", return_value=mock_resp):
            result = download_rootfs(tmp_path, "x86_64")

        assert result.exists()
        assert result.name == "mini.tar.gz"
        assert result.read_bytes() == data

    def test_checksum_mismatch(self, tmp_path):
        from services.rootfs import download_rootfs

        data = b"fake tarball data"

        mock_resp = MagicMock()
        mock_resp.read.return_value = data
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("services.rootfs.get_latest_version", return_value=("3.21", "mini.tar.gz", "badhash")), \
             patch("urllib.request.urlopen", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
                download_rootfs(tmp_path, "x86_64")

    def test_network_error(self, tmp_path):
        from services.rootfs import download_rootfs

        with patch("services.rootfs.get_latest_version", return_value=("3.21", "mini.tar.gz", "abc")), \
             patch("urllib.request.urlopen", side_effect=OSError("Connection refused")):
            with pytest.raises(RuntimeError, match="Failed to download"):
                download_rootfs(tmp_path, "x86_64")


# ---------------------------------------------------------------------------
# install_packages
# ---------------------------------------------------------------------------


class TestInstallPackages:
    def test_calls_bwrap_correctly(self, tmp_path):
        from services.rootfs import install_packages

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            install_packages(tmp_path / "rootfs", ["bash", "python3"])

        args = mock_run.call_args[0][0]
        assert args[0] == "bwrap"
        assert "--bind" in args
        assert "--share-net" in args
        assert "apk" in args
        assert "add" in args
        assert "--no-cache" in args
        assert "bash" in args
        assert "python3" in args

    def test_failure_raises(self, tmp_path):
        from services.rootfs import install_packages

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1, stderr=b"ERROR: package not found"
            )
            with pytest.raises(RuntimeError, match="apk add failed"):
                install_packages(tmp_path / "rootfs", ["nonexistent-pkg"])


# ---------------------------------------------------------------------------
# _ensure_var_tmp_symlink
# ---------------------------------------------------------------------------


class TestVarTmpSymlink:
    def test_creates_symlink(self, tmp_path):
        from services.rootfs import _ensure_var_tmp_symlink

        rootfs = tmp_path / "rootfs"
        rootfs.mkdir()
        _ensure_var_tmp_symlink(rootfs)

        var_tmp = rootfs / "var" / "tmp"
        assert var_tmp.is_symlink()
        assert os.readlink(str(var_tmp)) == "/tmp"

    def test_idempotent(self, tmp_path):
        from services.rootfs import _ensure_var_tmp_symlink

        rootfs = tmp_path / "rootfs"
        rootfs.mkdir()
        _ensure_var_tmp_symlink(rootfs)
        _ensure_var_tmp_symlink(rootfs)  # Should not raise

        var_tmp = rootfs / "var" / "tmp"
        assert var_tmp.is_symlink()

    def test_replaces_directory(self, tmp_path):
        from services.rootfs import _ensure_var_tmp_symlink

        rootfs = tmp_path / "rootfs"
        (rootfs / "var" / "tmp").mkdir(parents=True)
        assert (rootfs / "var" / "tmp").is_dir()
        assert not (rootfs / "var" / "tmp").is_symlink()

        _ensure_var_tmp_symlink(rootfs)

        assert (rootfs / "var" / "tmp").is_symlink()
        assert os.readlink(str(rootfs / "var" / "tmp")) == "/tmp"


# ---------------------------------------------------------------------------
# prepare_golden_image
# ---------------------------------------------------------------------------


class TestPrepareGoldenImage:
    def test_idempotent_skip(self, tmp_path, monkeypatch):
        from services.rootfs import prepare_golden_image

        golden = tmp_path / "pipelit" / "rootfs"
        (golden / "bin").mkdir(parents=True)
        (golden / "bin" / "sh").touch()
        (golden / "usr" / "bin").mkdir(parents=True)
        (golden / "usr" / "bin" / "python3").touch()
        (golden / ".alpine-version").write_text("3.21.3")

        with patch("services.rootfs.get_golden_dir", return_value=golden):
            result = prepare_golden_image()

        assert result == golden

    def test_downloads_when_missing(self, tmp_path, monkeypatch):
        from services.rootfs import prepare_golden_image

        golden = tmp_path / "pipelit" / "rootfs"

        def fake_extract(tarball, target):
            # Simulate extraction creating the rootfs structure
            (target / "bin").mkdir(parents=True, exist_ok=True)
            (target / "bin" / "sh").touch()
            (target / "usr" / "bin").mkdir(parents=True, exist_ok=True)
            (target / "usr" / "bin" / "python3").touch()
            (target / ".alpine-version").write_text("3.21.3")

        tarball_path = tmp_path / "pipelit" / "mini.tar.gz"

        with patch("services.rootfs.get_golden_dir", return_value=golden), \
             patch("services.rootfs.detect_arch", return_value="x86_64"), \
             patch("services.rootfs.download_rootfs", return_value=tarball_path) as mock_dl, \
             patch("services.rootfs.extract_rootfs", side_effect=fake_extract) as mock_extract, \
             patch("services.rootfs.install_packages") as mock_install:
            # Create the tarball so unlink works
            golden.parent.mkdir(parents=True, exist_ok=True)
            tarball_path.touch()
            result = prepare_golden_image()

        mock_dl.assert_called_once()
        mock_extract.assert_called_once()
        mock_install.assert_called_once()
        assert result == golden

    def test_uses_flock(self, tmp_path, monkeypatch):
        from services.rootfs import prepare_golden_image

        golden = tmp_path / "pipelit" / "rootfs"

        def fake_extract(tarball, target):
            (target / "bin").mkdir(parents=True, exist_ok=True)
            (target / "bin" / "sh").touch()
            (target / "usr" / "bin").mkdir(parents=True, exist_ok=True)
            (target / "usr" / "bin" / "python3").touch()
            (target / ".alpine-version").write_text("3.21.3")

        tarball_path = tmp_path / "pipelit" / "mini.tar.gz"

        with patch("services.rootfs.get_golden_dir", return_value=golden), \
             patch("services.rootfs.detect_arch", return_value="x86_64"), \
             patch("services.rootfs.download_rootfs", return_value=tarball_path), \
             patch("services.rootfs.extract_rootfs", side_effect=fake_extract), \
             patch("services.rootfs.install_packages"), \
             patch("fcntl.flock") as mock_flock:
            golden.parent.mkdir(parents=True, exist_ok=True)
            tarball_path.touch()
            prepare_golden_image()

        # flock should be called for LOCK_EX and LOCK_UN
        assert mock_flock.call_count >= 2


# ---------------------------------------------------------------------------
# copy_rootfs_to_workspace
# ---------------------------------------------------------------------------


class TestCopyRootfsToWorkspace:
    def _make_golden(self, tmp_path):
        golden = tmp_path / "golden"
        (golden / "bin").mkdir(parents=True)
        (golden / "bin" / "sh").touch()
        (golden / "usr" / "bin").mkdir(parents=True)
        (golden / "usr" / "bin" / "python3").touch()
        (golden / ".alpine-version").write_text("3.21.3")
        return golden

    def test_creates_rootfs(self, tmp_path):
        from services.rootfs import copy_rootfs_to_workspace

        golden = self._make_golden(tmp_path)
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        result = copy_rootfs_to_workspace(golden, str(workspace))

        assert result == workspace / ".rootfs"
        assert (workspace / ".rootfs" / "bin" / "sh").exists()
        assert (workspace / ".rootfs" / "usr" / "bin" / "python3").exists()

    def test_idempotent(self, tmp_path):
        from services.rootfs import copy_rootfs_to_workspace

        golden = self._make_golden(tmp_path)
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        copy_rootfs_to_workspace(golden, str(workspace))
        copy_rootfs_to_workspace(golden, str(workspace))  # Should not raise

        assert (workspace / ".rootfs" / "bin" / "sh").exists()

    def test_creates_tmp(self, tmp_path):
        from services.rootfs import copy_rootfs_to_workspace

        golden = self._make_golden(tmp_path)
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        copy_rootfs_to_workspace(golden, str(workspace))

        assert (workspace / ".tmp").is_dir()

    def test_isolation(self, tmp_path):
        """Changes to workspace rootfs don't affect golden image."""
        from services.rootfs import copy_rootfs_to_workspace

        golden = self._make_golden(tmp_path)
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        copy_rootfs_to_workspace(golden, str(workspace))

        # Modify workspace rootfs
        (workspace / ".rootfs" / "new_file.txt").write_text("workspace only")

        # Golden should not be affected
        assert not (golden / "new_file.txt").exists()

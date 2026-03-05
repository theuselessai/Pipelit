"""Tests for services.rootfs — Debian rootfs provisioning and per-workspace copy."""

from __future__ import annotations

import hashlib
import os
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


def _make_debian_rootfs(rootfs_dir: Path) -> None:
    """Create a minimal Debian rootfs structure for testing."""
    (rootfs_dir / "bin").mkdir(parents=True, exist_ok=True)
    (rootfs_dir / "bin" / "sh").touch()
    (rootfs_dir / "usr" / "bin").mkdir(parents=True, exist_ok=True)
    (rootfs_dir / "usr" / "bin" / "python3").touch()
    (rootfs_dir / "etc").mkdir(parents=True, exist_ok=True)
    (rootfs_dir / "etc" / "debian_version").write_text("12.13")


# ---------------------------------------------------------------------------
# detect_arch
# ---------------------------------------------------------------------------


class TestDetectArch:
    def test_x86_64(self):
        from services.rootfs import detect_arch

        with patch("platform.machine", return_value="x86_64"):
            assert detect_arch() == "amd64"

    def test_aarch64(self):
        from services.rootfs import detect_arch

        with patch("platform.machine", return_value="aarch64"):
            assert detect_arch() == "arm64"

    def test_arm64_maps_to_arm64(self):
        from services.rootfs import detect_arch

        with patch("platform.machine", return_value="arm64"):
            assert detect_arch() == "arm64"

    def test_unsupported_raises(self):
        from services.rootfs import detect_arch

        with patch("platform.machine", return_value="mips64"):
            with pytest.raises(RuntimeError, match="Unsupported architecture"):
                detect_arch()


# ---------------------------------------------------------------------------
# is_rootfs_ready
# ---------------------------------------------------------------------------


class TestRootfsReadiness:
    def test_ready(self, tmp_path):
        from services.rootfs import is_rootfs_ready

        rootfs = tmp_path / "rootfs"
        _make_debian_rootfs(rootfs)
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
        (rootfs / "etc").mkdir(parents=True)
        (rootfs / "etc" / "debian_version").write_text("12.13")
        assert is_rootfs_ready(rootfs) is False

    def test_no_version_file(self, tmp_path):
        from services.rootfs import is_rootfs_ready

        rootfs = tmp_path / "rootfs"
        (rootfs / "bin").mkdir(parents=True)
        (rootfs / "bin" / "sh").touch()
        (rootfs / "usr" / "bin").mkdir(parents=True)
        (rootfs / "usr" / "bin" / "python3").touch()
        assert is_rootfs_ready(rootfs) is False

    def test_alpine_rootfs_not_ready(self, tmp_path):
        """Old Alpine rootfs should fail the readiness check."""
        from services.rootfs import is_rootfs_ready

        rootfs = tmp_path / "rootfs"
        (rootfs / "bin").mkdir(parents=True)
        (rootfs / "bin" / "sh").touch()
        (rootfs / "usr" / "bin").mkdir(parents=True)
        (rootfs / "usr" / "bin" / "python3").touch()
        (rootfs / "etc").mkdir(parents=True)
        (rootfs / "etc" / "alpine-release").write_text("3.21.3")
        assert is_rootfs_ready(rootfs) is False


# ---------------------------------------------------------------------------
# download_rootfs
# ---------------------------------------------------------------------------


class TestDownloadRootfs:
    def test_success(self, tmp_path):
        from services.rootfs import download_rootfs

        data = b"fake tarball data"
        sha256 = hashlib.sha256(data).hexdigest()

        call_count = [0]

        def mock_urlopen(req, **kwargs):
            mock_resp = MagicMock()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            if call_count[0] == 0:
                # First call: checksum file
                mock_resp.read.return_value = f"{sha256}  debian-rootfs-amd64.tar.gz\n".encode()
            else:
                # Second call: tarball
                mock_resp.read.return_value = data
            call_count[0] += 1
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            result = download_rootfs(tmp_path, "amd64")

        assert result.exists()
        assert result.name == "debian-rootfs-amd64.tar.gz"
        assert result.read_bytes() == data

    def test_checksum_mismatch(self, tmp_path):
        from services.rootfs import download_rootfs

        data = b"fake tarball data"

        call_count = [0]

        def mock_urlopen(req, **kwargs):
            mock_resp = MagicMock()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            if call_count[0] == 0:
                mock_resp.read.return_value = b"badhash  debian-rootfs-amd64.tar.gz\n"
            else:
                mock_resp.read.return_value = data
            call_count[0] += 1
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
                download_rootfs(tmp_path, "amd64")

    def test_network_error_on_checksum(self, tmp_path):
        from services.rootfs import download_rootfs

        with patch("urllib.request.urlopen", side_effect=OSError("Connection refused")):
            with pytest.raises(RuntimeError, match="Failed to download checksum"):
                download_rootfs(tmp_path, "amd64")

    def test_network_error_on_tarball(self, tmp_path):
        from services.rootfs import download_rootfs

        call_count = [0]

        def mock_urlopen(req, **kwargs):
            if call_count[0] == 0:
                call_count[0] += 1
                mock_resp = MagicMock()
                mock_resp.__enter__ = MagicMock(return_value=mock_resp)
                mock_resp.__exit__ = MagicMock(return_value=False)
                mock_resp.read.return_value = b"abc123  debian-rootfs-amd64.tar.gz\n"
                return mock_resp
            raise OSError("Connection refused")

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            with pytest.raises(RuntimeError, match="Failed to download rootfs"):
                download_rootfs(tmp_path, "amd64")


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
    def test_idempotent_skip(self, tmp_path):
        from services.rootfs import prepare_golden_image

        golden = tmp_path / "pipelit" / "rootfs"
        _make_debian_rootfs(golden)

        with patch("services.rootfs.get_golden_dir", return_value=golden):
            result = prepare_golden_image()

        assert result == golden

    def test_downloads_when_missing(self, tmp_path):
        from services.rootfs import prepare_golden_image

        golden = tmp_path / "pipelit" / "rootfs"
        tarball_path = tmp_path / "pipelit" / "debian-rootfs-amd64.tar.gz"

        def fake_extract(tarball, target):
            _make_debian_rootfs(target)

        with patch("services.rootfs.get_golden_dir", return_value=golden), \
             patch("services.rootfs.detect_arch", return_value="amd64"), \
             patch("services.rootfs.download_rootfs", return_value=tarball_path) as mock_dl, \
             patch("services.rootfs.extract_rootfs", side_effect=fake_extract) as mock_extract:
            golden.parent.mkdir(parents=True, exist_ok=True)
            tarball_path.touch()
            result = prepare_golden_image()

        mock_dl.assert_called_once()
        mock_extract.assert_called_once()
        assert result == golden

    def test_removes_old_rootfs(self, tmp_path):
        """Old Alpine rootfs should be removed and replaced with Debian."""
        from services.rootfs import prepare_golden_image

        golden = tmp_path / "pipelit" / "rootfs"
        # Create an old Alpine rootfs
        (golden / "bin").mkdir(parents=True)
        (golden / "bin" / "sh").touch()
        (golden / "usr" / "bin").mkdir(parents=True)
        (golden / "usr" / "bin" / "python3").touch()
        (golden / "etc").mkdir(parents=True)
        (golden / "etc" / "alpine-release").write_text("3.21.3")

        tarball_path = tmp_path / "pipelit" / "debian-rootfs-amd64.tar.gz"

        def fake_extract(tarball, target):
            _make_debian_rootfs(target)

        with patch("services.rootfs.get_golden_dir", return_value=golden), \
             patch("services.rootfs.detect_arch", return_value="amd64"), \
             patch("services.rootfs.download_rootfs", return_value=tarball_path), \
             patch("services.rootfs.extract_rootfs", side_effect=fake_extract):
            tarball_path.touch()
            result = prepare_golden_image()

        assert result == golden
        assert (golden / "etc" / "debian_version").exists()
        assert not (golden / "etc" / "alpine-release").exists()

    def test_uses_flock(self, tmp_path):
        from services.rootfs import prepare_golden_image

        golden = tmp_path / "pipelit" / "rootfs"
        tarball_path = tmp_path / "pipelit" / "debian-rootfs-amd64.tar.gz"

        def fake_extract(tarball, target):
            _make_debian_rootfs(target)

        with patch("services.rootfs.get_golden_dir", return_value=golden), \
             patch("services.rootfs.detect_arch", return_value="amd64"), \
             patch("services.rootfs.download_rootfs", return_value=tarball_path), \
             patch("services.rootfs.extract_rootfs", side_effect=fake_extract), \
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
        _make_debian_rootfs(golden)
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

    def test_replaces_alpine_rootfs(self, tmp_path):
        """Workspace with old Alpine rootfs should be replaced."""
        from services.rootfs import copy_rootfs_to_workspace

        golden = self._make_golden(tmp_path)
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        # Create old Alpine rootfs in workspace
        old_rootfs = workspace / ".rootfs"
        (old_rootfs / "bin").mkdir(parents=True)
        (old_rootfs / "bin" / "sh").touch()
        (old_rootfs / "etc").mkdir(parents=True)
        (old_rootfs / "etc" / "alpine-release").write_text("3.21.3")

        result = copy_rootfs_to_workspace(golden, str(workspace))

        assert (result / "etc" / "debian_version").exists()
        assert not (result / "etc" / "alpine-release").exists()

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

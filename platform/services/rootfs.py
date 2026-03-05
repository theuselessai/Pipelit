"""Debian rootfs golden image provisioning and per-workspace copy.

Downloads a pre-built Debian rootfs tarball from GitHub Releases, verifies
its SHA-256 hash, extracts it, and copies the golden image to individual
workspaces.  All packages are pre-installed in the tarball — no runtime
package installation needed.
"""

from __future__ import annotations

import fcntl
import hashlib
import logging
import os
import platform
import shutil
import subprocess
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROOTFS_REPO = "theuselessai/debian-rootfs"
ROOTFS_VERSION = "v2"

ARCH_MAP: dict[str, str] = {
    "x86_64": "amd64",
    "aarch64": "arm64",
    "arm64": "arm64",
}


# ---------------------------------------------------------------------------
# Architecture detection
# ---------------------------------------------------------------------------


def detect_arch() -> str:
    """Map ``platform.machine()`` to a Debian architecture string.

    Raises ``RuntimeError`` if the current architecture is not supported.
    """
    machine = platform.machine()
    arch = ARCH_MAP.get(machine)
    if arch is None:
        raise RuntimeError(
            f"Unsupported architecture: {machine}. "
            f"Supported: {', '.join(sorted(ARCH_MAP.keys()))}"
        )
    return arch


# ---------------------------------------------------------------------------
# Directory helpers
# ---------------------------------------------------------------------------


def get_golden_dir() -> Path:
    """Return the golden rootfs directory path.

    Uses ``settings.ROOTFS_DIR`` if set, otherwise ``{pipelit_dir}/rootfs/``.
    """
    from config import settings, get_pipelit_dir

    if settings.ROOTFS_DIR:
        return Path(settings.ROOTFS_DIR)
    return get_pipelit_dir() / "rootfs"


def is_rootfs_ready(rootfs_dir: Path) -> bool:
    """Check whether a rootfs directory contains a usable Debian rootfs.

    Checks for ``/bin/sh``, ``/usr/bin/python3``, and ``/etc/debian_version``.
    """
    return (
        (rootfs_dir / "bin" / "sh").exists()
        and (rootfs_dir / "usr" / "bin" / "python3").exists()
        and (rootfs_dir / "etc" / "debian_version").exists()
    )


# ---------------------------------------------------------------------------
# Download and extraction
# ---------------------------------------------------------------------------


def download_rootfs(target_dir: Path, arch: str) -> Path:
    """Download the Debian rootfs tarball and verify its SHA-256 hash.

    Returns the path to the downloaded tarball.

    Raises ``RuntimeError`` on checksum mismatch or network error.
    """
    base_url = f"https://github.com/{ROOTFS_REPO}/releases/download/{ROOTFS_VERSION}"
    filename = f"debian-rootfs-{arch}.tar.gz"
    tarball_path = target_dir / filename

    # Download checksum
    sha256_url = f"{base_url}/{filename}.sha256"
    logger.info("Fetching checksum from %s", sha256_url)
    req = urllib.request.Request(sha256_url, headers={"User-Agent": "pipelit-rootfs/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            expected_sha256 = resp.read().decode("utf-8").strip().split()[0]
    except Exception as exc:
        raise RuntimeError(f"Failed to download checksum from {sha256_url}: {exc}") from exc

    # Download tarball
    tarball_url = f"{base_url}/{filename}"
    logger.info("Downloading Debian rootfs %s from %s", ROOTFS_VERSION, tarball_url)
    req = urllib.request.Request(tarball_url, headers={"User-Agent": "pipelit-rootfs/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = resp.read()
    except Exception as exc:
        raise RuntimeError(f"Failed to download rootfs from {tarball_url}: {exc}") from exc

    # Verify SHA-256
    actual_sha256 = hashlib.sha256(data).hexdigest()
    if actual_sha256 != expected_sha256:
        raise RuntimeError(
            f"SHA-256 mismatch for {filename}: "
            f"expected {expected_sha256}, got {actual_sha256}"
        )

    tarball_path.write_bytes(data)
    logger.info("Downloaded and verified %s (%d bytes)", filename, len(data))
    return tarball_path


def extract_rootfs(tarball: Path, target_dir: Path) -> None:
    """Extract a rootfs tarball into the target directory."""
    logger.info("Extracting %s to %s", tarball, target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["tar", "xzf", str(tarball), "-C", str(target_dir)],
        check=True,
        capture_output=True,
        timeout=120,
    )


# ---------------------------------------------------------------------------
# /var/tmp → /tmp symlink
# ---------------------------------------------------------------------------


def _ensure_var_tmp_symlink(rootfs_dir: Path) -> None:
    """Create /var/tmp → /tmp symlink in the rootfs.

    Some programs write to /var/tmp expecting persistent temp storage.
    Inside our sandbox, /tmp is backed by workspace/.tmp, so we symlink
    /var/tmp to /tmp for consistency.
    """
    var_dir = rootfs_dir / "var"
    var_dir.mkdir(parents=True, exist_ok=True)
    var_tmp = var_dir / "tmp"

    if var_tmp.is_symlink():
        return  # Already a symlink, idempotent
    if var_tmp.is_dir():
        # Replace directory with symlink
        shutil.rmtree(var_tmp)
    elif var_tmp.exists():
        var_tmp.unlink()

    os.symlink("/tmp", str(var_tmp))


# ---------------------------------------------------------------------------
# Golden image preparation
# ---------------------------------------------------------------------------


def prepare_golden_image(tier: int = 1) -> Path:
    """Prepare the golden Debian rootfs image. Idempotent.

    Uses ``fcntl.flock()`` for concurrency safety across workers.

    The ``tier`` parameter is accepted for API compatibility but ignored —
    all packages are pre-installed in the tarball.

    Returns the path to the golden rootfs directory.
    """
    golden_dir = get_golden_dir()

    # Fast path: already ready
    if is_rootfs_ready(golden_dir):
        logger.info("Golden rootfs already ready at %s", golden_dir)
        return golden_dir

    golden_dir.mkdir(parents=True, exist_ok=True)
    lock_path = golden_dir.parent / ".rootfs.lock"
    lock_path.touch(exist_ok=True)

    with open(lock_path, "r") as lock_fd:
        logger.info("Acquiring rootfs lock at %s", lock_path)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            # Re-check after acquiring lock (another worker may have finished)
            if is_rootfs_ready(golden_dir):
                logger.info("Golden rootfs ready (created by another worker)")
                return golden_dir

            # Clean up old rootfs (e.g. Alpine → Debian migration)
            if golden_dir.exists():
                logger.info("Removing old rootfs at %s", golden_dir)
                shutil.rmtree(golden_dir)
                golden_dir.mkdir(parents=True, exist_ok=True)

            arch = detect_arch()

            # Download
            tarball = download_rootfs(golden_dir.parent, arch)

            try:
                # Extract
                extract_rootfs(tarball, golden_dir)

                # /var/tmp symlink
                _ensure_var_tmp_symlink(golden_dir)

                if not is_rootfs_ready(golden_dir):
                    raise RuntimeError(
                        f"Golden rootfs at {golden_dir} failed readiness check after provisioning. "
                        f"Expected bin/sh, usr/bin/python3, and etc/debian_version."
                    )

                logger.info("Golden rootfs prepared at %s", golden_dir)
            finally:
                # Clean up tarball
                try:
                    tarball.unlink(missing_ok=True)
                except Exception:
                    pass

            return golden_dir
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)


# ---------------------------------------------------------------------------
# Per-workspace copy
# ---------------------------------------------------------------------------


def copy_rootfs_to_workspace(golden_dir: Path, workspace_path: str) -> Path:
    """Copy the golden rootfs to a workspace's ``.rootfs`` directory.

    Also creates ``workspace/.tmp`` for persistent temp storage.

    Returns the path to the workspace rootfs.
    """
    workspace = Path(workspace_path)
    rootfs_dest = workspace / ".rootfs"

    if rootfs_dest.exists() and is_rootfs_ready(rootfs_dest):
        logger.info("Workspace rootfs already exists at %s", rootfs_dest)
        return rootfs_dest

    logger.info("Copying golden rootfs to %s", rootfs_dest)
    if rootfs_dest.exists():
        shutil.rmtree(rootfs_dest)
    shutil.copytree(str(golden_dir), str(rootfs_dest), symlinks=True)

    # Create .tmp for persistent temp
    tmp_dir = workspace / ".tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    return rootfs_dest

"""Alpine rootfs golden image provisioning and per-workspace copy.

Downloads an Alpine Linux minirootfs tarball, verifies its SHA-256 hash,
extracts it, installs tier-1/tier-2 packages via ``apk`` inside a bwrap
sandbox, and copies the resulting golden image to individual workspaces.
"""

from __future__ import annotations

import fcntl
import hashlib
import logging
import os
import platform
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALPINE_CDN = "https://dl-cdn.alpinelinux.org/alpine"

TIER1_PACKAGES: list[str] = [
    "bash", "python3", "py3-pip", "coreutils", "grep", "sed",
]

TIER2_PACKAGES: list[str] = [
    "findutils", "curl", "wget", "git", "tar", "unzip", "jq",
    "gawk", "nodejs", "npm",
]

ARCH_MAP: dict[str, str] = {
    "x86_64": "x86_64",
    "aarch64": "aarch64",
    "arm64": "aarch64",
    "armv7l": "armv7",
    "i686": "x86",
    "i386": "x86",
}


# ---------------------------------------------------------------------------
# Architecture detection
# ---------------------------------------------------------------------------


def detect_arch() -> str:
    """Map ``platform.machine()`` to an Alpine architecture string.

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
# Latest version discovery
# ---------------------------------------------------------------------------


def get_latest_version(arch: str) -> tuple[str, str, str]:
    """Fetch the latest Alpine minirootfs version from the CDN.

    Parses ``latest-releases.yaml`` with simple line-by-line parsing
    (no pyyaml dependency).

    Returns
    -------
    tuple[str, str, str]
        ``(version, filename, sha256)`` for the latest minirootfs.

    Raises
    ------
    RuntimeError
        If no minirootfs entry is found in the YAML.
    """
    url = f"{ALPINE_CDN}/latest-stable/releases/{arch}/latest-releases.yaml"
    logger.info("Fetching Alpine release info from %s", url)

    req = urllib.request.Request(url, headers={"User-Agent": "pipelit-rootfs/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        text = resp.read().decode("utf-8")

    # Parse YAML looking for flavor: alpine-minirootfs blocks
    entries: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("-"):
            if current:
                entries.append(current)
            current = {}
            # Handle "- key: value" format
            rest = stripped.lstrip("- ").strip()
            if ":" in rest:
                k, v = rest.split(":", 1)
                current[k.strip()] = v.strip().strip('"').strip("'")
        elif ":" in stripped and current is not None:
            k, v = stripped.split(":", 1)
            current[k.strip()] = v.strip().strip('"').strip("'")
    if current:
        entries.append(current)

    # Find the minirootfs entry
    for entry in entries:
        flavor = entry.get("flavor", "")
        if "minirootfs" in flavor:
            version = entry.get("version", "")
            filename = entry.get("file", "")
            sha256 = entry.get("sha256", "")
            if version and filename and sha256:
                return version, filename, sha256

    raise RuntimeError(
        f"No minirootfs entry found in Alpine latest-releases.yaml for {arch}"
    )


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
    """Check whether a rootfs directory contains a usable Alpine rootfs.

    Checks for ``/bin/sh``, ``/usr/bin/python3``, and ``.alpine-version``.
    """
    return (
        (rootfs_dir / "bin" / "sh").exists()
        and (rootfs_dir / "usr" / "bin" / "python3").exists()
        and (rootfs_dir / ".alpine-version").exists()
    )


# ---------------------------------------------------------------------------
# Download and extraction
# ---------------------------------------------------------------------------


def download_rootfs(target_dir: Path, arch: str) -> Path:
    """Download the Alpine minirootfs tarball and verify its SHA-256 hash.

    Returns the path to the downloaded tarball.

    Raises ``RuntimeError`` on checksum mismatch or network error.
    """
    version, filename, expected_sha256 = get_latest_version(arch)
    url = f"{ALPINE_CDN}/latest-stable/releases/{arch}/{filename}"
    tarball_path = target_dir / filename

    logger.info("Downloading Alpine rootfs %s from %s", version, url)

    req = urllib.request.Request(url, headers={"User-Agent": "pipelit-rootfs/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
    except Exception as exc:
        raise RuntimeError(f"Failed to download rootfs from {url}: {exc}") from exc

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
    """Extract a minirootfs tarball into the target directory."""
    logger.info("Extracting %s to %s", tarball, target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["tar", "xzf", str(tarball), "-C", str(target_dir)],
        check=True,
        capture_output=True,
        timeout=60,
    )


# ---------------------------------------------------------------------------
# Package installation
# ---------------------------------------------------------------------------


def install_packages(rootfs_dir: Path, packages: list[str]) -> None:
    """Install packages into the rootfs using apk via bwrap.

    Uses bwrap to run ``apk add`` inside the rootfs without requiring
    actual chroot privileges.

    Raises ``RuntimeError`` if package installation fails.
    """
    if not packages:
        return

    logger.info("Installing packages in rootfs: %s", ", ".join(packages))

    cmd = [
        "bwrap",
        "--bind", str(rootfs_dir), "/",
        "--dev", "/dev",
        "--proc", "/proc",
        "--ro-bind", "/etc/resolv.conf", "/etc/resolv.conf",
        "--share-net",
        "--die-with-parent",
        "--chdir", "/",
        "--",
        "apk", "add", "--no-cache",
    ] + packages

    result = subprocess.run(cmd, capture_output=True, timeout=300)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(
            f"apk add failed (exit {result.returncode}): {stderr}"
        )
    logger.info("Package installation complete")


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
    """Prepare the golden Alpine rootfs image. Idempotent.

    Uses ``fcntl.flock()`` for concurrency safety across workers.

    Parameters
    ----------
    tier : int
        Package tier: 1 for TIER1_PACKAGES only, 2 for both tiers.

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

            arch = detect_arch()

            # Download
            tarball = download_rootfs(golden_dir.parent, arch)

            try:
                # Extract
                extract_rootfs(tarball, golden_dir)

                # Install packages
                packages = list(TIER1_PACKAGES)
                if tier >= 2:
                    packages += TIER2_PACKAGES
                install_packages(golden_dir, packages)

                # /var/tmp symlink
                _ensure_var_tmp_symlink(golden_dir)

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

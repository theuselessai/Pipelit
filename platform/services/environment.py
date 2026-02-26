"""Environment detection, sandbox resolution, and capability discovery.

Detects container environments (Docker, Codespaces, Gitpod, Kubernetes,
Podman), resolves the sandbox execution mode, probes available runtimes
and shell tools, and validates the environment at startup.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tier classification constants
# ---------------------------------------------------------------------------

TIER1_TOOLS: list[str] = [
    "bash", "python3", "pip3", "cat", "ls", "cp", "mv", "mkdir",
    "rm", "chmod", "grep", "sed", "head", "tail", "wc",
]

TIER2_TOOLS: list[str] = [
    "find", "sort", "awk", "xargs", "tee", "curl", "wget",
    "git", "tar", "unzip", "jq", "node", "npm",
]

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SandboxResolution:
    """Result of resolving the sandbox execution mode."""

    mode: str  # "bwrap", "container", "none"
    can_execute: bool
    reason: str | None = None
    container_type: str | None = None


# ---------------------------------------------------------------------------
# Container detection
# ---------------------------------------------------------------------------


def detect_container() -> str | None:
    """Detect whether we're running inside a container.

    Returns the container type string or None for bare metal.
    Checks are ordered by specificity (most specific first).
    """
    # Codespaces (GitHub)
    if os.environ.get("CODESPACES") == "true":
        return "codespaces"

    # Gitpod
    if os.environ.get("GITPOD_WORKSPACE_ID"):
        return "gitpod"

    # Docker (/.dockerenv file)
    if os.path.exists("/.dockerenv"):
        return "docker"

    # Podman (container env var)
    if os.environ.get("container") == "podman":
        return "podman"

    # cgroup-based detection (Docker, Kubernetes, containerd)
    try:
        cgroup_path = Path("/proc/1/cgroup")
        if cgroup_path.exists():
            cgroup_text = cgroup_path.read_text()
            if "docker" in cgroup_text:
                return "docker"
            if "kubepods" in cgroup_text:
                return "kubernetes"
            if "containerd" in cgroup_text:
                return "containerd"
    except (OSError, PermissionError):
        pass

    return None


# ---------------------------------------------------------------------------
# Sandbox mode resolution
# ---------------------------------------------------------------------------


def resolve_sandbox_mode(config_mode: str = "auto") -> SandboxResolution:
    """Resolve the effective sandbox mode from config + environment.

    Parameters
    ----------
    config_mode : str
        The configured mode: ``"auto"`` (default), ``"bwrap"``, or
        ``"container"``.

    Returns
    -------
    SandboxResolution
        The resolved mode with execution capability flag.
    """
    container = detect_container()

    if config_mode == "bwrap":
        if shutil.which("bwrap"):
            return SandboxResolution(
                mode="bwrap",
                can_execute=True,
                container_type=container,
            )
        return SandboxResolution(
            mode="bwrap",
            can_execute=False,
            reason="bwrap requested but not found on PATH",
            container_type=container,
        )

    if config_mode == "container":
        if container:
            return SandboxResolution(
                mode="container",
                can_execute=True,
                container_type=container,
            )
        return SandboxResolution(
            mode="container",
            can_execute=False,
            reason="container mode requested but no container detected",
            container_type=None,
        )

    # auto mode: try bwrap first, then container, then none
    if shutil.which("bwrap"):
        return SandboxResolution(
            mode="bwrap",
            can_execute=True,
            container_type=container,
        )

    if container:
        return SandboxResolution(
            mode="container",
            can_execute=True,
            container_type=container,
        )

    return SandboxResolution(
        mode="none",
        can_execute=True,
        reason="no sandbox tool available; commands run unsandboxed",
        container_type=None,
    )


# ---------------------------------------------------------------------------
# Capability detection
# ---------------------------------------------------------------------------

_SUBPROCESS_TIMEOUT = 3  # seconds


def _detect_runtimes() -> dict:
    """Detect available language runtimes and their versions."""
    runtimes: dict[str, dict] = {}
    for name, cmd in [("python3", "python3"), ("node", "node"), ("pip3", "pip3")]:
        path = shutil.which(cmd)
        runtimes[name] = {"available": path is not None, "path": path, "version": None}
        if path:
            try:
                result = subprocess.run(
                    [path, "--version"],
                    capture_output=True,
                    timeout=_SUBPROCESS_TIMEOUT,
                )
                version = result.stdout.decode("utf-8", errors="replace").strip()
                if not version:
                    version = result.stderr.decode("utf-8", errors="replace").strip()
                runtimes[name]["version"] = version
            except (subprocess.TimeoutExpired, OSError):
                pass
    return runtimes


def _detect_shell_tools() -> dict:
    """Detect which tier-1 and tier-2 shell tools are available."""
    tools: dict[str, dict] = {}
    for tool in TIER1_TOOLS + TIER2_TOOLS:
        path = shutil.which(tool)
        tier = 1 if tool in TIER1_TOOLS else 2
        tools[tool] = {"available": path is not None, "tier": tier}
    return tools


def _detect_network() -> dict:
    """Detect basic network connectivity (DNS + HTTP)."""
    network: dict[str, bool] = {"dns": False, "http": False}

    # DNS check
    try:
        result = subprocess.run(
            ["getent", "hosts", "dl-cdn.alpinelinux.org"],
            capture_output=True,
            timeout=_SUBPROCESS_TIMEOUT,
        )
        network["dns"] = result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    # HTTP check (curl preferred, wget fallback)
    for cmd in ["curl", "wget"]:
        if shutil.which(cmd):
            try:
                if cmd == "curl":
                    args = ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                            "--max-time", "3", "https://dl-cdn.alpinelinux.org/alpine/"]
                else:
                    args = ["wget", "-q", "--spider", "--timeout=3",
                            "https://dl-cdn.alpinelinux.org/alpine/"]
                result = subprocess.run(args, capture_output=True, timeout=_SUBPROCESS_TIMEOUT + 2)
                network["http"] = result.returncode == 0
            except (subprocess.TimeoutExpired, OSError):
                pass
            break

    return network


def _detect_filesystem(workspace_path: str | None = None) -> dict:
    """Detect filesystem capabilities."""
    fs: dict[str, bool | str | None] = {
        "workspace_exists": False,
        "workspace_writable": False,
        "tmp_writable": False,
    }
    if workspace_path:
        fs["workspace_exists"] = os.path.isdir(workspace_path)
        if fs["workspace_exists"]:
            fs["workspace_writable"] = os.access(workspace_path, os.W_OK)
    fs["tmp_writable"] = os.access("/tmp", os.W_OK)
    return fs


def _detect_system() -> dict:
    """Detect basic system information."""
    return {
        "os": platform.system(),
        "arch": platform.machine(),
        "kernel": platform.release(),
    }


# ---------------------------------------------------------------------------
# Capabilities cache
# ---------------------------------------------------------------------------

_cached_capabilities: dict | None = None


def detect_capabilities(workspace_path: str | None = None) -> dict:
    """Detect full environment capabilities. Results are cached after first call."""
    global _cached_capabilities
    if _cached_capabilities is not None:
        return _cached_capabilities

    caps = {
        "runtimes": _detect_runtimes(),
        "shell_tools": _detect_shell_tools(),
        "network": _detect_network(),
        "filesystem": _detect_filesystem(workspace_path),
        "system": _detect_system(),
    }
    _cached_capabilities = caps
    return caps


def get_cached_capabilities() -> dict | None:
    """Return cached capabilities or None if not yet detected."""
    return _cached_capabilities


def refresh_capabilities(workspace_path: str | None = None) -> dict:
    """Force re-detection and cache update."""
    global _cached_capabilities
    _cached_capabilities = None
    return detect_capabilities(workspace_path)


# ---------------------------------------------------------------------------
# Startup validation
# ---------------------------------------------------------------------------


def validate_environment_on_startup() -> SandboxResolution:
    """Run full environment validation at server startup.

    1. Resolve sandbox mode from settings
    2. Detect and cache capabilities
    3. Compare with stored detected_environment in conf.json
    4. Log warnings if conditions changed
    5. Update conf.json with current state
    6. If bwrap mode, check rootfs readiness

    Returns the resolved sandbox mode.
    """
    from config import settings, load_conf, save_conf

    # 1. Resolve sandbox mode
    resolution = resolve_sandbox_mode(settings.SANDBOX_MODE)

    # 2. Detect capabilities
    workspace_path = settings.WORKSPACE_DIR or None
    caps = refresh_capabilities(workspace_path)

    # 3. Load previous state from conf.json
    conf = load_conf()
    prev_env = conf.detected_environment

    # 4. Log warnings if conditions changed
    if prev_env:
        prev_sandbox = prev_env.get("sandbox_mode")
        if prev_sandbox == "bwrap" and resolution.mode != "bwrap":
            logger.warning(
                "Sandbox mode changed: was bwrap, now %s. "
                "bwrap may have been uninstalled.",
                resolution.mode,
            )

        prev_container = prev_env.get("container_type")
        if prev_container and not resolution.container_type:
            logger.warning(
                "Container environment changed: was %s, now bare metal.",
                prev_container,
            )
        elif not prev_container and resolution.container_type:
            logger.warning(
                "Container environment changed: was bare metal, now %s.",
                resolution.container_type,
            )

    # 5. Update conf.json with current state
    conf.detected_environment = {
        "sandbox_mode": resolution.mode,
        "can_execute": resolution.can_execute,
        "container_type": resolution.container_type,
        "system": caps.get("system", {}),
    }
    try:
        save_conf(conf)
    except Exception:
        logger.exception("Failed to save detected environment to conf.json")

    # 6. If bwrap mode, check rootfs readiness
    if resolution.mode == "bwrap" and resolution.can_execute:
        try:
            from services.rootfs import get_golden_dir, is_rootfs_ready

            golden = get_golden_dir()
            if is_rootfs_ready(golden):
                logger.info("Golden rootfs ready at %s", golden)
            else:
                logger.info("Golden rootfs not yet provisioned at %s (will be created on first execution)", golden)
        except Exception:
            logger.exception("Failed to check rootfs readiness")

    return resolution

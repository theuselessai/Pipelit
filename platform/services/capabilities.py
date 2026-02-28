"""Capability detection — probes runtimes, shell tools, network, filesystem.

Call ``detect_capabilities()`` once at startup (cached) and
``format_capability_context()`` to build a human-readable context string
injected into agent system prompts.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess

logger = logging.getLogger(__name__)

# Module-level cache — populated on first call to detect_capabilities()
_cached_capabilities: dict | None = None

# Runtimes to probe
RUNTIMES = [
    "python3", "python", "node", "npm", "pip3", "pip",
    "ruby", "go", "java", "cargo",
]

# Shell tools to probe
SHELL_TOOLS = [
    "bash", "sh", "cat", "ls", "cp", "mv", "mkdir", "rm", "chmod",
    "grep", "sed", "head", "tail", "wc", "find", "sort", "awk",
    "xargs", "curl", "wget", "git", "tar", "unzip", "jq",
]


def detect_capabilities() -> dict:
    """Probe available runtimes, shell tools, network, and filesystem.

    Returns a dict with keys: runtimes, shell_tools, network, filesystem.
    Cached after first call — subsequent calls return the cached result.
    """
    global _cached_capabilities
    if _cached_capabilities is not None:
        return _cached_capabilities

    caps: dict = {
        "runtimes": {},
        "shell_tools": {},
        "network": {"dns": False, "http": False},
        "filesystem": {"workspace_writable": False, "tmp_writable": False},
    }

    # Runtimes
    for name in RUNTIMES:
        path = shutil.which(name)
        if path:
            version = _get_version(name)
            caps["runtimes"][name] = {"available": True, "version": version, "path": path}
        else:
            caps["runtimes"][name] = {"available": False, "version": None, "path": None}

    # Shell tools
    for name in SHELL_TOOLS:
        path = shutil.which(name)
        caps["shell_tools"][name] = {"available": path is not None}

    # Network checks (best-effort, non-blocking)
    caps["network"]["dns"] = _check_dns()
    caps["network"]["http"] = _check_http()

    # Filesystem checks
    from config import settings as _settings
    _ws_dir = _settings.WORKSPACE_DIR or os.path.expanduser("~/.config/pipelit/workspaces/default")
    caps["filesystem"]["workspace_writable"] = _check_writable(_ws_dir) if os.path.isdir(_ws_dir) else False
    caps["filesystem"]["tmp_writable"] = _check_writable("/tmp")

    _cached_capabilities = caps
    logger.info("Capabilities detected: %d runtimes, %d shell tools available",
                sum(1 for r in caps["runtimes"].values() if r["available"]),
                sum(1 for t in caps["shell_tools"].values() if t["available"]))
    return caps


def format_capability_context(caps: dict) -> str:
    """Format capabilities as human-readable text for system prompt injection.

    Returns a concise multi-line string describing available tools and runtimes.
    """
    lines = ["## Environment Capabilities"]

    # Runtimes
    available = []
    for name, info in caps.get("runtimes", {}).items():
        if info.get("available"):
            ver = info.get("version", "")
            available.append(f"{name} ({ver})" if ver else name)
    if available:
        lines.append(f"Runtimes: {', '.join(available)}")
    else:
        lines.append("Runtimes: none detected")

    # Shell tools
    tool_names = [name for name, info in caps.get("shell_tools", {}).items() if info.get("available")]
    if tool_names:
        lines.append(f"Shell tools: {', '.join(tool_names)}")
    else:
        lines.append("Shell tools: none detected")

    # Network
    net = caps.get("network", {})
    net_status = []
    if net.get("dns"):
        net_status.append("DNS")
    if net.get("http"):
        net_status.append("HTTP")
    lines.append(f"Network: {', '.join(net_status) if net_status else 'no outbound access'}")

    # Filesystem
    fs = caps.get("filesystem", {})
    fs_status = []
    if fs.get("workspace_writable"):
        fs_status.append("workspace writable")
    if fs.get("tmp_writable"):
        fs_status.append("/tmp writable")
    if fs_status:
        lines.append(f"Filesystem: {', '.join(fs_status)}")

    return "\n".join(lines)


def _get_version(name: str) -> str:
    """Get version string for a runtime (best-effort)."""
    try:
        result = subprocess.run(
            [name, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            stdin=subprocess.DEVNULL,
        )
        output = (result.stdout or result.stderr or "").strip()
        # Take first line only
        return output.split("\n")[0][:100] if output else ""
    except Exception:
        return ""


def _check_dns() -> bool:
    """Check if DNS resolution works."""
    try:
        import socket
        socket.getaddrinfo("dns.google", 53, socket.AF_INET, socket.SOCK_STREAM)
        return True
    except Exception:
        return False


def _check_http() -> bool:
    """Check if outbound HTTP works."""
    try:
        import urllib.request
        urllib.request.urlopen("https://httpbin.org/status/200", timeout=5)
        return True
    except Exception:
        return False


def _check_writable(path: str) -> bool:
    """Check if a path is writable."""
    import os
    import tempfile
    try:
        fd, tmp = tempfile.mkstemp(dir=path)
        os.close(fd)
        os.unlink(tmp)
        return True
    except Exception:
        return False

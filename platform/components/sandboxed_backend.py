"""Sandboxed shell backend for deep agents.

Wraps ``LocalShellBackend.execute()`` in platform-specific sandboxing so that
shell commands run inside an isolated namespace with the workspace directory
mapped as the root filesystem — all writes to any path persist in workspace
subdirectories.

- **Linux**: ``bwrap`` (bubblewrap) — mount namespace isolation
- **Fallback**: unsandboxed ``LocalShellBackend.execute()`` with a warning log
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

from deepagents.backends.local_shell import LocalShellBackend
from deepagents.backends.protocol import ExecuteResponse

logger = logging.getLogger(__name__)

# Default timeout for sandbox commands (seconds)
_DEFAULT_TIMEOUT = 120


def _detect_sandbox() -> str | None:
    """Return the sandbox tool available on this system, or None."""
    if shutil.which("bwrap"):
        return "bwrap"
    return None


def _prepare_sandbox_root(workspace: str) -> None:
    """Create mount points and symlinks in workspace for use as bwrap root."""
    # /usr mount point
    os.makedirs(os.path.join(workspace, "usr"), exist_ok=True)

    # Merged-usr symlinks or directory mount points for /bin, /lib, /sbin, /lib64
    for dir_name in ["bin", "lib", "sbin", "lib64"]:
        host_path = f"/{dir_name}"
        ws_path = os.path.join(workspace, dir_name)
        if os.path.islink(host_path):
            # Merged-usr: create matching symlink (e.g. bin → usr/bin)
            target = os.readlink(host_path)
            if not os.path.islink(ws_path):
                if os.path.isdir(ws_path) and not os.listdir(ws_path):
                    os.rmdir(ws_path)
                if not os.path.exists(ws_path):
                    os.symlink(target, ws_path)
        elif os.path.isdir(host_path):
            # Non-merged: create directory mount point
            os.makedirs(ws_path, exist_ok=True)

    # /etc mount point + individual entry files/dirs
    etc_ws = os.path.join(workspace, "etc")
    os.makedirs(etc_ws, exist_ok=True)
    for etc_entry in ["ssl", "resolv.conf", "hosts", "passwd", "group",
                       "ld.so.cache", "ld.so.conf"]:
        etc_host = f"/etc/{etc_entry}"
        etc_mount = os.path.join(etc_ws, etc_entry)
        if os.path.exists(etc_host):
            if os.path.isdir(etc_host):
                os.makedirs(etc_mount, exist_ok=True)
            elif not os.path.exists(etc_mount):
                Path(etc_mount).touch()

    # Special filesystem mount points + /tmp
    for d in ["proc", "dev", "tmp"]:
        os.makedirs(os.path.join(workspace, d), exist_ok=True)


def _build_bwrap_command(
    command: str,
    workspace: str,
    *,
    extra_ro_binds: list[str] | None = None,
    allow_network: bool = False,
) -> list[str]:
    """Build a bwrap command line for Linux sandboxing."""
    _prepare_sandbox_root(workspace)

    args = ["bwrap", "--unshare-all"]

    # Root: workspace becomes /
    args += ["--bind", workspace, "/"]

    # System binaries — read-only
    args += ["--ro-bind", "/usr", "/usr"]

    # On non-merged-usr systems, also bind /bin, /lib, /sbin, /lib64 separately
    for dir_name in ["bin", "lib", "sbin", "lib64"]:
        host_path = f"/{dir_name}"
        if os.path.isdir(host_path) and not os.path.islink(host_path):
            args += ["--ro-bind", host_path, host_path]

    # /etc entries — read-only
    for etc_path in ["/etc/ssl", "/etc/resolv.conf", "/etc/hosts",
                     "/etc/passwd", "/etc/group", "/etc/ld.so.cache", "/etc/ld.so.conf"]:
        if os.path.exists(etc_path):
            args += ["--ro-bind", etc_path, etc_path]

    args += ["--proc", "/proc"]
    args += ["--dev", "/dev"]

    # Extra read-only binds — create mount points in workspace first
    if extra_ro_binds:
        for path in extra_ro_binds:
            if os.path.exists(path):
                mount_point = os.path.join(workspace, path.lstrip("/"))
                os.makedirs(mount_point, exist_ok=True)
                args += ["--ro-bind", path, path]

    if allow_network:
        args += ["--share-net"]

    args += ["--die-with-parent"]
    args += ["--chdir", "/"]

    venv_bin = "/.venv/bin"
    args += [
        "--setenv", "HOME", "/",
        "--setenv", "PATH", f"{venv_bin}:/usr/bin:/bin",
        "--setenv", "TMPDIR", "/tmp",
    ]

    args += ["bash", "-c", command]
    return args


class SandboxedShellBackend(LocalShellBackend):
    """Shell backend that wraps ``execute()`` in OS-level sandboxing.

    Inherits all filesystem operations from ``LocalShellBackend`` (with
    ``virtual_mode=True`` for path confinement).  Only ``execute()`` is
    overridden to run commands inside a sandbox.

    Parameters
    ----------
    root_dir : str | Path
        Workspace directory — the only writable location inside the sandbox.
    allow_network : bool
        Whether to allow network access inside the sandbox (default False).
    extra_ro_binds : list[str] | None
        Additional paths to mount read-only inside the sandbox (e.g. skill
        directories).
    timeout : int
        Default timeout in seconds for shell commands.
    max_output_bytes : int
        Maximum bytes to capture from command output.
    """

    def __init__(
        self,
        root_dir: str | Path,
        *,
        allow_network: bool = False,
        extra_ro_binds: list[str] | None = None,
        timeout: int = _DEFAULT_TIMEOUT,
        max_output_bytes: int = 100_000,
    ) -> None:
        # Initialise LocalShellBackend with virtual_mode for filesystem sandboxing.
        # We do NOT inherit the parent process env — the sandbox builds its own.
        super().__init__(
            root_dir=root_dir,
            virtual_mode=True,
            timeout=timeout,
            max_output_bytes=max_output_bytes,
            inherit_env=False,
        )
        self._allow_network = allow_network
        self._extra_ro_binds = extra_ro_binds or []
        self._sandbox_tool = _detect_sandbox()

        if self._sandbox_tool:
            logger.info(
                "SandboxedShellBackend: using %s for workspace %s",
                self._sandbox_tool, root_dir,
            )
        else:
            logger.warning(
                "SandboxedShellBackend: no sandbox tool found (install bwrap or use Docker). "
                "Falling back to unsandboxed execution for workspace %s",
                root_dir,
            )

    def execute(
        self,
        command: str,
        *,
        timeout: int | None = None,
    ) -> ExecuteResponse:
        """Execute a shell command inside the sandbox.

        If no sandbox tool is available, falls back to the parent class's
        unsandboxed ``execute()``.
        """
        effective_timeout = timeout if timeout is not None else self._default_timeout
        workspace = str(self.cwd)

        # Fallback — no sandbox tool available
        if self._sandbox_tool is None:
            return super().execute(command, timeout=timeout)

        # Build sandboxed command
        sandbox_cmd = _build_bwrap_command(
            command,
            workspace,
            extra_ro_binds=self._extra_ro_binds,
            allow_network=self._allow_network,
        )

        try:
            result = subprocess.run(
                sandbox_cmd,
                capture_output=True,
                timeout=effective_timeout,
            )
            stdout = result.stdout.decode("utf-8", errors="replace")
            stderr = result.stderr.decode("utf-8", errors="replace")

            # Combine stdout and stderr (prefix stderr lines)
            output_parts = []
            if stdout:
                output_parts.append(stdout)
            if stderr:
                prefixed = "\n".join(
                    f"[stderr] {line}" for line in stderr.splitlines()
                )
                output_parts.append(prefixed)
            output = "\n".join(output_parts)

            # Truncate if needed
            truncated = False
            output_bytes = output.encode("utf-8")
            if len(output_bytes) > self._max_output_bytes:
                output = output_bytes[: self._max_output_bytes].decode("utf-8", errors="ignore")
                truncated = True

            return ExecuteResponse(
                output=output,
                exit_code=result.returncode,
                truncated=truncated,
            )

        except subprocess.TimeoutExpired:
            return ExecuteResponse(
                output=f"Command timed out after {effective_timeout}s",
                exit_code=124,
                truncated=False,
            )
        except Exception as exc:
            logger.exception("SandboxedShellBackend.execute() failed")
            return ExecuteResponse(
                output=f"Sandbox execution error: {exc}",
                exit_code=1,
                truncated=False,
            )

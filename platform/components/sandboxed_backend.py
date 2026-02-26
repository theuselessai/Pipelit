"""Sandboxed shell backend for deep agents.

Wraps ``LocalShellBackend.execute()`` in platform-specific sandboxing so that
shell commands run inside an isolated namespace.

Three execution modes:

- **bwrap**: Alpine rootfs mounted as ``/``, workspace bound at ``/workspace``,
  ``--clearenv`` with explicit env vars.  Full filesystem isolation.
- **container**: Already inside Docker/Codespaces/etc — scrubs env vars and
  runs with a clean ``PATH``/``HOME``.
- **none**: Unsandboxed ``LocalShellBackend.execute()`` fallback with warning.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from deepagents.backends.local_shell import LocalShellBackend
from deepagents.backends.protocol import ExecuteResponse

from services.environment import SandboxResolution, resolve_sandbox_mode

logger = logging.getLogger(__name__)

# Default timeout for sandbox commands (seconds)
_DEFAULT_TIMEOUT = 120


# ---------------------------------------------------------------------------
# Container-mode env scrubbing
# ---------------------------------------------------------------------------


def _build_sandbox_env(workspace_path: str) -> dict[str, str]:
    """Build clean env for container-mode subprocess execution."""
    return {
        "PATH": f"/usr/local/bin:/usr/bin:/bin:{workspace_path}/.packages/bin",
        "HOME": workspace_path,
        "TMPDIR": "/tmp",
        "LANG": "C.UTF-8",
        "PIP_TARGET": f"{workspace_path}/.packages",
        "PYTHONPATH": f"{workspace_path}/.packages",
        "PYTHONDONTWRITEBYTECODE": "1",
    }


# ---------------------------------------------------------------------------
# bwrap command building
# ---------------------------------------------------------------------------


def _build_bwrap_command(
    command: str,
    workspace: str,
    workspace_rootfs: str,
    *,
    extra_ro_binds: list[str] | None = None,
    allow_network: bool = False,
) -> list[str]:
    """Build a bwrap command line for Linux sandboxing with Alpine rootfs.

    The rootfs is mounted as ``/`` (rw), the workspace data at ``/workspace``
    (rw), and ``workspace/.tmp`` at ``/tmp`` (persistent temp).  ``--clearenv``
    strips the host environment; only explicit ``--setenv`` vars are visible.
    """
    # Ensure .tmp exists for persistent temp
    tmp_dir = os.path.join(workspace, ".tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    args = ["bwrap", "--unshare-all"]

    # Rootfs as root (rw — apk cache, etc.)
    args += ["--bind", workspace_rootfs, "/"]

    # Workspace data
    args += ["--bind", workspace, "/workspace"]

    # Persistent temp backed by workspace/.tmp
    args += ["--bind", tmp_dir, "/tmp"]

    # Special filesystems
    args += ["--proc", "/proc"]
    args += ["--dev", "/dev"]

    # DNS resolution (only when network allowed)
    if allow_network:
        if os.path.exists("/etc/resolv.conf"):
            args += ["--ro-bind", "/etc/resolv.conf", "/etc/resolv.conf"]
        args += ["--share-net"]

    # Extra read-only binds (e.g. skill directories)
    if extra_ro_binds:
        for path in extra_ro_binds:
            if os.path.exists(path):
                args += ["--ro-bind", path, path]

    args += ["--die-with-parent"]

    # Clear host environment, set explicit vars
    args += ["--clearenv"]
    args += ["--setenv", "HOME", "/workspace"]
    args += ["--setenv", "PATH", "/usr/local/bin:/usr/bin:/bin:/workspace/.packages/bin"]
    args += ["--setenv", "TMPDIR", "/tmp"]
    args += ["--setenv", "LANG", "C.UTF-8"]
    args += ["--setenv", "PIP_TARGET", "/workspace/.packages"]
    args += ["--setenv", "PYTHONPATH", "/workspace/.packages"]
    args += ["--setenv", "PYTHONDONTWRITEBYTECODE", "1"]

    args += ["--chdir", "/workspace"]

    args += ["bash", "-c", command]
    return args


# ---------------------------------------------------------------------------
# SandboxedShellBackend
# ---------------------------------------------------------------------------


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

        # Resolve sandbox mode via environment detection
        from config import settings
        self._resolution: SandboxResolution = resolve_sandbox_mode(settings.SANDBOX_MODE)
        self._workspace_rootfs: str | None = None

        if self._resolution.mode == "bwrap":
            logger.info(
                "SandboxedShellBackend: bwrap mode for workspace %s", root_dir,
            )
        elif self._resolution.mode == "container":
            logger.info(
                "SandboxedShellBackend: container mode (%s) for workspace %s",
                self._resolution.container_type, root_dir,
            )
        else:
            logger.warning(
                "SandboxedShellBackend: no sandbox available. "
                "Falling back to unsandboxed execution for workspace %s",
                root_dir,
            )

    def _ensure_workspace_rootfs(self, workspace: str) -> str:
        """Lazy rootfs provisioning — prepare golden image and copy to workspace."""
        if self._workspace_rootfs and os.path.isdir(self._workspace_rootfs):
            return self._workspace_rootfs

        from services.rootfs import prepare_golden_image, copy_rootfs_to_workspace

        golden = prepare_golden_image()
        rootfs_path = copy_rootfs_to_workspace(golden, workspace)
        self._workspace_rootfs = str(rootfs_path)
        return self._workspace_rootfs

    def _execute_bwrap(
        self,
        command: str,
        workspace: str,
        effective_timeout: int,
    ) -> ExecuteResponse:
        """Execute a command inside a bwrap sandbox with Alpine rootfs."""
        rootfs = self._ensure_workspace_rootfs(workspace)

        sandbox_cmd = _build_bwrap_command(
            command,
            workspace,
            rootfs,
            extra_ro_binds=self._extra_ro_binds,
            allow_network=self._allow_network,
        )

        return self._run_subprocess(sandbox_cmd, effective_timeout)

    def _execute_container(
        self,
        command: str,
        workspace: str,
        effective_timeout: int,
    ) -> ExecuteResponse:
        """Execute a command with scrubbed env inside a container."""
        clean_env = _build_sandbox_env(workspace)

        return self._run_subprocess(
            ["bash", "-c", command],
            effective_timeout,
            env=clean_env,
            cwd=workspace,
        )

    def _run_subprocess(
        self,
        cmd: list[str],
        timeout: int,
        *,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> ExecuteResponse:
        """Run a subprocess and capture output."""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=timeout,
                env=env,
                cwd=cwd,
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
                output=f"Command timed out after {timeout}s",
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

    def execute(
        self,
        command: str,
        *,
        timeout: int | None = None,
    ) -> ExecuteResponse:
        """Execute a shell command inside the sandbox.

        Routes to bwrap, container, or unsandboxed execution based on
        the resolved sandbox mode.
        """
        effective_timeout = timeout if timeout is not None else self._default_timeout
        workspace = str(self.cwd)

        if self._resolution.mode == "bwrap":
            return self._execute_bwrap(command, workspace, effective_timeout)

        if self._resolution.mode == "container":
            return self._execute_container(command, workspace, effective_timeout)

        # mode == "none" — unsandboxed fallback
        return super().execute(command, timeout=timeout)

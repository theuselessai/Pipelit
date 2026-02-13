"""Run Command tool component — subprocess execution."""

from __future__ import annotations

import subprocess

from langchain_core.tools import tool

from components import register

_DEFAULT_TIMEOUT = 300  # seconds
_MAX_OUTPUT_CHARS = 50_000


@register("run_command")
def run_command_factory(node):
    """Return a LangChain tool that runs shell commands."""

    extra = node.component_config.extra_config or {}
    timeout = int(extra.get("timeout", _DEFAULT_TIMEOUT))

    @tool
    def run_command(command: str) -> str:
        """Run a shell command and return stdout/stderr."""
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
            output = result.stdout
            if result.stderr:
                output += f"\nSTDERR:\n{result.stderr}"
            if result.returncode != 0:
                output += f"\n[exit code: {result.returncode}]"
            output = output or "(no output)"
            if len(output) > _MAX_OUTPUT_CHARS:
                half = _MAX_OUTPUT_CHARS // 2
                output = (
                    output[:half]
                    + f"\n\n... ({len(output) - _MAX_OUTPUT_CHARS} chars truncated) ...\n\n"
                    + output[-half:]
                )
            return output
        except subprocess.TimeoutExpired:
            return f"Error: command timed out after {timeout} seconds"
        except Exception as e:
            return f"Error: {e}"

    return run_command

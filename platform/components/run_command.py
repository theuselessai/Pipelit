"""Run Command tool component — subprocess execution."""

from __future__ import annotations

import subprocess

from langchain_core.tools import tool

from components import register


@register("run_command")
def run_command_factory(node):
    """Return a LangChain tool that runs shell commands."""

    @tool
    def run_command(command: str) -> str:
        """Run a shell command and return stdout/stderr."""
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
            output = result.stdout
            if result.stderr:
                output += f"\nSTDERR:\n{result.stderr}"
            if result.returncode != 0:
                output += f"\n[exit code: {result.returncode}]"
            return output or "(no output)"
        except subprocess.TimeoutExpired:
            return "Error: command timed out after 60 seconds"
        except Exception as e:
            return f"Error: {e}"

    return run_command

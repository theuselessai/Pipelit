"""Code Execute component — execute Python or Bash code in a sandboxed environment."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path

from components import register

logger = logging.getLogger(__name__)


# Security patterns to block
FORBIDDEN_PYTHON_PATTERNS = [
    r"import\s+os\s*$",
    r"from\s+os\s+import",
    r"import\s+subprocess",
    r"from\s+subprocess\s+import",
    r"import\s+shutil",
    r"from\s+shutil\s+import",
    r"__import__\s*\(",
    r"\beval\s*\(",
    r"\bexec\s*\(",
    r"\bcompile\s*\(",
    r"open\s*\(['\"]\/etc",
    r"open\s*\(['\"]\/proc",
    r"open\s*\(['\"]\/sys",
    r"open\s*\(['\"]\/dev",
]

FORBIDDEN_BASH_PATTERNS = [
    r"rm\s+-rf\s+/",
    r"rm\s+-rf\s+~",
    r"rm\s+-rf\s+\$HOME",
    r"dd\s+if=.*of=/dev/",
    r"mkfs\.",
    r">\s*/etc/",
    r">\s*/dev/",
    r"curl.*\|\s*(ba)?sh",
    r"wget.*\|\s*(ba)?sh",
    r"chmod\s+777",
    r"chmod\s+-R\s+777",
]


class SecurityError(Exception):
    """Raised when code contains forbidden patterns."""

    pass


def check_security(code: str, language: str) -> None:
    """Check code for forbidden patterns."""
    patterns = FORBIDDEN_PYTHON_PATTERNS if language == "python" else FORBIDDEN_BASH_PATTERNS

    for pattern in patterns:
        if re.search(pattern, code, re.MULTILINE | re.IGNORECASE):
            raise SecurityError(f"Forbidden pattern detected: {pattern}")


def execute_python_sync(
    code: str,
    timeout: int,
    sandbox: bool,
) -> tuple[str, str, int, any]:
    """Execute Python code synchronously."""

    # Create temp file
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".py",
        delete=False,
        dir="/tmp",
    ) as f:
        f.write(code)
        temp_path = f.name

    try:
        python_exe = "python3"

        # Environment restrictions for sandbox
        env = os.environ.copy()
        if sandbox:
            env["PATH"] = "/usr/bin:/bin:/usr/local/bin"
            env.pop("HOME", None)
            env.pop("USER", None)

        # Run with timeout
        result = subprocess.run(
            [python_exe, temp_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd="/tmp",
            env=env,
        )

        stdout = result.stdout
        stderr = result.stderr

        # Try to parse last line as JSON result
        parsed_result = None
        if stdout.strip():
            lines = stdout.strip().split("\n")
            try:
                parsed_result = json.loads(lines[-1])
            except (json.JSONDecodeError, IndexError):
                pass

        return stdout, stderr, result.returncode, parsed_result

    except subprocess.TimeoutExpired:
        return "", f"Execution timed out after {timeout} seconds", -1, None
    finally:
        os.unlink(temp_path)


def execute_bash_sync(
    code: str,
    timeout: int,
    sandbox: bool,
) -> tuple[str, str, int, any]:
    """Execute Bash code synchronously."""

    # Create temp file
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".sh",
        delete=False,
        dir="/tmp",
    ) as f:
        f.write("#!/bin/bash\nset -e\n")
        f.write(code)
        temp_path = f.name

    try:
        os.chmod(temp_path, 0o755)

        # Environment restrictions for sandbox
        env = os.environ.copy()
        if sandbox:
            env["PATH"] = "/usr/bin:/bin:/usr/local/bin"
            env.pop("HOME", None)
            env.pop("USER", None)

        # Run with timeout
        result = subprocess.run(
            ["/bin/bash", temp_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd="/tmp",
            env=env,
        )

        return result.stdout, result.stderr, result.returncode, None

    except subprocess.TimeoutExpired:
        return "", f"Execution timed out after {timeout} seconds", -1, None
    finally:
        os.unlink(temp_path)


@register("code_execute")
def code_execute_factory(node):
    """Return a graph node function that executes code."""
    extra = node.component_config.extra_config or {}
    node_id = node.node_id

    default_language = extra.get("language", "python")
    timeout_seconds = extra.get("timeout_seconds", 30)
    sandbox = extra.get("sandbox", True)

    def code_execute_node(state: dict) -> dict:
        # Get inputs from state
        node_outputs = state.get("node_outputs", {})
        trigger = state.get("trigger", {})

        # Look for code and language in node_outputs from connected nodes
        code = None
        language = None

        for out in node_outputs.values():
            if isinstance(out, dict):
                if "code" in out and code is None:
                    code = out["code"]
                if "language" in out and language is None:
                    language = out["language"]

        # Also check trigger for direct inputs
        if code is None:
            code = trigger.get("code")
        if language is None:
            language = trigger.get("language") or default_language

        if not code or not code.strip():
            return {
                "node_outputs": {
                    node_id: {
                        "stdout": "",
                        "stderr": "No code provided to execute",
                        "exit_code": -1,
                        "result": None,
                        "error": "EMPTY_CODE",
                    }
                }
            }

        if language not in ("python", "bash"):
            return {
                "node_outputs": {
                    node_id: {
                        "stdout": "",
                        "stderr": f"Language '{language}' not supported. Use 'python' or 'bash'.",
                        "exit_code": -1,
                        "result": None,
                        "error": "UNSUPPORTED_LANGUAGE",
                    }
                }
            }

        try:
            # Security check
            if sandbox:
                check_security(code, language)

            # Execute
            if language == "python":
                stdout, stderr, exit_code, result = execute_python_sync(
                    code, timeout_seconds, sandbox
                )
            else:
                stdout, stderr, exit_code, result = execute_bash_sync(
                    code, timeout_seconds, sandbox
                )

            output = {
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": exit_code,
                "result": result,
            }

            if exit_code != 0:
                output["error"] = "EXECUTION_ERROR"

            return {"node_outputs": {node_id: output}}

        except SecurityError as e:
            return {
                "node_outputs": {
                    node_id: {
                        "stdout": "",
                        "stderr": str(e),
                        "exit_code": -1,
                        "result": None,
                        "error": "SECURITY_VIOLATION",
                    }
                }
            }

        except Exception as e:
            logger.exception("Code execution error")
            return {
                "node_outputs": {
                    node_id: {
                        "stdout": "",
                        "stderr": str(e),
                        "exit_code": -1,
                        "result": None,
                        "error": "EXECUTION_FAILED",
                    }
                }
            }

    return code_execute_node

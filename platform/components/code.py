"""Code execution component — runs user-defined code snippets in a subprocess."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile

from components import register
from components._agent_shared import _build_backend

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 60  # seconds

# Wrapper script written to the workspace at runtime.
# Loads state from __input__.json, executes user code, writes result to __output__.json.
_WRAPPER_SCRIPT = '''\
import json, sys, io, contextlib

with open("__input__.json") as f:
    _data = json.load(f)

state = _data.get("state", {})
node_outputs = _data.get("node_outputs", {})
result = None

_stdout = io.StringIO()
with contextlib.redirect_stdout(_stdout):
    exec(open("__code__.py").read())

_out = {"result": str(result) if result is not None else _stdout.getvalue().strip()}

with open("__output__.json", "w") as f:
    json.dump(_out, f)
'''


@register("code")
def code_factory(node):
    """Build a code graph node that executes a Python snippet in a subprocess."""
    extra = node.component_config.extra_config or {}
    code_snippet = extra.get("code", "")
    language = extra.get("language", "python")
    timeout = int(extra.get("timeout", _DEFAULT_TIMEOUT))

    # Build sandboxed backend (uses workspace_id from extra_config if set)
    try:
        backend = _build_backend(extra)
        workspace_dir = str(backend.cwd)
    except Exception:
        logger.warning("Code node %s: failed to build sandbox backend, falling back to /tmp", node.node_id)
        backend = None
        workspace_dir = tempfile.mkdtemp(prefix="pipelit_code_")

    def code_node(state: dict) -> dict:
        if not code_snippet:
            raise ValueError("No code provided")

        if language != "python":
            raise ValueError(f"Language '{language}' not yet supported in sandbox mode")

        # Write user code and input state to workspace
        code_path = os.path.join(workspace_dir, "__code__.py")
        wrapper_path = os.path.join(workspace_dir, "__wrapper__.py")
        input_path = os.path.join(workspace_dir, "__input__.json")
        output_path = os.path.join(workspace_dir, "__output__.json")

        try:
            # Prepare input data (strip non-serialisable keys)
            input_data = {
                "state": _safe_serialize(state),
                "node_outputs": _safe_serialize(state.get("node_outputs", {})),
            }

            with open(code_path, "w") as f:
                f.write(code_snippet)
            with open(wrapper_path, "w") as f:
                f.write(_WRAPPER_SCRIPT)
            with open(input_path, "w") as f:
                json.dump(input_data, f)

            # Remove stale output file
            if os.path.exists(output_path):
                os.remove(output_path)

            # Execute via sandbox backend or plain subprocess
            if backend is not None:
                resp = backend.execute(f"python3 __wrapper__.py", timeout=timeout)
                exit_code = resp.exit_code
                stderr = resp.output or ""  # ExecuteResponse.output has combined stdout+stderr
            else:
                result = subprocess.run(
                    ["python3", wrapper_path],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=workspace_dir,
                    stdin=subprocess.DEVNULL,
                    start_new_session=True,
                )
                exit_code = result.returncode
                stderr = result.stderr or ""

            if exit_code != 0:
                raise RuntimeError(f"Code execution failed (exit {exit_code}): {stderr.strip()}")

            # Read output
            if not os.path.exists(output_path):
                raise RuntimeError(f"Code execution produced no output file. stderr: {stderr.strip()}")

            with open(output_path) as f:
                out_data = json.load(f)

            return {"output": out_data.get("result", "")}

        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Code execution timed out after {timeout} seconds")
        finally:
            # Clean up temp files
            for p in (code_path, wrapper_path, input_path, output_path):
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except OSError:
                    pass

    return code_node


def _safe_serialize(obj):
    """Best-effort JSON-safe serialization of state data."""
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        pass

    if isinstance(obj, dict):
        return {k: _safe_serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe_serialize(v) for v in obj]
    try:
        return str(obj)
    except Exception:
        return None

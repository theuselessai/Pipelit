"""Code execution component — runs user-defined code snippets."""

from __future__ import annotations

import io
import contextlib

from components import register


@register("code")
def code_factory(node):
    """Build a code graph node that executes a Python/JS/bash snippet."""
    extra = node.component_config.extra_config
    code_snippet = extra.get("code", "")
    language = extra.get("language", "python")
    node_id = node.node_id

    def code_node(state: dict) -> dict:
        if not code_snippet:
            return {
                "node_outputs": {node_id: {"output": "", "error": "No code provided"}},
            }

        if language == "python":
            output, error = _exec_python(code_snippet, state, node_id)
        else:
            return {
                "node_outputs": {node_id: {"output": "", "error": f"Language '{language}' not yet supported"}},
            }

        result: dict = {"node_outputs": {node_id: {"output": output, "error": error}}}
        if output and not error:
            result["message"] = output
        return result

    return code_node


def _exec_python(code: str, state: dict, node_id: str) -> tuple[str, str]:
    """Execute Python code with state available as a local variable.

    The code can:
      - Access `state` dict (read-only by convention)
      - Access `node_outputs` shortcut (= state["node_outputs"])
      - Set `result` variable to produce output
      - Use print() — stdout is captured as output
    """
    stdout_buf = io.StringIO()
    local_vars: dict = {
        "state": state,
        "node_outputs": state.get("node_outputs", {}),
        "result": None,
    }

    try:
        # If code contains `return`, wrap it in a function so `return` works
        if "return " in code or "return\n" in code:
            indented = "\n".join("  " + line for line in code.splitlines())
            wrapped = f"def _user_fn(state, node_outputs):\n{indented}\nresult = _user_fn(state, node_outputs)"
            with contextlib.redirect_stdout(stdout_buf):
                exec(wrapped, {"__builtins__": __builtins__}, local_vars)  # noqa: S102
        else:
            with contextlib.redirect_stdout(stdout_buf):
                exec(code, {"__builtins__": __builtins__}, local_vars)  # noqa: S102

        # Prefer explicit `result` variable, fall back to stdout
        if local_vars.get("result") is not None:
            output = str(local_vars["result"])
        else:
            output = stdout_buf.getvalue()

        return output.strip(), ""
    except Exception as e:
        return "", f"{type(e).__name__}: {e}"

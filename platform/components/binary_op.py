"""Executing one operation of a binary plugin.

One node is one invocation: the binary is spawned, handed its parameters on
stdin, and writes exactly one JSON envelope to stdout. Whatever it does inside —
several requests, a read-back to verify a write, polling until something settles
— is its own business and never reaches this layer.

Every binary node shares the single static component type `binary_op`. Which
binary a node invokes is its own data (`extra_config["binary"]`), and the
operation's surface — parameters, session requirement, output ports — is read
from that binary's pinned catalog at call time via `schemas.binary_catalogs`,
so a plugin registered while this process runs needs no restart.
"""

from __future__ import annotations

import json
import logging
import subprocess

from components import register
from schemas.binary_catalogs import operations_for
from services.plugins import PluginError, verified_plugin

logger = logging.getLogger(__name__)

# Grace on top of the operation's own budget. The binary should hit its timeout
# first and report it in an envelope; killing the process instead produces no
# envelope at all, so a timeout would be indistinguishable from a crash.
TIMEOUT_GRACE_S = 5.0
DEFAULT_TIMEOUT_S = 60.0


class BinaryOperationError(RuntimeError):
    """A plugin invocation failed."""


_error_classes: dict[str, type[BinaryOperationError]] = {}


def _error(code: str, message: str) -> BinaryOperationError:
    """Raise under a class named for the binary's own error code.

    The orchestrator records `type(exc).__name__` as a node's error_code, so
    naming the class after the code is what carries a branchable failure through
    to the execution log — rather than flattening every failure into one name and
    leaving the caller to string-match a message, which is exactly what the
    contract's error codes exist to avoid.
    """
    safe = "".join(c if c.isalnum() or c == "_" else "_" for c in code) or "BINARY_ERROR"
    cls = _error_classes.get(safe)
    if cls is None:
        cls = type(safe, (BinaryOperationError,), {})
        _error_classes[safe] = cls
    return cls(message)


def _operation_spec(binary: str, operation: str) -> dict:
    """The catalog entry for one operation of one binary, or a coded error."""
    operations = operations_for(binary)
    if operations is None:
        raise _error(
            "UNKNOWN_BINARY",
            f"no catalog for binary {binary!r} — is it registered? "
            f"Run scripts/register_plugin.py <plugin>.",
        )
    if operation not in operations:
        raise _error(
            "UNKNOWN_OPERATION",
            f"{operation!r} is not an operation of {binary}. "
            f"Known: {', '.join(sorted(operations))}",
        )
    return operations[operation]


@register("binary_op")
def binary_op_factory(node):
    """Return an executable node that performs one operation of one plugin."""
    extra = node.component_config.extra_config or {}
    binary = str(extra.get("binary") or "")
    operation = str(extra.get("operation") or "")

    def binary_op_node(state: dict) -> dict:
        if not binary:
            raise _error("NO_BINARY", "this node names no binary; set one in its config")
        if not operation:
            raise _error("NO_OPERATION", f"this {binary} node has no operation selected")

        op_spec = _operation_spec(binary, operation)
        plugin, _registration = verified_plugin(binary)

        session = str(extra.get("session") or "")
        if op_spec.get("session_required") and not session:
            raise _error(
                "MISSING_SESSION",
                f"{operation} requires a session; none is set on this node. "
                f"Identities are held by the binary — establish one with `auth login`.",
            )

        argv = list(plugin.argv)
        if session:
            argv += ["--session", session]
        else:
            # --env binds an environment to an identity at login, so it is
            # meaningful only where there is no identity to carry the binding.
            # Passing it alongside a session is how "this identity, that
            # environment" becomes expressible, and binaries refuse it.
            env_name = str(extra.get("env") or "")
            if env_name:
                argv += ["--env", env_name]
        argv += ["call", operation]

        # extra_config has already had its {{ }} expressions resolved upstream.
        declared = set((op_spec.get("params") or {}).get("properties") or {})
        params = {k: v for k, v in extra.items() if k in declared and v not in (None, "")}
        stdin = json.dumps({"params": params})

        budget = float(op_spec.get("timeout_default_s") or DEFAULT_TIMEOUT_S)
        try:
            proc = subprocess.run(
                argv,
                input=stdin,
                capture_output=True,
                text=True,
                timeout=budget + TIMEOUT_GRACE_S,
                cwd=plugin.directory,
            )
        except FileNotFoundError:
            raise _error("PLUGIN_NOT_EXECUTABLE", f"cannot run {argv[0]!r} for plugin {plugin.name}") from None
        except subprocess.TimeoutExpired:
            raise _error(
                "TIMEOUT",
                f"{operation} did not finish within {budget + TIMEOUT_GRACE_S}s and was killed, "
                f"so it reported nothing. Whether it took effect is unknown.",
            ) from None

        if proc.stderr:
            logger.info("%s stderr: %s", plugin.name, proc.stderr.strip()[:2000])

        # stdout is exactly one JSON object and nothing else, so parse the whole
        # stream: a binary that also logged to stdout must fail here rather than
        # yield an envelope that happens to parse.
        try:
            envelope = json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise _error(
                "MALFORMED_ENVELOPE",
                f"{plugin.name} exited {proc.returncode} without writing one JSON object "
                f"to stdout: {proc.stdout.strip()[:400]!r}",
            ) from None

        if not isinstance(envelope, dict) or "ok" not in envelope:
            raise _error("MALFORMED_ENVELOPE", f"{plugin.name} wrote JSON that is not an envelope")

        if not envelope.get("ok"):
            err = envelope.get("error") or {}
            code = str(err.get("code") or "BINARY_ERROR")
            message = str(err.get("message") or "the operation failed")
            # A failure carrying a slot patch is the recovery case: the operation
            # ran and the binary could not write down what it learned, so the
            # stored identity is now behind reality. Never swallow it.
            if envelope.get("slot_patch"):
                message += (
                    " — the binary could not persist a slot change it made; "
                    "the stored identity may be stale"
                )
            raise _error(code, message)

        proof = envelope.get("proof")
        if isinstance(proof, dict) and proof.get("discharged") is False:
            raise _error(
                "PROOF_NOT_DISCHARGED",
                f"{operation} reported success but its verification did not discharge: "
                f"{proof.get('detail') or 'no detail given'}. The write may not have taken effect.",
            )

        # Every port the CONFIGURED OPERATION declares gets a value. A port the
        # invocation did not emit resolves to None rather than being absent,
        # because an absent port becomes the literal string "{{ node.port }}"
        # downstream.
        data = envelope.get("data") or {}
        ports: dict = {name: None for name in op_spec.get("outputs", []) if name}
        ports.update({k: v for k, v in data.items() if k in ports})
        return ports

    return binary_op_node


__all__ = ["binary_op_factory", "BinaryOperationError", "PluginError"]

"""Identity and environment management as workflow nodes.

The verb surface is fixed by the protocol, so one component serves every plugin —
unlike operations, which differ per binary and come from a catalog.

Credentials travel on stdin, never on argv: a process's command line is readable
by other processes for the life of the call, which is why the binaries refuse
credential-shaped flags outright.

⚠️  A password supplied here lives in the node's configuration — in the database,
in the nodes API response, and in the config panel. That is a considered trade
for disposable test identities, which is what this is for. It is NOT suitable for
an account that matters; those are established once, out of band, and merely
selected here.
"""

from __future__ import annotations

import json
import logging
import subprocess

from components import COMPONENT_REGISTRY
from components.binary_op import TIMEOUT_GRACE_S, _error
from schemas.binary_verbs import VERB_MARKER, VERBS, build_argv
from schemas.node_types import get_node_type
from services.plugins import verified_plugin

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 60.0


def binary_auth_factory(node):
    """Return an executable node that performs one identity or environment verb."""
    component_type = node.component_type
    extra = node.component_config.extra_config or {}
    verb_id = str(extra.get("operation") or "")

    def binary_auth_node(state: dict) -> dict:
        spec = get_node_type(component_type)
        if spec is None or not spec.config_schema.get(VERB_MARKER):
            raise _error("NOT_AN_IDENTITY_NODE", f"{component_type!r} is not an identity node")
        if verb_id not in VERBS:
            raise _error(
                "UNKNOWN_VERB",
                f"{verb_id!r} is not a verb. Known: {', '.join(sorted(VERBS))}",
            )

        binary = spec.config_schema["x-binary"]
        plugin, _registration = verified_plugin(binary)

        missing = [
            key for key in (VERBS[verb_id]["params"].get("required") or [])
            if not str(extra.get(key) or "").strip()
        ]
        if missing:
            raise _error(
                "MISSING_PARAM",
                f"{verb_id} needs {', '.join(missing)}; none supplied on this node.",
            )

        fragment, credential = build_argv(verb_id, extra)
        argv = [*plugin.argv, *fragment]
        stdin = json.dumps({"params": {}, "credential": credential}) if credential else json.dumps({"params": {}})

        try:
            proc = subprocess.run(
                argv, input=stdin, capture_output=True, text=True,
                timeout=DEFAULT_TIMEOUT_S + TIMEOUT_GRACE_S, cwd=plugin.directory,
            )
        except FileNotFoundError:
            raise _error("PLUGIN_NOT_EXECUTABLE", f"cannot run {argv[0]!r}") from None
        except subprocess.TimeoutExpired:
            raise _error("TIMEOUT", f"{verb_id} did not finish and was killed") from None

        if proc.stderr:
            logger.info("%s stderr: %s", plugin.name, proc.stderr.strip()[:2000])

        try:
            envelope = json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise _error(
                "MALFORMED_ENVELOPE",
                f"{plugin.name} exited {proc.returncode} without writing one JSON object: "
                f"{proc.stdout.strip()[:300]!r}",
            ) from None

        if not envelope.get("ok"):
            err = envelope.get("error") or {}
            raise _error(str(err.get("code") or "BINARY_ERROR"),
                         str(err.get("message") or f"{verb_id} failed"))

        data = envelope.get("data") or {}
        ports: dict = {p.name: None for p in (spec.outputs if spec else [])}
        ports.update({k: v for k, v in data.items() if k in ports})
        return ports

    return binary_auth_node


def register_verb_types() -> int:
    from schemas.node_types import NODE_TYPE_REGISTRY

    count = 0
    for component_type, spec in NODE_TYPE_REGISTRY.items():
        if spec.config_schema.get(VERB_MARKER):
            COMPONENT_REGISTRY[component_type] = binary_auth_factory
            count += 1
    return count


register_verb_types()

__all__ = ["binary_auth_factory", "register_verb_types"]

"""The verb surface every binary plugin shares.

Operations differ per binary and come from its catalog. *Verbs* do not: the
bin-contract protocol fixes them, so `auth login`, `auth refresh`,
`auth session list/remove` and `env add/list/remove` mean the same thing for
every plugin, including ones nobody has written yet. That is why this table
lives in the platform rather than being read from a catalog — and why a single
node type serves every plugin's identity management.

Login is deliberately NOT a catalog operation, and this does not make it one. A
refresh is a precondition of an operation rather than a step before it — expiry
happens at a time, not at a place in a graph — and the catalog describes what a
binary can *do*, not how a caller establishes who it is. What this module adds is
that Pipelit knows the verb surface independently, so identity management can be
performed on a canvas where automating it is the point: for a platform whose
subject under test includes registering, logging in, rotating and deleting
accounts, login has to be a step in the workflow rather than a prerequisite of
running one.
"""

from __future__ import annotations

from typing import Any

from schemas.node_types import DataType, NodeTypeSpec, PortDefinition

# Marks a node type as driven by this table rather than by a catalog.
VERB_MARKER = "x-verbs"

# argv shape per verb.
#   globals     flags that precede the verb, from node config
#   verb        the literal argv words
#   positional  config keys appended after the verb, in order
#   flags       config key -> flag name, appended after the positionals
#   credential  config keys that travel on stdin instead of argv
#
# A parameter may also carry `"picker"`, naming a list the host can offer:
# "environments" or "sessions". It marks a parameter that names something which
# must ALREADY EXIST, as against one that creates it — `auth login` writes a
# session handle and so takes free text, while `auth refresh` selects one that is
# already there. Getting that backwards produces a picker with nothing in it on
# the very operation whose job is to fill the list.
VERBS: dict[str, dict[str, Any]] = {
    "auth.login": {
        "summary": "Establish an identity and bind it to an environment. Always overwrites the slot.",
        "globals": ["env", "session"],
        "verb": ["auth", "login"],
        "credential": ["username", "password", "totp_seed"],
        "params": {
            "type": "object",
            "required": ["env", "session", "username", "password"],
            "properties": {
                "env": {"type": "string", "title": "Environment", "picker": "environments",
                        "description": "A registered environment name. Bound to this identity at login and nowhere else."},
                "session": {"type": "string", "title": "Session handle",
                            "description": "What to call this identity. An existing handle is overwritten wholesale, so this is free text rather than a picker."},
                "username": {"type": "string", "title": "Username"},
                "password": {"type": "string", "title": "Password", "secret": True},
                "totp_seed": {"type": "string", "title": "TOTP seed", "secret": True,
                              "description": "Only if the account has TOTP enrolled."},
            },
        },
        "outputs": [("session", DataType.OBJECT, "The established identity: handle, subject, environment. Never token material.")],
    },
    "auth.refresh": {
        "summary": "Re-establish a session from the credential the binary already stores.",
        "globals": ["session"],
        "verb": ["auth", "refresh"],
        "params": {
            "type": "object",
            "required": ["session"],
            "properties": {"session": {"type": "string", "title": "Session handle",
                                       "picker": "sessions"}},
        },
        "outputs": [("session", DataType.OBJECT, "The refreshed identity.")],
    },
    "auth.sessionList": {
        "summary": "List the identities this binary holds. Never prints token material.",
        "verb": ["auth", "session", "list"],
        "params": {"type": "object", "properties": {}, "additionalProperties": False},
        "outputs": [("sessions", DataType.ARRAY, "Handle, subject, environment and timestamps for each identity.")],
    },
    "auth.sessionRemove": {
        "summary": "Forget an identity locally. NOT a revocation — the server-side session may still be live.",
        "verb": ["auth", "session", "remove"],
        "positional": ["session"],
        "params": {
            "type": "object",
            "required": ["session"],
            "properties": {"session": {"type": "string", "title": "Session handle",
                                       "picker": "sessions"}},
        },
        "outputs": [("removed", DataType.STRING, "The handle that was forgotten.")],
    },
    "env.add": {
        "summary": "Register an environment this binary may be pointed at.",
        "verb": ["env", "add"],
        "positional": ["name"],
        "flags": {"url": "--url", "kind": "--kind"},
        "params": {
            "type": "object",
            "required": ["name", "url", "kind"],
            "properties": {
                "name": {"type": "string", "title": "Name"},
                "url": {"type": "string", "title": "Base URL"},
                "kind": {"type": "string", "title": "Kind", "enum": ["uat", "prod"],
                         "description": "A binary may refuse to register a production environment at all."},
            },
        },
        "outputs": [("environment", DataType.OBJECT, "The registered environment.")],
    },
    "env.list": {
        "summary": "List the environments this binary knows.",
        "verb": ["env", "list"],
        "params": {"type": "object", "properties": {}, "additionalProperties": False},
        "outputs": [("envs", DataType.ARRAY, "Name, URL and kind for each environment.")],
    },
    "env.remove": {
        "summary": "Forget an environment. Refused while an identity is still bound to it.",
        "verb": ["env", "remove"],
        "positional": ["name"],
        "params": {
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string", "title": "Name", "picker": "environments"}},
        },
        "outputs": [("removed", DataType.STRING, "The environment that was forgotten.")],
    },
}


def component_type_for(binary: str) -> str:
    return f"{binary}_auth".replace("-", "_")


def build_argv(verb_id: str, config: dict) -> tuple[list[str], dict]:
    """Return (argv fragment, credential object) for one verb.

    Global flags precede the verb; positionals and verb-scoped flags follow it.
    Credential values never reach argv — a process's command line is readable by
    other processes for the life of the call.
    """
    spec = VERBS[verb_id]
    argv: list[str] = []
    for key in spec.get("globals", []):
        value = str(config.get(key) or "")
        if value:
            argv += [f"--{key}", value]
    argv += list(spec["verb"])
    for key in spec.get("positional", []):
        value = str(config.get(key) or "")
        if value:
            argv.append(value)
    for key, flag in (spec.get("flags") or {}).items():
        value = str(config.get(key) or "")
        if value:
            argv += [flag, value]
    credential = {
        k: config[k] for k in spec.get("credential", [])
        if config.get(k) not in (None, "")
    }
    return argv, credential


def auth_spec_for(binary: str) -> NodeTypeSpec:
    """One node type per plugin covering identity and environment management."""
    outputs: dict[str, PortDefinition] = {}
    for verb in VERBS.values():
        for name, data_type, description in verb["outputs"]:
            outputs.setdefault(name, PortDefinition(
                name=name, data_type=data_type, description=description))

    return NodeTypeSpec(
        component_type=component_type_for(binary),
        display_name=f"{binary} · identity",
        description=(
            f"Identity and environment management for the {binary} binary: log in, "
            f"refresh, list and forget sessions, register environments. Credentials "
            f"are held by the binary — this platform stores none of its own."
        ),
        category="action",
        inputs=[PortDefinition(name="input", data_type=DataType.ANY, required=False,
                               description="Optional upstream value; parameters come from config")],
        outputs=list(outputs.values()),
        config_schema={
            "type": "object",
            "properties": {
                "operation": {"type": "string", "title": "Operation", "enum": sorted(VERBS)},
            },
            "required": ["operation"],
            "x-binary": binary,
            VERB_MARKER: True,
            "x-operations": {
                verb_id: {
                    "summary": verb["summary"],
                    "params": verb["params"],
                    # Verbs establish identity rather than consuming one, so the
                    # session picker must not be offered: `session` here is a
                    # handle being written, not one being chosen.
                    "session_required": False,
                    "timeout_default_s": 60,
                    "outputs": [name for name, _, _ in verb["outputs"]],
                }
                for verb_id, verb in VERBS.items()
            },
        },
    )

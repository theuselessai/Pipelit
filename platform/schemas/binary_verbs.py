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

The verb SURFACE is fixed; two of the objects it carries are not. What
establishes an identity (`auth login`'s `credential`) and what an environment
record holds (`env add`) genuinely differ per binary, which is why the contract
keeps both opaque and lets a catalog describe them (`credential_schema`,
`env_schema`). A host that hardcodes a guess renders a form with no field for
the thing the binary requires, and the operator cannot log in at all — so this
table's entries for those two verbs are FALLBACKS, used only when a binary
declares nothing, and `compose_verbs` splices in whatever it does declare.
"""

from __future__ import annotations

import logging
from typing import Any

from schemas.node_types import DataType, NodeTypeSpec, PortDefinition

logger = logging.getLogger(__name__)

# Marks a node type as driven by this table rather than by a catalog.
VERB_MARKER = "x-verbs"

# Whether each verb changes state observable outside the binary. Unlike an
# operation's `mutates`, which comes from the binary's own catalog, verbs are
# fixed by the protocol rather than declared per-binary — so their mutation
# status is fixed here too, in this one place, rather than being re-derived or
# guessed at each call site. `auth.login`, `auth.refresh` and
# `auth.sessionRemove` change what identity the binary holds; `env.add` and
# `env.remove` change what environments it knows. `auth.sessionList` and
# `env.list` only read that state back.
MUTATING_VERBS = frozenset({
    "auth.login", "auth.refresh", "auth.sessionRemove", "env.add", "env.remove",
})

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
        # `credential` and the non-fixed params here are the FALLBACK, for a
        # binary that declares no `credential_schema`. `compose_verbs` replaces
        # them wholesale with whatever a binary does declare.
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
        # `flags` and the non-fixed params are the FALLBACK for a binary whose
        # `env_schema` is unresolvable — normally it is not, since registration
        # requires one, and `compose_verbs` builds these from it instead.
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


# Verb parameters that are protocol-level rather than binary-declared: `env`
# and `session` on login are the global flags the protocol fixes, `name` on
# `env add` is the positional its verb line fixes. Composition keeps these
# exactly and splices the binary's declared fields in beside them. A declared
# property that collides with one of these — or with the platform's own config
# keys — is skipped, the same way catalog operations skip colliding parameters.
_FIXED_PARAMS: dict[str, tuple[str, ...]] = {
    "auth.login": ("env", "session"),
    "env.add": ("name",),
}


def _declared_properties(schema: Any, verb_id: str) -> dict[str, Any] | None:
    """The usable properties a binary declared for one verb, or None.

    None sends the caller to the fallback entry, and covers "declared nothing"
    as well as "declared nothing usable" (not an object, no properties, or
    every property colliding with a platform key). Falling back on a
    fully-colliding schema is the lesser wrong: composing an empty form would
    leave the operator with nothing to fill in at all.
    """
    if not isinstance(schema, dict) or not isinstance(schema.get("properties"), dict):
        return None
    from schemas.binary_catalogs import RESERVED_CONFIG_KEYS

    reserved = RESERVED_CONFIG_KEYS.union(_FIXED_PARAMS[verb_id])
    properties = {k: v for k, v in schema["properties"].items() if k not in reserved}
    colliding = sorted(set(schema["properties"]) - set(properties))
    if colliding:
        logger.error(
            "a declared schema for %s names %s, which the platform reserves — skipping",
            verb_id, ", ".join(colliding),
        )
    return properties or None


def _compose_entry(verb_id: str, declared: dict[str, Any] | None) -> dict[str, Any]:
    """One verb entry with the binary's declared fields spliced in.

    The declared property specs pass through untouched, so `"secret": true`
    survives to the form and to anything else that must mask the value. How the
    fields travel differs per verb — login's go on stdin (`credential`), an
    environment record's go as verb-scoped flags, exactly where the fallback
    fields travel today.
    """
    base = VERBS[verb_id]
    properties = _declared_properties(declared, verb_id)
    if properties is None:
        return base
    fixed = _FIXED_PARAMS[verb_id]
    entry = {
        **base,
        "params": {
            "type": "object",
            "required": [
                *fixed,
                *(r for r in ((declared or {}).get("required") or []) if r in properties),
            ],
            "properties": {
                **{k: base["params"]["properties"][k] for k in fixed},
                **properties,
            },
        },
    }
    if verb_id == "auth.login":
        entry["credential"] = list(properties)
    else:
        entry["flags"] = {key: f"--{key}" for key in properties}
    return entry


def compose_verbs(
    credential_schema: dict[str, Any] | None = None,
    env_schema: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """The verb table, with the parts a binary may declare filled in.

    A binary that declares neither schema gets the fallback entries unchanged —
    absence means "not describing it", never "nothing needed". The other verbs
    are protocol-fixed all the way down and pass through untouched.
    """
    verbs = dict(VERBS)
    verbs["auth.login"] = _compose_entry("auth.login", credential_schema)
    verbs["env.add"] = _compose_entry("env.add", env_schema)
    return verbs


def verbs_for(binary: str, catalog_dir=None) -> dict[str, dict[str, Any]]:
    """The verb table as it applies to ONE binary, from its pinned catalog.

    Resolved per call, like every other catalog question, so a catalog
    registered into a running process is honoured on the next call. An
    unresolvable binary composes nothing and gets the fallback table.
    """
    from schemas.binary_catalogs import credential_schema_for, env_schema_for

    return compose_verbs(
        credential_schema_for(binary, catalog_dir),
        env_schema_for(binary, catalog_dir),
    )


def build_argv(
    verb_id: str, config: dict, verbs: dict[str, dict[str, Any]] | None = None
) -> tuple[list[str], dict]:
    """Return (argv fragment, credential object) for one verb.

    Global flags precede the verb; positionals and verb-scoped flags follow it.
    Credential values never reach argv — a process's command line is readable by
    other processes for the life of the call. `verbs` is a composed table from
    `verbs_for`/`compose_verbs`; without one the fallback table drives, which is
    correct only for a binary that declares nothing.
    """
    spec = (verbs or VERBS)[verb_id]
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


def verb_operations(
    verbs: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """The `x-operations` sidecar for a verb table.

    Static (fallback) by default; hand it a composed table from `verbs_for` to
    get the sidecar as it applies to one binary. Shared by the node type spec
    and by design-time validation, so the form and the validator cannot
    disagree about what a verb requires.
    """
    return {
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
        for verb_id, verb in (verbs or VERBS).items()
    }


def auth_spec() -> NodeTypeSpec:
    """The single static identity node type, `binary_auth`.

    One node type serves every plugin: the verb surface is protocol-defined, so
    it is identical whichever binary the node names. Which binary that is lives
    in the node's own config (`extra_config["binary"]`), never in the type.
    """
    outputs: dict[str, PortDefinition] = {}
    for verb in VERBS.values():
        for name, data_type, description in verb["outputs"]:
            outputs.setdefault(name, PortDefinition(
                name=name, data_type=data_type, description=description))

    return NodeTypeSpec(
        component_type="binary_auth",
        display_name="Binary Identity",
        description=(
            "Identity and environment management for a binary plugin: log in, "
            "refresh, list and forget sessions, register environments. Credentials "
            "are held by the binary — this platform stores none of its own."
        ),
        category="action",
        inputs=[PortDefinition(name="input", data_type=DataType.ANY, required=False,
                               description="Optional upstream value; parameters come from config")],
        outputs=list(outputs.values()),
        config_schema={
            "type": "object",
            "properties": {
                "binary": {
                    "type": "string",
                    "title": "Binary",
                    "description": "Name of the registered binary this node manages identities for.",
                },
                "operation": {"type": "string", "title": "Operation", "enum": sorted(VERBS)},
            },
            "required": ["binary", "operation"],
            VERB_MARKER: True,
            # The FALLBACK sidecar: the spec is per-type and the composition is
            # per-binary, so the login and env.add entries here are what a
            # binary that declares nothing gets. The frontend re-composes per
            # node from the catalog listing; the component and the validator
            # compose via `verbs_for`.
            "x-operations": verb_operations(),
        },
    )

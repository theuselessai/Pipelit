"""Fold catalog-derived component types into the static binary_op / binary_auth

Every (binary, domain) pair and every binary's auth surface used to be its own
polymorphic identity, synthesised at import from the machine's catalog files.
This revision rewrites those rows to the two STATIC types and moves the binary
into node data: `extra_config["binary"]` (plus `"domain"` for operation rows),
so migrated nodes are shaped identically to palette-created ones.

The old->new enumeration is built AT RUNTIME from this machine's registration
records (catalogs/registrations/*.plugin.json) and catalog files
(catalogs/*.json), by EQUALITY against the exact names the old code derived
(`f"{binary}_{domain}".replace("-", "_")` / `f"{binary}_auth".replace("-", "_")`).
It never pattern-matches "looks derived" — the naming rule strips hyphens and is
lossy, so a pattern would be both over- and under-inclusive. Names longer than
30 characters are skipped (they never registered: component_type is String(30)
and the old loader refused them), as is any name colliding with a built-in type.

Rollback caveats (record kept per the plan's "Migration rollback note"):

1. `downgrade()` needs the SAME registrations/catalogs present that `upgrade()`
   used: it reverses via `extra_config["binary"]`, resolving an operation row's
   domain through the binary's catalog when the row carries no `"domain"` key.
   On a machine without them, affected rows are left as binary_op/binary_auth
   with a warning — they are then unloadable under the OLD code, which is the
   pre-existing absent-catalog failure, not a new one.
2. A DB restored from another machine may hold derived names this machine's
   enumeration cannot claim. `upgrade()` leaves them untouched and warns; they
   were already unloadable without their catalog.

Take a file copy of the sqlite DB before upgrading in any environment that
matters. No DDL here: values change, the schema does not (`component_type`
stays String(30) on both columns; no batch_alter_table).

Revision ID: c4b1a9e0f2d3
Revises: 3870bee8886b
Create Date: 2026-08-18
"""
from __future__ import annotations

import json
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "c4b1a9e0f2d3"
down_revision = "3870bee8886b"
branch_labels = None
depends_on = None

# platform/alembic/versions/<this file> -> parents[2] == platform/
_PLATFORM_DIR = Path(__file__).resolve().parents[2]
CATALOG_DIR = _PLATFORM_DIR / "catalogs"
REGISTRATION_DIR = CATALOG_DIR / "registrations"

MAX_COMPONENT_TYPE = 30

# Frozen snapshot of the built-in component types as of this revision. The
# enumeration below must never claim one of these — in particular
# mailbox_action and the trigger_* types are built-ins, not derived names.
STATIC_COMPONENT_TYPES = frozenset({
    "categorizer", "router", "extractor", "ai_model", "agent", "deep_agent",
    "switch", "assertion", "run_command", "get_totp_code", "platform_api",
    "whoami", "spawn_and_await", "workflow_create", "workflow_discover",
    "scheduler_tools", "system_health", "human_confirmation", "workflow",
    "code", "code_execute", "loop", "wait", "merge", "filter", "error_handler",
    "output_parser", "memory_read", "memory_write", "identify_user",
    "trigger_telegram", "trigger_schedule", "trigger_manual",
    "trigger_workflow", "trigger_error", "trigger_chat", "reply_chat", "skill",
    "validate_gherkin", "validate_topology", "mailbox_action", "mailbox_parse",
    "binary_op", "binary_auth",
})


def _read_json(path: Path) -> dict | None:
    try:
        doc = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  ⚠  {path.name} is unreadable, skipping: {exc}")
        return None
    return doc if isinstance(doc, dict) else None


def _read_catalog(path: Path) -> dict | None:
    """One catalog document — bare or still inside its stdout envelope."""
    doc = _read_json(path)
    if doc is None:
        return None
    if isinstance(doc.get("data"), dict) and "operations" in doc["data"]:
        doc = doc["data"]
    if "binary" not in doc or not isinstance(doc.get("operations"), list):
        return None
    return doc


def _catalog_by_binary() -> dict[str, dict]:
    catalogs: dict[str, dict] = {}
    if CATALOG_DIR.is_dir():
        for path in sorted(CATALOG_DIR.glob("*.json")):
            doc = _read_catalog(path)
            if doc is not None:
                catalogs[doc["binary"]] = doc
    return catalogs


def _registered_binaries() -> set[str]:
    binaries: set[str] = set()
    if REGISTRATION_DIR.is_dir():
        for path in sorted(REGISTRATION_DIR.glob("*.plugin.json")):
            reg = _read_json(path)
            if reg is None:
                continue
            binary = reg.get("binary") or path.name.removesuffix(".plugin.json")
            binaries.add(binary)
    return binaries


def _claim(mapping: dict, old_name: str, new_type: str, binary: str, domain: str | None) -> None:
    if len(old_name) > MAX_COMPONENT_TYPE:
        # The old loader refused names over 30 chars, so no row can carry one.
        return
    if old_name in STATIC_COMPONENT_TYPES:
        print(
            f"  ⚠  derived name {old_name!r} (binary {binary!r}) collides with a "
            f"built-in component type — NOT migrating it"
        )
        return
    mapping[old_name] = (new_type, binary, domain)


def _enumerate_old_types() -> dict[str, tuple[str, str, str | None]]:
    """old component_type -> (new component_type, binary, domain-or-None).

    Built from THIS machine's registrations and catalogs: the union of both,
    because the old loader derived types from any readable catalog file whether
    or not a registration record accompanied it.
    """
    catalogs = _catalog_by_binary()
    mapping: dict[str, tuple[str, str, str | None]] = {}
    for binary in sorted(_registered_binaries() | set(catalogs)):
        _claim(mapping, f"{binary}_auth".replace("-", "_"), "binary_auth", binary, None)
        doc = catalogs.get(binary)
        if doc is None:
            print(
                f"  ⚠  {binary} has a registration record but no readable catalog — "
                f"its operation node types (if any rows exist) cannot be enumerated"
            )
            continue
        domains = sorted({op["domain"] for op in doc["operations"] if isinstance(op, dict) and "domain" in op})
        for domain in domains:
            _claim(mapping, f"{binary}_{domain}".replace("-", "_"), "binary_op", binary, domain)
    return mapping


def _load_extra(raw) -> dict:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = None
    return raw if isinstance(raw, dict) else {}


def _warn_unclaimed(conn) -> None:
    """Loudly name every component_type that is neither static nor claimed."""
    for table in ("workflow_nodes", "component_configs"):
        rows = conn.execute(
            sa.text(f"SELECT DISTINCT component_type FROM {table}")
        ).fetchall()
        for (value,) in rows:
            if value not in STATIC_COMPONENT_TYPES and value != "__base__":
                print(
                    f"  ⚠  {table} still holds component_type {value!r}, which is "
                    f"neither a built-in nor binary_op/binary_auth. This machine's "
                    f"catalogs cannot claim it; the row is left untouched and is "
                    f"exactly as unloadable as it was before this migration."
                )


def upgrade() -> None:
    conn = op.get_bind()
    mapping = _enumerate_old_types()
    if not mapping:
        print("  no registrations or catalogs on this machine — nothing to enumerate")
        _warn_unclaimed(conn)
        return

    old_names = sorted(mapping)
    placeholders = ", ".join(f":t{i}" for i in range(len(old_names)))
    bind = {f"t{i}": name for i, name in enumerate(old_names)}

    # Rewrite the config rows first: type AND the binary/domain keys, so a
    # migrated node is shaped identically to a palette-created one.
    rows = conn.execute(
        sa.text(
            f"SELECT id, component_type, extra_config FROM component_configs "
            f"WHERE component_type IN ({placeholders})"
        ),
        bind,
    ).fetchall()
    for cfg_id, old_type, raw_extra in rows:
        new_type, binary, domain = mapping[old_type]
        extra = _load_extra(raw_extra)
        extra["binary"] = binary
        if domain is not None:
            extra["domain"] = domain
        conn.execute(
            sa.text(
                "UPDATE component_configs SET component_type = :new, extra_config = :extra "
                "WHERE id = :id"
            ),
            {"new": new_type, "extra": json.dumps(extra), "id": cfg_id},
        )
        print(f"  component_configs #{cfg_id}: {old_type} -> {new_type} (binary={binary})")

    # Then the node rows, by equality on the same enumerated names.
    for old_type in old_names:
        new_type = mapping[old_type][0]
        result = conn.execute(
            sa.text(
                "UPDATE workflow_nodes SET component_type = :new WHERE component_type = :old"
            ),
            {"new": new_type, "old": old_type},
        )
        if result.rowcount:
            print(f"  workflow_nodes: {result.rowcount} row(s) {old_type} -> {new_type}")

    _warn_unclaimed(conn)


def downgrade() -> None:
    conn = op.get_bind()
    catalogs = _catalog_by_binary()

    rows = conn.execute(
        sa.text(
            "SELECT id, component_type, extra_config FROM component_configs "
            "WHERE component_type IN ('binary_op', 'binary_auth')"
        )
    ).fetchall()

    for cfg_id, cur_type, raw_extra in rows:
        extra = _load_extra(raw_extra)
        binary = extra.get("binary")
        if not binary:
            print(
                f"  ⚠  component_configs #{cfg_id} ({cur_type}) has no "
                f"extra_config['binary'] — cannot derive its old name; leaving it"
            )
            continue

        if cur_type == "binary_auth":
            old_type = f"{binary}_auth".replace("-", "_")
        else:
            domain = extra.get("domain")
            if not domain:
                # Resolve the configured operation's domain through the catalog.
                doc = catalogs.get(binary)
                operation = extra.get("operation")
                if doc is not None and operation:
                    domain = next(
                        (o.get("domain") for o in doc["operations"]
                         if isinstance(o, dict) and o.get("id") == operation),
                        None,
                    )
            if not domain:
                print(
                    f"  ⚠  component_configs #{cfg_id} (binary_op, binary={binary!r}) — "
                    f"no domain on the row and none resolvable from this machine's "
                    f"catalogs; leaving it as binary_op"
                )
                continue
            old_type = f"{binary}_{domain}".replace("-", "_")

        if len(old_type) > MAX_COMPONENT_TYPE:
            print(
                f"  ⚠  old name {old_type!r} exceeds {MAX_COMPONENT_TYPE} chars and "
                f"could never have existed; leaving component_configs #{cfg_id}"
            )
            continue

        # Remove the keys upgrade added, restore the old discriminator.
        extra.pop("binary", None)
        extra.pop("domain", None)
        conn.execute(
            sa.text(
                "UPDATE component_configs SET component_type = :old, extra_config = :extra "
                "WHERE id = :id"
            ),
            {"old": old_type, "extra": json.dumps(extra), "id": cfg_id},
        )
        conn.execute(
            sa.text(
                "UPDATE workflow_nodes SET component_type = :old "
                "WHERE component_config_id = :cid AND component_type = :cur"
            ),
            {"old": old_type, "cid": cfg_id, "cur": cur_type},
        )
        print(f"  component_configs #{cfg_id}: {cur_type} -> {old_type}")

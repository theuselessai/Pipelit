"""Binary plugins: discovery, integrity, and registration records.

A *plugin* is a directory containing an executable that implements the
bin-contract protocol, plus a `plugin.json` saying how to run it. Installing one
is dropping the directory into the plugins directory; there is no per-binary
configuration to edit and no curated list of approved binaries.

Two rules hold that together.

**A node names a plugin; it never carries a command.** The name is resolved here,
against the plugins directory, and a name containing a path separator is refused.
Without that, editing a node would be running arbitrary code — and in this
platform agents create nodes (`workflow_create`, `spawn_and_await`), so "whoever
can edit a node" includes anything that can steer an agent.

**A plugin runs only if it still hashes to what passed conformance.** Conformance
is checked once, at registration, and it necessarily runs the binary to do so —
so the verdict has to be bound to the thing it was a verdict about, or passing
once and swapping the file afterwards defeats the whole gate. The checksum covers
the plugin's whole directory, because hashing one entry file says nothing about
the tree it imports.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from config import BASE_DIR

logger = logging.getLogger(__name__)

PLUGIN_DIR = Path(os.environ.get("PLIT_PLUGIN_DIR") or Path(BASE_DIR) / "plugins")
# Deliberately NOT beside the catalogs: the node-type loader globs *.json there,
# and a registration record is not a catalog. Two kinds of document in one
# directory means each loader has to recognise the other's files to ignore them.
REGISTRATION_DIR = Path(BASE_DIR) / "catalogs" / "registrations"
MANIFEST_NAME = "plugin.json"


class PluginError(RuntimeError):
    """A plugin could not be resolved, verified, or run."""


@dataclass(frozen=True)
class Plugin:
    name: str
    directory: Path
    argv: list[str]

    @property
    def manifest_path(self) -> Path:
        return self.directory / MANIFEST_NAME


@dataclass(frozen=True)
class Registration:
    """What was recorded when a plugin passed conformance."""

    binary: str
    plugin: str
    argv: list[str]
    checksum: str
    fingerprint: str
    catalog_hash: str
    registered_at: str
    dev_mode: bool = False


def _safe_name(name: str) -> str:
    """Reject anything that could escape the plugins directory.

    The name arrives from node configuration, so it is caller-controlled. A
    plugin called `../../usr/bin` must not resolve.
    """
    if not name or name != Path(name).name or name in (".", ".."):
        raise PluginError(f"invalid plugin name: {name!r}")
    return name


def tree_checksum(directory: Path) -> str:
    """SHA-256 over every file in the tree, by relative path.

    Hashing `(path, content)` pairs rather than contents alone means a rename or
    a deletion moves the checksum too — a tree that merely has the same bytes
    somewhere else is not the same tree.
    """
    digest = hashlib.sha256()
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        rel = path.relative_to(directory).as_posix()
        digest.update(rel.encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return "sha256:" + digest.hexdigest()


def tree_fingerprint(directory: Path) -> str:
    """A cheap stand-in for the checksum: count, sizes and mtimes.

    Re-hashing a whole tree before every invocation is too expensive, and
    skipping the check entirely is how the checksum becomes decorative. This is
    the fast path — if the fingerprint matches, nothing has been written since
    registration and the checksum cannot have moved; if it differs, the full
    hash runs. It is a cache key, never evidence on its own.
    """
    parts = []
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        stat = path.stat()
        parts.append(f"{path.relative_to(directory).as_posix()}:{stat.st_size}:{stat.st_mtime_ns}")
    return "fp:" + hashlib.sha256("\n".join(parts).encode()).hexdigest()


def read_manifest(directory: Path) -> list[str]:
    """The argv a plugin declares for itself, relative to its own directory."""
    path = directory / MANIFEST_NAME
    try:
        manifest = json.loads(path.read_text())
    except FileNotFoundError:
        raise PluginError(f"{directory.name} has no {MANIFEST_NAME}") from None
    except (OSError, json.JSONDecodeError) as exc:
        raise PluginError(f"{directory.name}/{MANIFEST_NAME} is unreadable: {exc}") from None

    argv = manifest.get("exec")
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
        raise PluginError(f"{directory.name}/{MANIFEST_NAME} needs an \"exec\" array of strings")
    return argv


def resolve(name: str, plugin_dir: Path | None = None) -> Plugin:
    """Find an installed plugin by name and read how to run it."""
    root = plugin_dir or PLUGIN_DIR
    directory = root / _safe_name(name)
    if not directory.is_dir():
        raise PluginError(f"no plugin named {name!r} in {root}")

    argv = read_manifest(directory)
    # The first element is the program. Anything that looks like a path is
    # resolved inside the plugin, so a manifest cannot reach out of its own
    # directory to name an interpreter-adjacent script elsewhere.
    resolved = list(argv)
    for i, part in enumerate(resolved[1:], start=1):
        candidate = directory / part
        if candidate.exists():
            resolved[i] = str(candidate)
    return Plugin(name=directory.name, directory=directory, argv=resolved)


def installed(plugin_dir: Path | None = None) -> list[str]:
    root = plugin_dir or PLUGIN_DIR
    if not root.is_dir():
        return []
    return sorted(d.name for d in root.iterdir() if (d / MANIFEST_NAME).is_file())


def registration_path(binary: str) -> Path:
    return REGISTRATION_DIR / f"{binary}.plugin.json"


def read_registration(binary: str) -> Registration:
    path = registration_path(binary)
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        raise PluginError(
            f"{binary} is not registered. Run scripts/register_plugin.py <name>."
        ) from None
    except (OSError, json.JSONDecodeError) as exc:
        raise PluginError(f"registration for {binary} is unreadable: {exc}") from None
    return Registration(**data)


def write_registration(reg: Registration) -> Path:
    REGISTRATION_DIR.mkdir(parents=True, exist_ok=True)
    path = registration_path(reg.binary)
    path.write_text(json.dumps(reg.__dict__, indent=2, sort_keys=True) + "\n")
    return path


def verified_plugin(binary: str, plugin_dir: Path | None = None) -> tuple[Plugin, Registration]:
    """Resolve a registered binary and prove it is what passed conformance.

    Refuses rather than re-registering. A mismatch means the code changed since
    it was tested, and quietly accepting the new code would make the check
    decorative — the same failure as a conformance suite that skips instead of
    failing.
    """
    reg = read_registration(binary)
    plugin = resolve(reg.plugin, plugin_dir)

    if reg.dev_mode:
        logger.warning(
            "plugin %s runs in DEV MODE: its integrity is not checked, so what runs "
            "need not be what passed conformance",
            reg.plugin,
        )
        return plugin, reg

    if tree_fingerprint(plugin.directory) == reg.fingerprint:
        return plugin, reg

    # The cheap check moved, so something was written. Only the real hash can say
    # whether the bytes actually differ — a rebuild that produced identical files
    # is not a change.
    actual = tree_checksum(plugin.directory)
    if actual != reg.checksum:
        raise PluginError(
            f"{plugin.name} has changed since it was registered "
            f"({actual[:19]}… is not {reg.checksum[:19]}…). What would run is not what "
            f"passed conformance. Re-register it."
        )
    return plugin, reg


@dataclass(frozen=True)
class DriftEntry:
    """One saved `binary_op` node whose configured operation was affected by a
    catalog re-registration."""

    workflow_slug: str
    node_id: str
    operation: str
    change: str  # "operation_removed" | "output_ports_lost"
    detail: str


def saved_binary_op_nodes(db, binary: str) -> list[tuple[str, str, dict]]:
    """Every saved `binary_op` node naming `binary`, as (workflow_slug, node_id, extra_config).

    Ports are never snapshotted on the node (decision 2), so the only way to
    know what a saved node is depending on is to look at what it configured —
    its `extra_config["operation"]` — against the catalogs that come and go.
    """
    from models.node import BaseComponentConfig, WorkflowNode
    from models.workflow import Workflow

    rows = (
        db.query(WorkflowNode, Workflow.slug, BaseComponentConfig)
        .join(Workflow, Workflow.id == WorkflowNode.workflow_id)
        .join(BaseComponentConfig, BaseComponentConfig.id == WorkflowNode.component_config_id)
        .filter(WorkflowNode.component_type == "binary_op")
        .all()
    )
    return [
        (slug, wf_node.node_id, config.extra_config or {})
        for wf_node, slug, config in rows
        if (config.extra_config or {}).get("binary") == binary
    ]


def detect_drift(
    db, binary: str, previous_catalog: dict | None, new_catalog: dict
) -> list[DriftEntry]:
    """Saved `binary_op` nodes whose configured operation was hit by re-registering `binary`.

    Compares the catalog that is about to be REPLACED against the one that is
    about to replace it, for every saved node naming this binary. Two ways a
    node's configured operation is affected: it no longer exists at all, or it
    still exists but no longer declares one of the output ports the node was
    relying on (a strict subset check — new ports appearing is not drift).

    This is a REPORT, not a gate — re-registration is already a deliberate act
    (decision 2), and blocking it here would make an operator's fix for a bad
    catalog contingent on first fixing every workflow that referenced it. The
    pin that actually protects a running node is the catalog FILE itself: it
    only changes here, on deliberate re-registration, never underneath a node
    by a binary upgrade.
    """
    if not previous_catalog:
        return []

    old_ops = {op["id"]: op for op in previous_catalog.get("operations", []) if op.get("id")}
    new_ops = {op["id"]: op for op in new_catalog.get("operations", []) if op.get("id")}

    entries: list[DriftEntry] = []
    for slug, node_id, extra in saved_binary_op_nodes(db, binary):
        operation = extra.get("operation")
        if not operation or operation not in old_ops:
            # Nothing this node was actually relying on to compare — either it
            # never had a resolvable operation, or it named one the OLD
            # catalog didn't offer either (already broken before this call).
            continue

        if operation not in new_ops:
            entries.append(DriftEntry(
                workflow_slug=slug, node_id=node_id, operation=operation,
                change="operation_removed",
                detail=f"operation {operation!r} no longer exists in {binary}'s catalog",
            ))
            continue

        old_outputs = {o["name"] for o in old_ops[operation].get("outputs", []) if o.get("name")}
        new_outputs = {o["name"] for o in new_ops[operation].get("outputs", []) if o.get("name")}
        lost = sorted(old_outputs - new_outputs)
        if lost:
            entries.append(DriftEntry(
                workflow_slug=slug, node_id=node_id, operation=operation,
                change="output_ports_lost",
                detail=f"operation {operation!r} lost output port(s): {', '.join(lost)}",
            ))

    return entries

#!/usr/bin/env python3
"""Register a binary plugin: check it, pin it, and write its catalog.

    python scripts/register_plugin.py <plugin-name>
    python scripts/register_plugin.py <plugin-name> --dev

A plugin is a directory under the plugins directory containing an executable and
a `plugin.json` that says how to run it. Registration runs `<bin> catalog`,
checks the document is one this platform can use, records a checksum of the
plugin's whole tree, and writes the catalog that node types are derived from.

Nothing here is a security check. Testing a binary means running it, so the first
execution always precedes the verdict; what this establishes is that the binary
behaves, and the checksum is what binds that verdict to the code it was about.
Whether a binary is *safe* to install is decided by whoever can write to the
plugins directory.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from schemas.binary_catalogs import CATALOG_DIR  # noqa: E402
from services.plugins import (  # noqa: E402
    PLUGIN_DIR,
    PluginError,
    Registration,
    detect_drift,
    installed,
    resolve,
    tree_checksum,
    tree_fingerprint,
    write_registration,
)

REQUIRED_ENVELOPE_KEYS = ("ok", "data", "proof", "slot_patch", "error")
REQUIRED_CATALOG_KEYS = (
    "protocol", "binary", "version", "generated_from", "catalog_hash",
    "env_schema", "operations",
)
REQUIRED_OPERATION_KEYS = (
    "id", "domain", "summary", "session", "params", "outputs", "timeout_default_s",
)


def conform(stdout: str, returncode: int) -> tuple[dict, list[str]]:
    """Check what the binary printed. Returns (catalog, failures)."""
    failures: list[str] = []

    if returncode != 0:
        failures.append(f"`catalog` exited {returncode}; it must succeed without configuration")

    # Exactly one JSON object on stdout, and nothing else. Parsed as a whole
    # stream rather than a line, so a binary that also logs to stdout fails here
    # instead of yielding a document that happens to parse.
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return {}, [f"stdout is not exactly one JSON object: {exc}"]

    if not isinstance(envelope, dict):
        return {}, ["stdout is JSON, but not an object"]

    missing = [k for k in REQUIRED_ENVELOPE_KEYS if k not in envelope]
    if missing:
        failures.append(f"envelope is missing {', '.join(missing)}")
    if envelope.get("ok") is not True:
        failures.append(f"envelope reports failure: {envelope.get('error')}")

    catalog = envelope.get("data")
    if not isinstance(catalog, dict):
        return {}, failures + ["envelope carries no catalog document in `data`"]

    if catalog.get("protocol") != 1:
        # Refuse the whole document rather than the operations we recognise: a
        # partially understood surface is how a caller ends up invoking an
        # operation whose meaning has changed.
        return catalog, failures + [
            f"protocol is {catalog.get('protocol')!r}, not 1 — refusing the whole catalog"
        ]

    for key in REQUIRED_CATALOG_KEYS:
        if key not in catalog:
            failures.append(f"catalog is missing {key!r}")

    operations = catalog.get("operations")
    if not isinstance(operations, list) or not operations:
        failures.append("catalog declares no operations")
        return catalog, failures

    seen: set[str] = set()
    for op in operations:
        oid = op.get("id", "<unnamed>")
        for key in REQUIRED_OPERATION_KEYS:
            if key not in op:
                failures.append(f"operation {oid} is missing {key!r}")
        if oid in seen:
            # JSON Schema cannot express uniqueness over a key, so it is checked
            # here: two operations with one id means `call` is ambiguous.
            failures.append(f"duplicate operation id {oid}")
        seen.add(oid)

    return catalog, failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", nargs="?", help=f"a directory under {PLUGIN_DIR}")
    parser.add_argument("--dev", action="store_true",
                        help="skip integrity verification at call time; for plugin development only")
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()

    if not args.name:
        found = installed()
        print(f"plugins directory: {PLUGIN_DIR}")
        print("installed:", ", ".join(found) if found else "(none)")
        return 0

    try:
        plugin = resolve(args.name)
    except PluginError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    argv = [*plugin.argv, "catalog"]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=args.timeout, cwd=plugin.directory)
    except FileNotFoundError:
        print(f"error: cannot run {plugin.argv[0]!r}", file=sys.stderr)
        return 2
    except subprocess.TimeoutExpired:
        print(f"error: `catalog` did not finish in {args.timeout}s", file=sys.stderr)
        return 2

    catalog, failures = conform(proc.stdout, proc.returncode)
    if failures:
        print(f"{plugin.name} does not conform:", file=sys.stderr)
        for f in failures:
            print(f"  ✗ {f}", file=sys.stderr)
        if proc.stderr.strip():
            print(f"\nstderr:\n{proc.stderr.strip()[:1000]}", file=sys.stderr)
        print("\nnot registered.", file=sys.stderr)
        return 1

    binary = catalog["binary"]
    stamp = catalog["generated_from"]
    if stamp.get("dirty"):
        print(f"⚠  {binary} reports dirty: commit {stamp.get('commit')} names a tree that is "
              f"not what ran. Registering anyway; this build is not identifiable.")

    CATALOG_DIR.mkdir(parents=True, exist_ok=True)
    catalog_path = CATALOG_DIR / f"{binary}.json"
    previous = json.loads(catalog_path.read_text()) if catalog_path.exists() else None
    catalog_path.write_text(json.dumps(catalog, indent=2, sort_keys=True) + "\n")

    reg = Registration(
        binary=binary,
        plugin=plugin.name,
        argv=plugin.argv,
        checksum=tree_checksum(plugin.directory),
        fingerprint=tree_fingerprint(plugin.directory),
        catalog_hash=catalog["catalog_hash"],
        registered_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        dev_mode=bool(args.dev),
    )
    write_registration(reg)

    domains = sorted({op["domain"] for op in catalog["operations"]})
    print(f"registered {binary} from plugin {plugin.name}")
    print(f"  {catalog['version']} @ {stamp.get('commit', '?')[:12]}")
    print(f"  {len(catalog['operations'])} operations across {len(domains)} domains: {', '.join(domains)}")
    print(f"  catalog  {catalog['catalog_hash']}")
    print(f"  code     {reg.checksum}")
    if reg.dev_mode:
        print("  ⚠  DEV MODE: integrity is not verified at call time")

    # binary_op / binary_auth are STATIC component types (registered once, at
    # models/node.py import) — no mapped class is built from a catalog, so no
    # process needs restarting to recognise this binary. Ports are resolved
    # PER NODE from the catalog FILE via schemas.binary_catalogs, cached only
    # by that file's mtime: the server, the scheduler and every worker read it
    # again — and see this registration — on their very next call.
    print("\n  No restart needed: the catalog file is read on demand, per call, "
          "cached only by its own mtime. Already-running processes see this "
          "registration on their next call.")

    if previous:
        # The alarming header is triggered on the COMPUTED DIFF of operation
        # ids, never on catalog_hash inequality by itself. A binary's
        # catalog_hash can cover things that are not the operation surface
        # (e.g. its own build stamp), so a binary that hashes that way
        # changes catalog_hash on every rebuild even when its operations are
        # byte-for-byte identical. Gating the header on the hash alone would
        # then fire it on every single registration with empty added/removed
        # lists — a warning that cries wolf on every rebuild is worse than
        # no warning at all, because it trains people to ignore the one time
        # it matters. This guard must not depend on another binary's hashing
        # discipline, so it depends on the id diff instead. Do not "restore"
        # the hash trigger for the header below.
        was = {op["id"] for op in previous.get("operations", [])}
        now = {op["id"] for op in catalog["operations"]}
        if was != now:
            print("\n  SURFACE CHANGED — saved workflows may reference what is gone:")
            for op in sorted(was - now):
                print(f"    removed  {op}")
            for op in sorted(now - was):
                print(f"    added    {op}")
        elif previous.get("catalog_hash") != catalog["catalog_hash"]:
            # Hash differs, but no operation was added or removed — stay
            # quiet instead of the alarming header above.
            print("\n  catalog rebuilt; operation surface unchanged.")

        # Drift protection lives HERE, at the registration boundary — not on
        # the node (decision 2: ports are derived, never snapshotted). This is
        # a REPORT, never a gate: re-registration is already a deliberate act,
        # and the operator's fix for a bad catalog must not be blocked behind
        # first fixing every workflow that referenced it. Unlike the header
        # above, this does not look at operation ids at all: a port can change
        # WITHIN an operation whose id is unchanged, and a saved node depending
        # on that port still needs to be named regardless of whether the
        # id-level header fired. It runs on every re-registration rather than
        # behind a hash comparison, for the same reason the header does — a
        # binary whose catalog_hash failed to move would otherwise silence
        # BOTH reports at once, which is the failure this guard exists to
        # survive. detect_drift compares content, so an unchanged catalog
        # simply yields nothing.
        from database import SessionLocal

        db = SessionLocal()
        try:
            drift = detect_drift(db, binary, previous, catalog)
        finally:
            db.close()
        if drift:
            print("\n  SAVED NODES AFFECTED — a port one of them depends on changed:")
            for entry in drift:
                print(f"    {entry.workflow_slug} / {entry.node_id}: {entry.detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

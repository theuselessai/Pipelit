#!/usr/bin/env python3
"""Register a binary plugin: check it, pin it, and write its catalog.

    python scripts/register_plugin.py zc-portal-admin
    python scripts/register_plugin.py zc-portal-admin --dev

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

    if previous and previous.get("catalog_hash") != catalog["catalog_hash"]:
        was = {op["id"] for op in previous.get("operations", [])}
        now = {op["id"] for op in catalog["operations"]}
        print("\n  SURFACE CHANGED — saved workflows may reference what is gone:")
        for op in sorted(was - now):
            print(f"    removed  {op}")
        for op in sorted(now - was):
            print(f"    added    {op}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

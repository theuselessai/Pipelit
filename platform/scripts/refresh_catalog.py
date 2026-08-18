#!/usr/bin/env python3
"""Refresh a binary's catalog into platform/catalogs/.

    python scripts/refresh_catalog.py -- node /path/to/bin/main.js
    python scripts/refresh_catalog.py -- zc-portal-admin

Runs `<bin> catalog`, checks the document is one this platform can use, and
writes it to `platform/catalogs/<binary>.json`. Those files are gitignored: a
catalog describes one organisation's operations and this repository is public.

Running the binary is deliberate and manual. Node types must not change
underneath saved workflows just because someone upgraded a binary, so refreshing
is an act someone performs and reviews the result of — the same reason a lockfile
is committed rather than resolved at startup.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

CATALOG_DIR = Path(__file__).resolve().parent.parent / "catalogs"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="+", help="the binary, as you would invoke it")
    parser.add_argument("--dir", type=Path, default=CATALOG_DIR)
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()

    argv = [*args.command, "catalog"]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=args.timeout)
    except FileNotFoundError:
        print(f"not found: {args.command[0]}", file=sys.stderr)
        return 2
    except subprocess.TimeoutExpired:
        print(f"`{' '.join(argv)}` did not finish in {args.timeout}s", file=sys.stderr)
        return 2

    if proc.returncode != 0:
        print(f"`{' '.join(argv)}` exited {proc.returncode}", file=sys.stderr)
        print(proc.stderr.strip()[:2000], file=sys.stderr)
        return proc.returncode

    # The contract says stdout is exactly one JSON object and nothing else, so
    # parse the whole stream rather than a line of it: a binary that also logged
    # to stdout must fail here, not produce a catalog that happens to parse.
    try:
        doc = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        print(f"stdout is not one JSON object: {exc}", file=sys.stderr)
        return 1

    if isinstance(doc.get("data"), dict) and "operations" in doc["data"]:
        if doc.get("ok") is False:
            print(f"binary reported failure: {doc.get('error')}", file=sys.stderr)
            return 1
        doc = doc["data"]

    if doc.get("protocol") != 1:
        print(f"protocol is {doc.get('protocol')!r}, not 1 — refusing", file=sys.stderr)
        return 1
    for key in ("binary", "version", "generated_from", "catalog_hash", "operations"):
        if key not in doc:
            print(f"catalog is missing {key!r}", file=sys.stderr)
            return 1

    stamp = doc["generated_from"]
    if stamp.get("dirty"):
        print(
            f"⚠  {doc['binary']} reports dirty: {stamp.get('commit')} names a tree that is "
            f"not what ran. Refreshing anyway; do not pin this.",
            file=sys.stderr,
        )

    args.dir.mkdir(parents=True, exist_ok=True)
    out = args.dir / f"{doc['binary']}.json"
    previous = json.loads(out.read_text()) if out.exists() else None
    out.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")

    domains = sorted({op["domain"] for op in doc["operations"]})
    print(f"wrote {out}")
    print(f"  {doc['binary']} {doc['version']} @ {stamp.get('commit', '?')[:12]}")
    print(f"  {len(doc['operations'])} operations across {len(domains)} domains: {', '.join(domains)}")
    print(f"  {doc['catalog_hash']}")

    if previous and previous.get("catalog_hash") != doc["catalog_hash"]:
        was = {op["id"] for op in previous.get("operations", [])}
        now = {op["id"] for op in doc["operations"]}
        print("\n  SURFACE CHANGED — saved workflows may reference what is gone:")
        for op in sorted(was - now):
            print(f"    removed  {op}")
        for op in sorted(now - was):
            print(f"    added    {op}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Binary plugins: what is installed, and the identities each one holds.

Read-only. Every response here comes from running the plugin's own read verbs —
`auth session list` and `env list` — because the binary is the only thing that
knows. Neither prints credential material by construction.

These exist so a node can offer a picker instead of a text field. A mistyped
session handle is otherwise an UNKNOWN_SESSION at run time, discovered when the
workflow runs rather than when it is built.
"""

from __future__ import annotations

import json
import logging
import subprocess

from fastapi import APIRouter, Depends, HTTPException

from auth import get_current_user
from models.user import UserProfile
from schemas.binary_catalogs import config_schema_for, credential_schema_for, env_schema_for
from services.plugins import PluginError, installed, read_registration, verified_plugin

logger = logging.getLogger(__name__)

router = APIRouter()

READ_TIMEOUT_S = 30.0


def _run_verb(binary: str, verb: list[str]) -> dict:
    """Run one read-only verb and return its envelope data."""
    try:
        plugin, _ = verified_plugin(binary)
    except PluginError as exc:
        # A plugin that changed since registration, or was never registered, is a
        # configuration problem rather than a bad request.
        raise HTTPException(status_code=409, detail=str(exc)) from None

    try:
        proc = subprocess.run(
            [*plugin.argv, *verb], capture_output=True, text=True,
            timeout=READ_TIMEOUT_S, cwd=plugin.directory,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(status_code=502, detail=f"{binary} did not respond: {exc}") from None

    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=502,
            detail=f"{binary} did not write one JSON object to stdout",
        ) from None

    if not envelope.get("ok"):
        error = envelope.get("error") or {}
        raise HTTPException(status_code=502, detail=error.get("message") or f"{binary} refused")
    return envelope.get("data") or {}


@router.get("/")
def list_plugins(profile: UserProfile = Depends(get_current_user)):
    """Installed plugins, and whether each is registered.

    Installed and registered are different states: a directory can be dropped in
    without having passed conformance, and it cannot be used until it has.
    """
    items = []
    for name in installed():
        entry: dict = {"plugin": name, "registered": False}
        try:
            # The registration is keyed by the binary's own name, which is only
            # knowable from its catalog — so look for one that claims this plugin.
            from services.plugins import REGISTRATION_DIR

            for path in REGISTRATION_DIR.glob("*.plugin.json"):
                reg = read_registration(path.name.removesuffix(".plugin.json"))
                if reg.plugin == name:
                    entry.update(registered=True, binary=reg.binary,
                                 registered_at=reg.registered_at, dev_mode=reg.dev_mode)
                    break
        except PluginError:
            pass
        items.append(entry)
    return {"items": items, "total": len(items)}


@router.get("/catalog/")
def list_catalog(profile: UserProfile = Depends(get_current_user)):
    """Every REGISTERED binary's legacy-shaped config schema.

    Read from the pinned catalog file via the access layer in
    `schemas.binary_catalogs` — NEVER by running the binary. The catalog file is
    the pin; answering an HTTP request by shelling out would defeat that. A
    binary registered mid-process (no restart) is visible on the next call
    because `config_schema_for` re-reads and re-caches by mtime, not at import.

    Unregistered plugin directories are absent. A registered binary whose
    catalog is unreadable still appears, with `schema: null`, rather than
    failing the whole listing.
    """
    # Imported locally, like list_plugins() above, so a REGISTRATION_DIR
    # monkeypatched onto the services.plugins module after this module was
    # imported is still honoured.
    from services.plugins import REGISTRATION_DIR

    items = []
    for path in sorted(REGISTRATION_DIR.glob("*.plugin.json")):
        try:
            reg = read_registration(path.name.removesuffix(".plugin.json"))
        except PluginError:
            continue
        items.append({
            "binary": reg.binary,
            "plugin": reg.plugin,
            "schema": config_schema_for(reg.binary),
            # The catalog's own descriptions of the two objects the protocol
            # keeps opaque: what `auth login` reads as `credential`, and what
            # an environment record holds. Raw, so the frontend can compose the
            # identity node's form from them; null when the binary declares
            # nothing — which for credentials never means "none needed", only
            # that the form falls back to the platform's default fields.
            "credential_schema": credential_schema_for(reg.binary),
            "env_schema": env_schema_for(reg.binary),
        })
    return {"items": items, "total": len(items)}


@router.get("/{binary}/sessions/")
def list_sessions(binary: str, profile: UserProfile = Depends(get_current_user)):
    """Identities this binary holds. Never includes token material."""
    data = _run_verb(binary, ["auth", "session", "list"])
    return {"items": data.get("sessions", []), "unreadable": data.get("unreadable", [])}


@router.get("/{binary}/environments/")
def list_environments(binary: str, profile: UserProfile = Depends(get_current_user)):
    """Environments this binary may be pointed at."""
    data = _run_verb(binary, ["env", "list"])
    return {"items": data.get("envs", data.get("environments", []))}

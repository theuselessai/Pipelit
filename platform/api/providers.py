"""Provider and model management API for agentgateway config.d/ structure.

Admin-only endpoints for managing LLM providers and their models via
the agentgateway filesystem-based configuration.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx
from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_admin
from config import settings
from models.user import UserProfile

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class CreateProviderIn(BaseModel):
    provider: str
    provider_type: str
    api_key: str
    base_url: str = ""


class CreateProviderOut(BaseModel):
    provider: str
    provider_type: str
    models: list[dict]


class ProviderOut(BaseModel):
    provider: str
    provider_type: str
    models: list[dict]


class AddModelsIn(BaseModel):
    models: list[dict]


class AddModelsOut(BaseModel):
    provider: str
    models: list[dict]


class FetchedModel(BaseModel):
    id: str
    name: str


class ModelOut(BaseModel):
    slug: str
    model_name: str
    route: str


# ---------------------------------------------------------------------------
# Guard: AGENTGATEWAY_ENABLED
# ---------------------------------------------------------------------------


def _require_agentgateway():
    """Raise 404 if agentgateway integration is disabled."""
    if not settings.AGENTGATEWAY_ENABLED:
        raise HTTPException(status_code=404, detail="Agentgateway integration is not enabled.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_base_url(base_url: str, provider_type: str) -> tuple[str, str]:
    """Parse base_url into (host_override, path_override) for _provider.yaml.

    Returns (host_override, path_override) with appropriate endpoint suffix.
    """
    if not base_url:
        return "", ""

    parsed = urlparse(base_url.rstrip("/"))
    host = parsed.hostname or ""
    port = parsed.port
    if host and not port:
        port = 443 if parsed.scheme == "https" else 80
    host_override = f"{host}:{port}" if host else ""
    path_override = parsed.path or ""

    # Append endpoint suffix
    if provider_type in ("openai_compatible", "glm", "openai"):
        if path_override and not path_override.endswith("/chat/completions"):
            path_override = path_override.rstrip("/") + "/chat/completions"
    elif provider_type == "anthropic":
        if path_override and not path_override.endswith("/messages"):
            path_override = path_override.rstrip("/") + "/messages"

    return host_override, path_override


ANTHROPIC_MODELS = [
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-sonnet-4-20250514",
    "claude-opus-4-0-20250514",
    "claude-haiku-4-5-20251001",
    "claude-3-5-sonnet-20241022",
]


async def _fetch_provider_models(provider: str) -> list[dict]:
    """Fetch models from a provider using its stored API key."""
    from pathlib import Path

    from services.agentgateway_config import get_provider_config

    agw_dir = Path(settings.AGENTGATEWAY_DIR)
    key_path = agw_dir / "keys" / f"{provider}.key"

    if not key_path.exists():
        raise HTTPException(status_code=404, detail=f"No API key found for provider '{provider}'.")

    # Decrypt API key
    fernet = Fernet(settings.FIELD_ENCRYPTION_KEY.encode())
    api_key = fernet.decrypt(key_path.read_bytes()).decode()

    # Read provider config for base URL
    try:
        config = get_provider_config(provider)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Provider '{provider}' not found.")

    host = config.get("hostOverride", "").replace(":443", "").replace(":80", "")

    # Determine provider type from config
    provider_cfg = config.get("provider", {})
    is_anthropic = "anthropic" in provider_cfg

    if is_anthropic:
        # Anthropic: use hardcoded list (Anthropic /v1/models requires special auth)
        return [{"id": m, "name": m} for m in ANTHROPIC_MODELS]

    # OpenAI-compatible: call /v1/models
    base_host = host or f"api.{provider}.com"
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://{base_host}/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return [{"id": m["id"], "name": m.get("name", m["id"])} for m in data.get("data", [])]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/", status_code=201)
def create_provider(
    payload: CreateProviderIn,
    _admin: UserProfile = Depends(require_admin),
):
    """Create a new provider: write API key, add provider config, reassemble."""
    _require_agentgateway()

    from services.agentgateway_config import (
        add_provider,
        reassemble_config,
        restart_agentgateway,
        write_provider_key,
    )

    host_override, path_override = _parse_base_url(payload.base_url, payload.provider_type)

    try:
        write_provider_key(payload.provider, payload.api_key)
        add_provider(
            provider=payload.provider,
            provider_type=payload.provider_type,
            host_override=host_override,
            path_override=path_override,
        )
        reassemble_config()
        restart_agentgateway()  # New key requires restart to load env var
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return {
        "provider": payload.provider,
        "provider_type": payload.provider_type,
        "models": [],
    }


@router.get("/")
def list_providers_endpoint(
    _admin: UserProfile = Depends(require_admin),
):
    """List all configured providers with their models."""
    _require_agentgateway()

    from services.agentgateway_config import (
        get_provider_config,
        list_models,
        list_providers,
    )

    providers = list_providers()
    result = []
    for p in providers:
        try:
            config = get_provider_config(p)
        except FileNotFoundError:
            continue

        # Determine provider_type from config
        provider_cfg = config.get("provider", {})
        if "anthropic" in provider_cfg:
            provider_type = "anthropic"
        else:
            provider_type = "openai"

        models = list_models(p)
        result.append({
            "provider": p,
            "provider_type": provider_type,
            "models": models,
        })

    return result


@router.delete("/{provider}/", status_code=204)
def delete_provider(
    provider: str,
    _admin: UserProfile = Depends(require_admin),
):
    """Remove a provider and all its models."""
    _require_agentgateway()

    from services.agentgateway_config import remove_provider, restart_agentgateway

    try:
        remove_provider(provider)
        restart_agentgateway()  # Key removed, restart to clean env vars
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/{provider}/fetch-models/")
async def fetch_models(
    provider: str,
    _admin: UserProfile = Depends(require_admin),
):
    """Fetch available models from the provider's API directly."""
    _require_agentgateway()

    try:
        models = await _fetch_provider_models(provider)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Provider API returned {exc.response.status_code}: {exc.response.text[:500]}",
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch models: {exc}")

    return models


@router.post("/{provider}/models/", status_code=201)
def add_models(
    provider: str,
    payload: AddModelsIn,
    _admin: UserProfile = Depends(require_admin),
):
    """Add models to a provider (batch). Reassembles config once at the end."""
    _require_agentgateway()

    from services.agentgateway_config import (
        add_model,
        list_models,
        reassemble_config,
    )

    try:
        for m in payload.models:
            add_model(
                provider=provider,
                model_slug=m["slug"],
                model_name=m["model_name"],
                reassemble=False,
            )

        reassemble_config()
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    models = list_models(provider)
    return {
        "provider": provider,
        "models": models,
    }


@router.delete("/{provider}/models/{model_slug}/", status_code=204)
def delete_model(
    provider: str,
    model_slug: str,
    _admin: UserProfile = Depends(require_admin),
):
    """Remove a single model from a provider."""
    _require_agentgateway()

    from services.agentgateway_config import remove_model

    try:
        remove_model(provider, model_slug)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/{provider}/models/")
def list_models_endpoint(
    provider: str,
    _admin: UserProfile = Depends(require_admin),
):
    """List configured models for a provider."""
    _require_agentgateway()

    from services.agentgateway_config import list_models

    return list_models(provider)

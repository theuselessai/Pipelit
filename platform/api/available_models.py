"""Available models endpoint — read-only list of models from agentgateway config."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from auth import get_current_user
from config import settings
from models.user import UserProfile

available_models_router = APIRouter()


@available_models_router.get("/")
def list_available_models(profile: UserProfile = Depends(get_current_user)):
    """Return available models across all configured providers.

    Reads directly from the agentgateway filesystem config.
    Returns an empty list when AGENTGATEWAY_ENABLED is False.
    """
    if not settings.AGENTGATEWAY_ENABLED:
        return []
    from services.agentgateway_config import list_all_available_models

    return list_all_available_models()

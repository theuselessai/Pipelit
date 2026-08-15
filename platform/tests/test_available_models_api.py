"""Tests for GET /api/v1/available-models/."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

_platform_dir = str(Path(__file__).resolve().parent.parent)
if _platform_dir not in sys.path:
    sys.path.insert(0, _platform_dir)

MOCK_MODELS = [
    {
        "route": "venice-glm-4.7",
        "provider": "venice",
        "model_slug": "glm-4.7",
        "model_name": "zai-org-glm-4.7",
    },
    {
        "route": "venice-deepseek-r1",
        "provider": "venice",
        "model_slug": "deepseek-r1",
        "model_name": "deepseek-r1-0528",
    },
]


@pytest.fixture
def app(db):
    from main import app as _app
    from database import get_db

    def _override_get_db():
        yield db

    _app.dependency_overrides[get_db] = _override_get_db
    yield _app
    _app.dependency_overrides.clear()


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def auth_client(client, api_key):
    client.headers["Authorization"] = f"Bearer {api_key.key}"
    return client


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


def test_requires_authentication(client):
    """GET /available-models/ without a token returns 401 or 403."""
    resp = client.get("/api/v1/available-models/")
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# AGENTGATEWAY_ENABLED=True
# ---------------------------------------------------------------------------


def test_returns_models_when_enabled(auth_client):
    """Returns model list from list_all_available_models() when enabled."""
    with (
        patch("config.settings.AGENTGATEWAY_ENABLED", True),
        patch(
            "services.agentgateway_config.list_all_available_models",
            return_value=MOCK_MODELS,
        ),
    ):
        resp = auth_client.get("/api/v1/available-models/")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 2


def test_response_structure(auth_client):
    """Each item has route, provider, model_slug, model_name keys."""
    with (
        patch("config.settings.AGENTGATEWAY_ENABLED", True),
        patch(
            "services.agentgateway_config.list_all_available_models",
            return_value=MOCK_MODELS,
        ),
    ):
        resp = auth_client.get("/api/v1/available-models/")

    assert resp.status_code == 200
    for item in resp.json():
        assert "route" in item
        assert "provider" in item
        assert "model_slug" in item
        assert "model_name" in item


def test_response_values(auth_client):
    """Response values match what list_all_available_models returns."""
    with (
        patch("config.settings.AGENTGATEWAY_ENABLED", True),
        patch(
            "services.agentgateway_config.list_all_available_models",
            return_value=MOCK_MODELS,
        ),
    ):
        resp = auth_client.get("/api/v1/available-models/")

    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["route"] == "venice-glm-4.7"
    assert data[0]["provider"] == "venice"
    assert data[0]["model_slug"] == "glm-4.7"
    assert data[0]["model_name"] == "zai-org-glm-4.7"
    assert data[1]["route"] == "venice-deepseek-r1"


# ---------------------------------------------------------------------------
# AGENTGATEWAY_ENABLED=False
# ---------------------------------------------------------------------------


def test_returns_empty_list_when_disabled(auth_client):
    """Returns [] when AGENTGATEWAY_ENABLED is False."""
    with patch("config.settings.AGENTGATEWAY_ENABLED", False):
        resp = auth_client.get("/api/v1/available-models/")

    assert resp.status_code == 200
    assert resp.json() == []


def test_does_not_call_filesystem_when_disabled(auth_client):
    """list_all_available_models is never called when gateway is disabled."""
    with (
        patch("config.settings.AGENTGATEWAY_ENABLED", False),
        patch(
            "services.agentgateway_config.list_all_available_models"
        ) as mock_list,
    ):
        resp = auth_client.get("/api/v1/available-models/")

    assert resp.status_code == 200
    mock_list.assert_not_called()

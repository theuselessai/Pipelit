"""Tests for the Settings API endpoints (GET/PATCH /settings/, POST /settings/recheck-environment/)."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# Ensure platform/ is importable
_platform_dir = str(Path(__file__).resolve().parent.parent)
if _platform_dir not in sys.path:
    sys.path.insert(0, _platform_dir)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MOCK_ENVIRONMENT = {
    "os": "Linux",
    "arch": "x86_64",
    "container": None,
    "bwrap_available": True,
    "rootfs_ready": False,
    "sandbox_mode": "bwrap",
    "capabilities": {
        "runtimes": {
            "python3": {"available": True, "version": "Python 3.11.0", "path": "/usr/bin/python3"},
            "node": {"available": True, "version": "v20.0.0", "path": "/usr/bin/node"},
            "pip3": {"available": True, "version": "pip 23.0", "path": "/usr/bin/pip3"},
        },
        "shell_tools": {
            "bash": {"available": True, "tier": 1},
            "python3": {"available": True, "tier": 1},
        },
        "network": {"dns": True, "http": True},
    },
    "tier1_met": True,
    "tier2_warnings": [],
    "gate": {"passed": True, "blocked_reason": None},
}


@pytest.fixture(autouse=True)
def _isolate_pipelit_dir(tmp_path, monkeypatch):
    """Point PIPELIT_DIR to tmp_path so tests never touch the real config."""
    pipelit_dir = tmp_path / "pipelit"
    pipelit_dir.mkdir(parents=True)
    monkeypatch.setenv("PIPELIT_DIR", str(pipelit_dir))


@pytest.fixture(autouse=True)
def _restore_root_log_level():
    """Restore root logger level after tests that hot-reload log_level."""
    original = logging.getLogger().level
    yield
    logging.getLogger().setLevel(original)


@pytest.fixture(autouse=True)
def _clear_capabilities_cache():
    """Reset the capabilities cache before each test."""
    import services.environment as env

    env._cached_capabilities = None
    yield
    env._cached_capabilities = None


@pytest.fixture
def app(db):
    """Create a test FastAPI app with DB overridden to use test session."""
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
# GET /settings/
# ---------------------------------------------------------------------------


def test_get_settings_unauthenticated(client):
    """GET /settings/ without auth returns 401 or 403."""
    resp = client.get("/api/v1/settings/")
    assert resp.status_code in (401, 403)


def test_get_settings_returns_config(auth_client):
    """GET /settings/ returns config and environment."""
    with patch("api.settings._build_environment_cached", return_value=MOCK_ENVIRONMENT):
        resp = auth_client.get("/api/v1/settings/")
    assert resp.status_code == 200
    data = resp.json()
    assert "config" in data
    assert "environment" in data


def test_get_settings_shape(auth_client):
    """Response contains all expected config fields."""
    with patch("api.settings._build_environment_cached", return_value=MOCK_ENVIRONMENT):
        resp = auth_client.get("/api/v1/settings/")
    assert resp.status_code == 200
    config = resp.json()["config"]
    expected_fields = {
        "pipelit_dir", "sandbox_mode", "database_url", "redis_url",
        "log_level", "log_file", "platform_base_url",
        "cors_allow_all_origins", "zombie_execution_threshold_seconds",
    }
    assert expected_fields <= set(config.keys())


def test_get_settings_with_existing_conf(auth_client, tmp_path, monkeypatch):
    """Pre-written conf.json values are reflected in GET response."""
    pipelit_dir = tmp_path / "pipelit"
    pipelit_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PIPELIT_DIR", str(pipelit_dir))

    conf_data = {"sandbox_mode": "container", "log_level": "DEBUG"}
    (pipelit_dir / "conf.json").write_text(json.dumps(conf_data))

    with patch("api.settings._build_environment_cached", return_value=MOCK_ENVIRONMENT):
        resp = auth_client.get("/api/v1/settings/")
    assert resp.status_code == 200
    config = resp.json()["config"]
    assert config["sandbox_mode"] == "container"
    assert config["log_level"] == "DEBUG"


# ---------------------------------------------------------------------------
# PATCH /settings/
# ---------------------------------------------------------------------------


def test_patch_settings_unauthenticated(client):
    """PATCH /settings/ without auth returns 401 or 403."""
    resp = client.patch("/api/v1/settings/", json={"log_level": "DEBUG"})
    assert resp.status_code in (401, 403)


def test_patch_log_level_hot_reload(auth_client, monkeypatch):
    """Patching log_level hot-reloads it and updates conf.json."""
    from config import settings as _settings

    monkeypatch.setattr(_settings, "LOG_LEVEL", _settings.LOG_LEVEL)

    resp = auth_client.patch("/api/v1/settings/", json={"log_level": "DEBUG"})
    assert resp.status_code == 200
    data = resp.json()
    assert "log_level" in data["hot_reloaded"]
    assert "log_level" not in data["restart_required"]
    assert data["config"]["log_level"] == "DEBUG"

    # Verify hot-reload happened
    assert _settings.LOG_LEVEL == "DEBUG"
    assert logging.getLogger().level == logging.DEBUG


def test_patch_zombie_threshold_hot_reload(auth_client, monkeypatch):
    """Patching zombie_execution_threshold_seconds hot-reloads it."""
    from config import settings as _settings

    monkeypatch.setattr(_settings, "ZOMBIE_EXECUTION_THRESHOLD_SECONDS", _settings.ZOMBIE_EXECUTION_THRESHOLD_SECONDS)

    resp = auth_client.patch(
        "/api/v1/settings/",
        json={"zombie_execution_threshold_seconds": 600},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "zombie_execution_threshold_seconds" in data["hot_reloaded"]
    assert data["config"]["zombie_execution_threshold_seconds"] == 600
    assert _settings.ZOMBIE_EXECUTION_THRESHOLD_SECONDS == 600


def test_patch_database_url_restart_required(auth_client):
    """Patching database_url returns it in restart_required."""
    resp = auth_client.patch(
        "/api/v1/settings/",
        json={"database_url": "sqlite:///new.db"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "database_url" in data["restart_required"]
    assert "database_url" not in data["hot_reloaded"]


def test_patch_multiple_fields(auth_client, monkeypatch):
    """Mix of hot-reloadable + restart-required fields."""
    from config import settings as _settings

    monkeypatch.setattr(_settings, "LOG_LEVEL", _settings.LOG_LEVEL)

    resp = auth_client.patch(
        "/api/v1/settings/",
        json={"log_level": "WARNING", "redis_url": "redis://new:6379/0"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "log_level" in data["hot_reloaded"]
    assert "redis_url" in data["restart_required"]


def test_patch_invalid_log_level(auth_client):
    """Invalid log_level returns 422."""
    resp = auth_client.patch("/api/v1/settings/", json={"log_level": "INVALID"})
    assert resp.status_code == 422


def test_patch_negative_zombie_threshold(auth_client):
    """Negative zombie threshold returns 422."""
    resp = auth_client.patch(
        "/api/v1/settings/",
        json={"zombie_execution_threshold_seconds": -1},
    )
    assert resp.status_code == 422


def test_patch_empty_body(auth_client):
    """Empty PATCH body succeeds with no changes."""
    resp = auth_client.patch("/api/v1/settings/", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["hot_reloaded"] == []
    assert data["restart_required"] == []


def test_patch_preserves_unmodified_fields(auth_client, tmp_path, monkeypatch):
    """Only patched fields change; unmodified fields stay the same."""
    pipelit_dir = tmp_path / "pipelit"
    pipelit_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PIPELIT_DIR", str(pipelit_dir))

    from config import save_conf, PipelitConfig

    conf = PipelitConfig(sandbox_mode="bwrap", log_level="INFO", redis_url="redis://orig:6379/0")
    save_conf(conf)

    resp = auth_client.patch("/api/v1/settings/", json={"log_level": "ERROR"})
    assert resp.status_code == 200

    # Re-read conf.json to verify
    from config import load_conf

    updated = load_conf()
    assert updated.log_level == "ERROR"
    assert updated.sandbox_mode == "bwrap"
    assert updated.redis_url == "redis://orig:6379/0"


# ---------------------------------------------------------------------------
# POST /settings/recheck-environment/
# ---------------------------------------------------------------------------


def test_recheck_environment(auth_client):
    """POST recheck-environment returns environment data."""
    with patch("api.settings.refresh_capabilities"), \
         patch("api.settings.build_environment_report", return_value=MOCK_ENVIRONMENT):
        resp = auth_client.post("/api/v1/settings/recheck-environment/")
    assert resp.status_code == 200
    data = resp.json()
    assert "environment" in data
    assert data["environment"]["os"] == "Linux"


def test_recheck_environment_unauthenticated(client):
    """POST recheck-environment without auth returns 401 or 403."""
    resp = client.post("/api/v1/settings/recheck-environment/")
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# URL redaction
# ---------------------------------------------------------------------------


class TestRedactUrl:
    """Unit tests for _redact_url helper."""

    def test_no_password(self):
        from api.settings import _redact_url

        assert _redact_url("sqlite:///pipelit.db") == "sqlite:///pipelit.db"

    def test_redis_with_password(self):
        from api.settings import _redact_url

        assert _redact_url("redis://:secret@host:6379/0") == "redis://:***@host:6379/0"

    def test_postgres_with_user_and_password(self):
        from api.settings import _redact_url

        result = _redact_url("postgresql://admin:hunter2@db.example.com:5432/mydb")
        assert result == "postgresql://admin:***@db.example.com:5432/mydb"

    def test_no_password_with_host(self):
        from api.settings import _redact_url

        assert _redact_url("redis://localhost:6379/0") == "redis://localhost:6379/0"

    def test_empty_string(self):
        from api.settings import _redact_url

        assert _redact_url("") == ""


def test_get_settings_redacts_urls(auth_client, tmp_path, monkeypatch):
    """GET /settings/ redacts passwords from database_url and redis_url."""
    pipelit_dir = tmp_path / "pipelit"
    pipelit_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PIPELIT_DIR", str(pipelit_dir))

    conf_data = {
        "database_url": "postgresql://admin:secret@db:5432/app",
        "redis_url": "redis://:mypass@redis:6379/0",
    }
    (pipelit_dir / "conf.json").write_text(json.dumps(conf_data))

    with patch("api.settings._build_environment_cached", return_value=MOCK_ENVIRONMENT):
        resp = auth_client.get("/api/v1/settings/")
    assert resp.status_code == 200
    config = resp.json()["config"]
    assert "secret" not in config["database_url"]
    assert "admin:***@" in config["database_url"]
    assert "mypass" not in config["redis_url"]
    assert ":***@" in config["redis_url"]

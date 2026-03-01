"""Tests for /health endpoint and production safety guards."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Ensure platform/ is importable
_platform_dir = str(Path(__file__).resolve().parent.parent)
if _platform_dir not in sys.path:
    sys.path.insert(0, _platform_dir)


@pytest.fixture
def app(db):
    from main import app as _app
    from database import get_db

    def _override_get_db():
        try:
            yield db
        finally:
            pass

    _app.dependency_overrides[get_db] = _override_get_db
    yield _app
    _app.dependency_overrides.clear()


@pytest.fixture
def client(app):
    return TestClient(app)


class TestHealthEndpoint:
    def test_health_all_ok(self, client):
        """GET /health with Redis+DB up returns ok status."""
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["redis"] is True
        assert data["database"] is True
        assert "version" in data

    def test_health_redis_down(self, client):
        """When Redis is unreachable, status is degraded."""
        def bad_redis(*args, **kwargs):
            raise ConnectionError("Redis down")

        with patch("main.redis_lib.from_url", side_effect=bad_redis):
            resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["redis"] is False
        assert data["database"] is True

    def test_health_db_down(self, client):
        """When DB is unreachable, status is degraded."""
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(side_effect=Exception("DB down"))
        mock_session.__exit__ = MagicMock(return_value=False)

        with patch("main.SessionLocal", return_value=mock_session):
            resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["redis"] is True
        assert data["database"] is False


class TestSecretKeyGuard:
    def test_secret_key_guard_raises_in_production(self):
        """Lifespan raises RuntimeError when DEBUG=False and SECRET_KEY is default."""
        from main import lifespan, app as _app

        with patch("main.settings") as mock_settings:
            mock_settings.DEBUG = False
            mock_settings.SECRET_KEY = "change-me-in-production"

            with pytest.raises(RuntimeError, match="SECRET_KEY"):
                import asyncio
                async def _run():
                    async with lifespan(_app):
                        pass
                asyncio.run(_run())

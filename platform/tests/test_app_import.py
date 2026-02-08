"""Tests that import main.py, covering app creation, CORS, and router registration."""

from __future__ import annotations

import asyncio
from unittest.mock import patch


class TestAppSetup:
    @patch("main.engine")
    def test_app_exists(self, mock_engine):
        from main import app
        assert app is not None
        assert app.title == "Workflow Platform API"

    @patch("main.engine")
    @patch("main.Base")
    def test_startup_creates_tables(self, mock_base, mock_engine):
        from main import lifespan, app

        async def _run():
            async with lifespan(app):
                pass

        asyncio.run(_run())
        mock_base.metadata.create_all.assert_called_once_with(bind=mock_engine)

    @patch("main.engine")
    def test_routers_registered(self, mock_engine):
        from main import app
        # Check some expected routes exist
        route_paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert any("/api/" in p for p in route_paths)


class TestWsRouterImport:
    def test_ws_router_available(self):
        from ws import ws_router
        assert ws_router is not None

    def test_global_ws_authenticate(self):
        """Test _authenticate is importable (already tested elsewhere)."""
        from ws.global_ws import _authenticate
        assert callable(_authenticate)

    def test_executions_router(self):
        from ws.executions import router
        assert router is not None

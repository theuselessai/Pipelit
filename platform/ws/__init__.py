"""WebSocket endpoints for execution event streaming."""

from ws.executions import router as ws_router

__all__ = ["ws_router"]

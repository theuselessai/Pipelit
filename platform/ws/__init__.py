"""WebSocket endpoints for execution event streaming."""

from fastapi import APIRouter

from ws.executions import router as executions_ws_router
from ws.global_ws import router as global_ws_router

ws_router = APIRouter()
ws_router.include_router(executions_ws_router)
ws_router.include_router(global_ws_router)

__all__ = ["ws_router"]

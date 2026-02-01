"""FastAPI application entry point."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure platform/ is on sys.path for absolute imports
_platform_dir = str(Path(__file__).resolve().parent)
if _platform_dir not in sys.path:
    sys.path.insert(0, _platform_dir)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api import api_router
from api.executions import chat_router
from config import settings
from database import Base, engine
from handlers.webhook import router as webhook_router
from handlers.manual import router as manual_router
from ws import ws_router

app = FastAPI(title="Workflow Platform API", version="1.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.CORS_ALLOW_ALL_ORIGINS else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(api_router)

# Chat router (nested under /api/v1/workflows)
app.include_router(chat_router, prefix="/api/v1/workflows", tags=["chat"])

# Webhook & manual execution endpoints
app.include_router(webhook_router, prefix="/api", tags=["webhooks"])
app.include_router(manual_router, prefix="/api", tags=["manual"])

# WebSocket endpoints
app.include_router(ws_router)

# Serve frontend static files (built React SPA)
frontend_dist = Path(__file__).parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="spa")


@app.on_event("startup")
def startup():
    # Create tables if they don't exist (dev convenience; use alembic in prod)
    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

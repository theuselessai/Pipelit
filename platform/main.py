"""FastAPI application entry point."""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Ensure platform/ is on sys.path for absolute imports
_platform_dir = str(Path(__file__).resolve().parent)
if _platform_dir not in sys.path:  # pragma: no cover
    sys.path.insert(0, _platform_dir)

try:
    __version__ = (Path(__file__).resolve().parent.parent / "VERSION").read_text().strip()
except Exception:  # pragma: no cover
    __version__ = "0.0.0-dev"

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api import api_router
from api.executions import chat_router
from config import settings
from database import Base, engine
from handlers.manual import router as manual_router
from ws import ws_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Configure unified logging before anything else
    from logging_config import setup_logging
    setup_logging("Server")

    import logging
    logger = logging.getLogger(__name__)

    # Startup: create tables if they don't exist (dev convenience; use alembic in prod)
    Base.metadata.create_all(bind=engine)

    # Ensure default workspace exists in DB (covers existing installs)
    try:
        from database import SessionLocal
        from models.workspace import Workspace
        from config import get_pipelit_dir
        with SessionLocal() as session:
            default = session.query(Workspace).filter(Workspace.name == "default").first()
            if not default:
                from models.user import UserProfile
                user = session.query(UserProfile).first()
                if user:
                    workspace_path = str(get_pipelit_dir() / "workspaces" / "default")
                    ws = Workspace(name="default", path=workspace_path, user_profile_id=user.id)
                    session.add(ws)
                    session.commit()
                    os.makedirs(workspace_path, exist_ok=True)
                    os.makedirs(os.path.join(workspace_path, ".tmp"), exist_ok=True)
                    logger.info("Created default workspace at %s", workspace_path)
                else:
                    logger.info("No user found, skipping default workspace creation")
    except Exception:
        logger.exception("Failed to ensure default workspace on startup")

    # Recover any scheduled jobs that missed their next_run_at while the server was down
    try:
        from services.scheduler import recover_scheduled_jobs
        recovered = recover_scheduled_jobs()
        if recovered:
            logger.info("Recovered %d stale scheduled jobs", recovered)
    except Exception:
        logger.exception("Failed to recover scheduled jobs on startup")

    # Ensure skills directory exists
    try:
        skills_dir = Path(settings.SKILLS_DIR) if settings.SKILLS_DIR else Path.home() / ".config" / "pipelit" / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Skills directory: %s", skills_dir)
    except Exception:
        logger.exception("Failed to create skills directory")

    # Validate sandbox environment
    try:
        from services.environment import validate_environment_on_startup
        resolution = validate_environment_on_startup()
        logger.info("Sandbox: mode=%s, can_execute=%s, container=%s",
                     resolution.mode, resolution.can_execute, resolution.container_type)
        if not resolution.can_execute:
            logger.warning("Sandbox not available: %s", resolution.reason)
    except Exception:
        logger.exception("Failed to validate sandbox environment on startup")

    # Recover any executions stuck in "running" from a previous crash
    try:
        from services.execution_recovery import recover_zombie_executions
        recovered_executions = recover_zombie_executions()
        if recovered_executions:
            logger.info("Recovered %d zombie executions", recovered_executions)
    except Exception:
        logger.exception("Failed to recover zombie executions on startup")

    yield


app = FastAPI(title="Workflow Platform API", version=__version__, lifespan=lifespan)

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

# Manual execution endpoint
app.include_router(manual_router, prefix="/api/v1", tags=["manual"])

# WebSocket endpoints
app.include_router(ws_router)

# Serve frontend static files (built React SPA)
frontend_dist = Path(__file__).parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="spa")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, log_config=None)

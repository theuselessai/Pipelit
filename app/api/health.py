"""Health check endpoints."""
from fastapi import APIRouter
from redis import Redis

from app.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict:
    """Basic health check."""
    return {"status": "ok"}


@router.get("/health/detailed")
async def detailed_health_check() -> dict:
    """Detailed health check including Redis status."""
    redis_status = "unknown"

    try:
        redis_conn = Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
        )
        redis_conn.ping()
        redis_status = "connected"
    except Exception as e:
        redis_status = f"error: {str(e)}"

    return {
        "status": "ok",
        "redis": redis_status,
        "api_enabled": settings.API_ENABLED,
    }

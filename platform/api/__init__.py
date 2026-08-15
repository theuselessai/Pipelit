"""FastAPI router aggregation."""

from fastapi import APIRouter

from api.auth import router as auth_router
from api.workflows import router as workflows_router
from api.nodes import router as nodes_router
from api.executions import router as executions_router
from api.credentials import router as credentials_router
from api.memory import router as memory_router
from api.schedules import router as schedules_router
from api.workspaces import router as workspaces_router
from api.providers import router as providers_router
from api.settings import router as settings_router
from api.users import router as users_router
from api.available_models import available_models_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(users_router, prefix="/users", tags=["users"])
api_router.include_router(workflows_router, prefix="/workflows", tags=["workflows"])
api_router.include_router(nodes_router, prefix="/workflows", tags=["nodes", "edges"])
api_router.include_router(executions_router, prefix="/executions", tags=["executions"])
api_router.include_router(credentials_router, prefix="/credentials", tags=["credentials"])
api_router.include_router(memory_router, prefix="/memories", tags=["memories"])
api_router.include_router(schedules_router, prefix="/schedules", tags=["schedules"])
api_router.include_router(workspaces_router, prefix="/workspaces", tags=["workspaces"])
api_router.include_router(settings_router, prefix="/settings", tags=["settings"])
api_router.include_router(providers_router, prefix="/providers", tags=["providers"])
api_router.include_router(available_models_router, prefix="/available-models", tags=["available-models"])

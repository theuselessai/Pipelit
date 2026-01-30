from ninja import NinjaAPI

from .auth import SessionOrBasicAuth  # list of auth backends
from .auth_views import router as auth_router
from .credentials import router as credentials_router
from .executions import router as executions_router
from .nodes import router as nodes_router
from .triggers import router as triggers_router
from .workflows import router as workflows_router

api = NinjaAPI(
    title="Workflow Platform API",
    version="1.0.0",
    auth=SessionOrBasicAuth,
    urls_namespace="api-v1",
)

api.add_router("/auth", auth_router)
api.add_router("/workflows", workflows_router)
api.add_router("/workflows", nodes_router)
api.add_router("/workflows", triggers_router)
api.add_router("/executions", executions_router)
api.add_router("/credentials", credentials_router)

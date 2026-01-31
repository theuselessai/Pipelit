from ninja import NinjaAPI

from .auth import BearerAuth
from .auth_views import router as auth_router
from .credentials import router as credentials_router
from .executions import chat_router, router as executions_router
from .nodes import router as nodes_router
from .workflows import router as workflows_router

api = NinjaAPI(
    title="Workflow Platform API",
    version="1.0.0",
    auth=BearerAuth(),
    urls_namespace="api-v1",
)

api.add_router("/auth", auth_router)
api.add_router("/workflows", workflows_router)
api.add_router("/workflows", nodes_router)
api.add_router("/workflows", chat_router)
api.add_router("/executions", executions_router)
api.add_router("/credentials", credentials_router)

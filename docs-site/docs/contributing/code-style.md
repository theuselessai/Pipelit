# Code Style

This page documents the coding conventions and style guidelines for contributing to Pipelit.

## The Most Important Rule

!!! danger "This project uses FastAPI + SQLAlchemy, NOT Django"
    Pipelit's backend is built on **FastAPI**, **SQLAlchemy 2.0**, **Alembic**, and **RQ (Redis Queue)**. Never reference Django models, Django ORM, Django settings, Django views, or any Django concepts in code, comments, commit messages, or documentation.

    - Models are SQLAlchemy `declarative_base` classes, not `django.db.models.Model`
    - Migrations use Alembic, not `manage.py migrate`
    - Settings use Pydantic `BaseSettings`, not `django.conf.settings`
    - Background tasks use RQ, not Celery (though Celery is also not Django-specific)
    - Authentication uses FastAPI dependencies with Bearer tokens, not Django middleware

## Python

### General

- Follow [PEP 8](https://peps.python.org/pep-0008/) for formatting and naming
- Maximum line length: 100 characters (relaxed from PEP 8's 79)
- Use **absolute imports** from `platform/` as the root (e.g., `from models.node import WorkflowNode`)
- Prefer f-strings over `.format()` or `%` formatting

### Type Hints

Use type hints on all function signatures:

```python
# Good
def resolve_llm_for_node(node: WorkflowNode, db: Session) -> BaseChatModel:
    ...

# Bad
def resolve_llm_for_node(node, db):
    ...
```

Use `from __future__ import annotations` at the top of every module for modern annotation syntax:

```python
from __future__ import annotations

from typing import Any

def process(data: dict[str, Any]) -> list[str]:
    ...
```

### Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| Modules | `snake_case` | `node_type_defs.py` |
| Classes | `PascalCase` | `WorkflowNode`, `NodeTypeSpec` |
| Functions | `snake_case` | `get_component_factory()` |
| Constants | `UPPER_SNAKE_CASE` | `COMPONENT_REGISTRY`, `NODE_TYPE_REGISTRY` |
| Variables | `snake_case` | `edge_type`, `node_id` |
| Private | Leading underscore | `_safe_eval()`, `_platform_dir` |

### Imports

Organize imports in three groups, separated by blank lines:

```python
# 1. Standard library
from __future__ import annotations

import os
from pathlib import Path

# 2. Third-party
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

# 3. Local
from auth import get_current_user
from database import get_db
from models.workflow import Workflow
```

### SQLAlchemy Models

- Use SQLAlchemy 2.0 style with `Mapped` type annotations
- Use `mapped_column()` instead of `Column()`
- Define relationships with explicit `Mapped` types

```python
# Good (SQLAlchemy 2.0)
class WorkflowNode(Base):
    __tablename__ = "workflow_nodes"

    id: Mapped[int] = mapped_column(primary_key=True)
    node_id: Mapped[str] = mapped_column(String(100))
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflows.id"))

# Bad (SQLAlchemy 1.x style)
class WorkflowNode(Base):
    __tablename__ = "workflow_nodes"

    id = Column(Integer, primary_key=True)
    node_id = Column(String(100))
```

### FastAPI Endpoints

- Use `APIRouter` for route grouping
- Use dependency injection for database sessions and authentication
- Return Pydantic models or dicts, never raw ORM objects
- Use appropriate HTTP status codes

```python
@router.post("/workflows/", status_code=201)
def create_workflow(
    data: WorkflowCreate,
    db: Session = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
):
    ...
```

### Pydantic Schemas

- Use `Literal` types for enum-like fields (`component_type`, `edge_type`)
- Use `model_config = ConfigDict(from_attributes=True)` for ORM compatibility
- Separate create, update, and response schemas

### Authentication

- API uses **Bearer token** authentication exclusively
- Always use the `get_current_user` dependency for authenticated endpoints
- Agent users are created without passwords via `create_agent_user`
- Never use the user's personal API key for agent operations

## TypeScript

### General

- Use TypeScript **strict mode** (enabled in `tsconfig.json`)
- Prefer `const` over `let`; never use `var`
- Use arrow functions for callbacks and inline functions
- Use template literals over string concatenation

### Types

- Define interfaces for API response types in `types/models.ts`
- Use `interface` for object shapes, `type` for unions and intersections
- Avoid `any` -- use `unknown` and narrow with type guards when the type is uncertain

```typescript
// Good
interface WorkflowNode {
    id: number;
    node_id: string;
    component_type: ComponentType;
}

// Bad
const node: any = response.data;
```

### React Components

- Use functional components with hooks
- Use TanStack Query for all API data fetching
- Use Shadcn/ui components for UI elements
- Colocate component-specific types with the component file

```typescript
// Good
export function WorkflowCanvas({ slug }: { slug: string }) {
    const { data: nodes } = useNodes(slug);
    // ...
}

// Bad - class component
class WorkflowCanvas extends React.Component { ... }
```

### API Hooks

All API interactions go through TanStack Query hooks defined in `frontend/src/api/`:

```typescript
// Queries (GET)
export function useWorkflows() {
    return useQuery({ queryKey: ["workflows"], queryFn: fetchWorkflows });
}

// Mutations (POST/PATCH/DELETE)
export function useCreateWorkflow() {
    return useMutation({ mutationFn: createWorkflow });
}
```

## File Organization

- **One concern per file.** Do not mix unrelated functionality.
- **Keep files focused.** If a file grows beyond 300-400 lines, consider splitting it.
- **Mirror backend structure in frontend.** API hooks in `api/`, page components in `features/`, shared components in `components/`.

## Commit Messages

- Use present tense, imperative mood: "add feature" not "added feature"
- Start with a category when appropriate: `fix:`, `feat:`, `test:`, `docs:`, `refactor:`
- Keep the first line under 72 characters
- Reference issue numbers when applicable: `fix: resolve edge validation crash (#42)`

## Documentation

- Document public functions and classes with docstrings
- Use `"""triple double quotes"""` for Python docstrings
- Use `/** JSDoc */` comments for exported TypeScript functions
- Keep comments focused on "why" rather than "what"

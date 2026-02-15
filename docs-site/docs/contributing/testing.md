# Testing

Pipelit uses **pytest** for its test suite. All tests are located in `platform/tests/` and use an in-memory SQLite database for isolation.

## Running the Test Suite

```bash
cd platform
source ../.venv/bin/activate
export FIELD_ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
python -m pytest tests/ -v
```

!!! note "Encryption key required"
    The `FIELD_ENCRYPTION_KEY` environment variable must be set before running tests. The `conftest.py` auto-generates a temporary key if one is not provided, but setting it explicitly is recommended for consistency.

### Running Specific Tests

```bash
# Run a single test file
python -m pytest tests/test_api.py -v

# Run a specific test function
python -m pytest tests/test_api.py::test_create_workflow -v

# Run tests matching a keyword
python -m pytest tests/ -k "scheduler" -v

# Run with short traceback
python -m pytest tests/ -v --tb=short
```

## Test Structure

Tests are organized by the subsystem they exercise:

| Test File | Coverage Area |
|-----------|---------------|
| `test_api.py` | REST API endpoints (workflow CRUD, nodes, edges) |
| `test_api_extended.py` | Extended API tests (credentials, executions, batch operations) |
| `test_views.py` | HTTP view layer tests |
| `test_builder.py` | Workflow compilation (LangGraph graph building) |
| `test_orchestrator.py` | Node execution orchestration |
| `test_orchestrator_core.py` | Core orchestrator logic |
| `test_orchestrator_e2e.py` | End-to-end orchestrator tests |
| `test_orchestrator_loops.py` | Loop component execution |
| `test_orchestrator_helpers.py` | Orchestrator utility functions |
| `test_orchestrator_checkpoints.py` | Conversation memory checkpointing |
| `test_components.py` | Individual component implementations |
| `test_components_http.py` | HTTP request component |
| `test_components_db.py` | Database-dependent components |
| `test_components_remaining.py` | Additional component tests |
| `test_edge_validation.py` | Edge type compatibility validation |
| `test_node_io.py` | Node I/O schemas and type system |
| `test_expressions.py` | Jinja2 template expression resolution |
| `test_topology.py` | DAG topology analysis (BFS reachability) |
| `test_database_and_models.py` | SQLAlchemy model tests |
| `test_scheduler.py` | Self-rescheduling scheduler (29 tests) |
| `test_ws.py` | WebSocket endpoint tests |
| `test_ws_async.py` | Async WebSocket tests |
| `test_broadcast.py` | Redis pub/sub broadcast |
| `test_memory.py` | Memory system tests |
| `test_memory_service.py` | Memory service layer |
| `test_dispatch.py` | Trigger dispatch logic |
| `test_handlers.py` | Event handler tests |
| `test_telegram_handler.py` | Telegram trigger handler |
| `test_manual_handler.py` | Manual trigger handler |
| `test_mfa.py` | Multi-factor authentication |
| `test_token_usage.py` | Token counting and cost tracking |
| `test_epics_tasks.py` | Epic and task management |

## Test Fixtures

Shared fixtures are defined in `platform/conftest.py`:

| Fixture | Provides |
|---------|----------|
| `db` | SQLAlchemy test session (in-memory SQLite) |
| `user_profile` | A `UserProfile` with username `testuser` |
| `api_key` | An `APIKey` linked to the test user |
| `workflow` | A `Workflow` with slug `test-workflow` |
| `telegram_credential` | A `BaseCredential` with Telegram bot token |
| `telegram_trigger` | A `WorkflowNode` for a Telegram trigger |
| `manual_trigger` | A `WorkflowNode` for a manual trigger |

The `_setup_db` fixture runs automatically before each test, creating all tables and dropping them afterward for complete isolation.

## Authentication in Tests

All API tests must use **Bearer token authentication**. Never use session auth, basic auth, or OAuth in tests.

### Pattern: Authenticated Test Client

```python
@pytest.fixture
def auth_client(client, api_key):
    client.headers["Authorization"] = f"Bearer {api_key.key}"
    return client


def test_create_workflow(auth_client):
    response = auth_client.post("/api/v1/workflows/", json={
        "name": "My Workflow",
    })
    assert response.status_code == 201
```

### Pattern: Database Override

Tests override the `get_db` dependency to use the in-memory test database:

```python
@pytest.fixture
def app(db):
    from main import app as _app
    from database import get_db

    def _override_get_db():
        try:
            yield db
        finally:
            pass

    _app.dependency_overrides[get_db] = _override_get_db
    yield _app
    _app.dependency_overrides.clear()
```

## Writing New Tests

### Test File Template

```python
"""Tests for <subsystem>."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure platform/ is importable
_platform_dir = str(Path(__file__).resolve().parent.parent)
if _platform_dir not in sys.path:
    sys.path.insert(0, _platform_dir)


def test_my_feature(db, workflow, api_key):
    """Test description."""
    # Arrange
    # ...

    # Act
    # ...

    # Assert
    assert result == expected
```

### Guidelines

- Use descriptive test function names (`test_switch_routes_to_matching_condition`)
- Use the `db`, `workflow`, and other shared fixtures from `conftest.py`
- Always authenticate API requests with `Bearer {api_key.key}`
- Test both success and error paths
- Mock external services (Redis, LLM providers) where appropriate
- Keep tests independent -- do not rely on test execution order

## Coverage

Check test coverage with:

```bash
python -m pytest tests/ --cov=. --cov-report=term-missing -v
```

Generate an HTML coverage report:

```bash
python -m pytest tests/ --cov=. --cov-report=html -v
# Open htmlcov/index.html in a browser
```

The project uses Codecov for tracking coverage on pull requests. Coverage badges are displayed on the repository README.

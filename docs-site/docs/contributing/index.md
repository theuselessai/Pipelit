# Contributing

Thank you for your interest in contributing to Pipelit! This section covers everything you need to get started as a developer.

## Guides

<div class="grid" markdown>

<div class="card" markdown>

### [Development Setup](development-setup.md)

Fork the repository, install dependencies, and run the backend, worker, and frontend in development mode.

</div>

<div class="card" markdown>

### [Testing](testing.md)

Run the test suite, understand the test structure, write new tests with Bearer token authentication, and check coverage.

</div>

<div class="card" markdown>

### [Adding Components](adding-components.md)

Step-by-step guide to creating new workflow node types: registry entries, component implementations, SQLAlchemy models, Pydantic schemas, and frontend types.

</div>

<div class="card" markdown>

### [Migrations](migrations.md)

Alembic migration best practices: checking for conflicts, handling SQLite batch operations, testing against existing data, and common commands.

</div>

<div class="card" markdown>

### [Code Style](code-style.md)

Python and TypeScript conventions, type hints, formatting, and the most important rule: this project uses FastAPI + SQLAlchemy, not Django.

</div>

<div class="card" markdown>

### [Releasing](releasing.md)

How to create a new Pipelit release: version bumping, changelog updates, tagging, and the automated GitHub Release workflow.

</div>

</div>

## Quick Contribution Checklist

Before submitting a pull request:

1. **Branch** -- create a feature branch from `master`
2. **Code** -- follow the project's code style and conventions
3. **Test** -- add or update tests for your changes
4. **Migrate** -- create an Alembic migration if you changed database models
5. **Register** -- if adding a new component type, register it in all required places
6. **Run tests** -- ensure the full test suite passes
7. **Commit** -- write clear, descriptive commit messages

## Tech Stack Reminder

This project uses:

| Layer | Technologies |
|-------|-------------|
| **Backend** | FastAPI, SQLAlchemy 2.0, Alembic, Pydantic, RQ (Redis Queue) |
| **Frontend** | React, Vite, TypeScript, Shadcn/ui, React Flow, TanStack Query |
| **Execution** | LangGraph, LangChain, Redis pub/sub, WebSocket |

!!! warning "Not Django"
    This project uses **FastAPI + SQLAlchemy + RQ**. Never reference Django models, Django ORM, Django settings, or any Django concepts. The backend is Python/FastAPI with SQLAlchemy models and Alembic migrations.

# Development Setup

This guide walks through setting up a complete Pipelit development environment from scratch.

## Prerequisites

| Tool | Minimum Version | Purpose |
|------|----------------|---------|
| Python | 3.10+ | Backend runtime |
| Redis | 8.0+ | Task queue, pub/sub, search |
| Node.js | 18+ | Frontend build and dev server |
| Git | 2.0+ | Source control |

## Fork and Clone

1. Fork the repository on GitHub: [theuselessai/Pipelit](https://github.com/theuselessai/Pipelit)

2. Clone your fork:

    ```bash
    git clone git@github.com:YOUR_USERNAME/Pipelit.git
    cd Pipelit
    ```

3. Add the upstream remote:

    ```bash
    git remote add upstream git@github.com:theuselessai/Pipelit.git
    ```

## Backend Setup

Create a Python virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r platform/requirements.txt
```

The `requirements.txt` includes FastAPI, SQLAlchemy, LangGraph, LangChain, and all other backend dependencies.

## Frontend Setup

Install Node.js dependencies:

```bash
cd platform/frontend
npm install
cd ../..
```

## Configuration

Create a `.env` file in the repository root:

```bash
# Generate the encryption key
echo "FIELD_ENCRYPTION_KEY=$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" > .env
echo "REDIS_URL=redis://localhost:6379/0" >> .env
```

See [Environment Variables](../deployment/environment.md) for the full list of configuration options.

## Running in Development

Start all services with a single command:

```bash
cd platform
source ../.venv/bin/activate
honcho start
```

This reads the `Procfile` and starts:

| Process | Command | Description |
|---------|---------|-------------|
| **server** | `uvicorn main:app --reload` | FastAPI backend on `:8000` with auto-reload |
| **frontend** | `npm run dev` | Vite dev server on `:5173`, proxies `/api` to `:8000` |
| **scheduler** | `rq worker --worker-class worker_class.PipelitWorker workflows --with-scheduler` | 1 worker with job scheduler for delayed/recurring jobs |
| **worker** | `rq worker-pool workflows -w worker_class.PipelitWorker -n 2` | 2 additional workers for parallel job processing |

All processes use unified logging with context-aware formatting — server logs as `[Server]`, workers as `[Worker-{pid}]`. Execution and node IDs are injected automatically.

!!! note
    Workers do **not** auto-reload on file changes. Restart honcho (++ctrl+c++ then `honcho start`) after backend code changes that affect execution logic.

### First Login

Open `http://localhost:5173` in your browser. The setup wizard prompts you to create an admin account on first visit.

??? note "Manual startup (without honcho)"
    If you prefer separate terminals:

    ```bash
    # Terminal 1 — Backend
    cd platform && source ../.venv/bin/activate
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload

    # Terminal 2 — RQ Worker with scheduler
    cd platform && source ../.venv/bin/activate
    rq worker --worker-class worker_class.PipelitWorker workflows --with-scheduler

    # Terminal 3 — Frontend (dev)
    cd platform/frontend
    npm run dev
    ```

## Project Structure

```
Pipelit/
├── .env                    # Environment variables (not committed)
├── platform/
│   ├── main.py             # FastAPI app entry point
│   ├── config.py           # Pydantic Settings
│   ├── database.py         # SQLAlchemy engine + session
│   ├── auth.py             # Bearer token auth
│   ├── api/                # REST endpoint routers
│   ├── models/             # SQLAlchemy ORM models
│   ├── schemas/            # Pydantic schemas + node type registry
│   ├── services/           # Business logic (orchestrator, builder, etc.)
│   ├── components/         # LangGraph node implementations
│   ├── handlers/           # Trigger handlers (Telegram, webhook, manual)
│   ├── validation/         # Edge type compatibility checks
│   ├── ws/                 # WebSocket endpoints + broadcast
│   ├── tasks/              # RQ job wrappers
│   ├── triggers/           # Trigger resolver
│   ├── logging_config.py   # Unified logging (context-aware formatter)
│   ├── worker_class.py     # Custom RQ worker with unified logging
│   ├── Procfile            # honcho process definitions
│   ├── alembic/            # Database migrations
│   ├── tests/              # Test suite
│   ├── conftest.py         # Shared test fixtures
│   └── frontend/           # React SPA
│       ├── src/
│       │   ├── api/        # TanStack Query hooks
│       │   ├── features/   # Page components
│       │   ├── components/ # Shared UI components
│       │   ├── hooks/      # Custom React hooks
│       │   ├── lib/        # Utilities (wsManager, etc.)
│       │   └── types/      # TypeScript type definitions
│       └── package.json
└── docs/                   # Design documents
```

## IDE Setup Tips

### VS Code

Recommended extensions:

- **Python** (ms-python.python) -- Linting, IntelliSense, debugging
- **Pylance** (ms-python.vscode-pylance) -- Type checking
- **ESLint** (dbaeumer.vscode-eslint) -- TypeScript linting
- **Prettier** (esbenp.prettier-vscode) -- Code formatting

Workspace settings (`.vscode/settings.json`):

```json
{
    "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python",
    "python.analysis.extraPaths": ["${workspaceFolder}/platform"],
    "editor.formatOnSave": true,
    "typescript.tsdk": "platform/frontend/node_modules/typescript/lib"
}
```

### PyCharm / IntelliJ

1. Set the Python interpreter to `.venv/bin/python`
2. Mark `platform/` as a Sources Root
3. Mark `platform/frontend/src/` as a Resource Root

## Common Development Tasks

### Creating a Feature Branch

Always create a new branch before starting work:

```bash
git checkout master
git pull upstream master
git checkout -b feature/your-feature-name
```

### Rebuilding the Frontend

If you only need to test backend changes without the Vite dev server:

```bash
cd platform/frontend
npm run build
```

Then access the app at `http://localhost:8000` (served directly by FastAPI).

### Resetting the Database

To start fresh with a clean database:

```bash
rm platform/db.sqlite3
rm platform/checkpoints.db
# Restart the backend — tables are recreated automatically
```

### Checking Redis

```bash
redis-cli ping              # Should return PONG
redis-cli MODULE LIST        # Should include "search" module
rq info                      # Show queue status
```

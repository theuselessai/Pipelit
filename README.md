# Pipelit

[![CI](https://github.com/theuselessai/Pipelit/actions/workflows/ci.yml/badge.svg)](https://github.com/theuselessai/Pipelit/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/theuselessai/Pipelit/graph/badge.svg)](https://app.codecov.io/gh/theuselessai/Pipelit)

A visual workflow automation platform for building LLM-powered agents. Design workflows on a React Flow canvas, connect triggers (Telegram, webhooks, chat), LLM agents, tools, and routing logic. Executes via LangGraph with real-time WebSocket status updates.

## Stack

- **Backend:** FastAPI + SQLAlchemy + Alembic + RQ (Redis Queue)
- **Frontend:** React + Vite + TypeScript, Shadcn/ui, React Flow (@xyflow/react v12), TanStack Query

## Prerequisites

- Python 3.10+
- Redis server
- Node.js 18+ (for frontend)

## Setup

1. **Clone and install backend dependencies**
   ```bash
   git clone git@github.com:theuselessai/aibot_telegram_server.git
   cd aibot_telegram_server
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r platform/requirements.txt
   ```

2. **Install frontend dependencies**
   ```bash
   cd platform/frontend
   npm install
   ```

3. **Start Redis** (see [Redis Setup](#redis-setup) below)
   ```bash
   # macOS
   brew services start redis

   # Linux (Debian/Ubuntu)
   sudo systemctl start redis
   ```

## Running

**Backend:**
```bash
cd platform
source ../.venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**Frontend (development):**
```bash
cd platform/frontend
npm run dev          # Dev server at http://localhost:5173 (proxies /api to backend)
```

**Frontend (production):**
```bash
cd platform/frontend
npm run build        # Build to dist/ (served by FastAPI static mount)
```

## Testing

```bash
cd platform
source ../.venv/bin/activate
export FIELD_ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
python -m pytest tests/ -v
```

## Platform REST API

All endpoints under `/api/v1/`, authenticated via Bearer token (`Authorization: Bearer <key>`).

| Resource | Endpoints |
|----------|-----------|
| **Auth** | `POST /auth/token/`, `GET /auth/me/`, `POST /auth/setup/` |
| **Workflows** | `GET/POST /workflows/`, `GET/PATCH/DELETE /workflows/{slug}/`, `POST /workflows/{slug}/validate/` |
| **Nodes** | `GET/POST /workflows/{slug}/nodes/`, `PATCH/DELETE .../nodes/{node_id}/` |
| **Edges** | `GET/POST /workflows/{slug}/edges/`, `PATCH/DELETE .../edges/{id}/` |
| **Executions** | `GET /executions/`, `GET .../executions/{id}/`, `POST .../executions/{id}/cancel/` |
| **Chat** | `POST /workflows/{slug}/chat/`, `DELETE /workflows/{slug}/chat/history` |
| **Credentials** | `GET/POST /credentials/`, `GET/PATCH/DELETE .../credentials/{id}/`, `POST .../credentials/{id}/test/` |

## Features

- **Visual Workflow Editor** — drag-and-drop React Flow canvas with node palette and config panel
- **Multiple Triggers** — Telegram, webhooks, chat, manual execution
- **LLM Agents** — LangGraph react agents with tool-calling (shell, HTTP, web search, calculator, etc.)
- **Conditional Routing** — switch nodes with rule-based routing via conditional edges
- **Conversation Memory** — optional per-agent SQLite-backed conversation persistence
- **Real-time Updates** — WebSocket push for node execution status, canvas badges
- **Jinja2 Expressions** — template variables in prompts referencing upstream node outputs
- **Credentials Management** — encrypted storage for LLM providers, Telegram bots, etc.
- **Dark Mode** — system/light/dark theme via Shadcn CSS variables

## Redis Setup

The `spawn_and_await` tool (agent-to-agent delegation) uses `langgraph-checkpoint-redis` which requires the **RediSearch** module. Without it you'll get:

```
unknown command 'FT._LIST'
```

**Redis 8.0+** includes RediSearch (and all former Redis Stack modules) natively — no separate `redis-stack-server` package needed. If you're running an older Redis version, upgrade to 8.0+.

**Workaround without Redis 8:** Enable `conversation_memory` on agent nodes that use `spawn_and_await`. This switches the checkpointer from RedisSaver to SqliteSaver, bypassing the RediSearch requirement.

### Removing existing Redis (<8.0)

If you have an older Redis installed, stop and remove it first so it doesn't conflict on port 6379:

```bash
# Debian/Ubuntu
sudo systemctl stop redis-server
sudo systemctl disable redis-server
sudo apt remove --purge redis-server

# macOS
brew services stop redis
brew uninstall redis

# Docker
docker stop redis && docker rm redis
```

### Installing Redis 8.0+

```bash
# Docker (easiest)
docker run -d --name redis -p 6379:6379 redis:8

# Debian/Ubuntu
curl -fsSL https://packages.redis.io/gpg | sudo gpg --dearmor -o /usr/share/keyrings/redis-archive-keyring.gpg
sudo chmod 644 /usr/share/keyrings/redis-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/redis-archive-keyring.gpg] https://packages.redis.io/deb $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/redis.list
sudo apt-get update
sudo apt-get install redis

# macOS
brew install redis
brew services start redis
```

Verify RediSearch is available:

```bash
redis-cli MODULE LIST
# Should include "search" (ft) module
```

## License

MIT

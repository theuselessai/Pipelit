<p align="center">
  <img src="docs/assets/banner.png" alt="Pipelit — Visual LLM Workflow Automation" width="100%" />
</p>

<p align="center">
  <strong>Build, connect, and orchestrate LLM-powered agents — visually.</strong>
</p>

<p align="center">
  <a href="https://github.com/theuselessai/Pipelit/actions/workflows/ci.yml"><img src="https://github.com/theuselessai/Pipelit/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <a href="https://app.codecov.io/gh/theuselessai/Pipelit"><img alt="Codecov" src="https://img.shields.io/codecov/c/github/theuselessai/pipelit?style=flat-square"></a>
  <a href="https://github.com/theuselessai/Pipelit/releases"><img src="https://img.shields.io/github/v/tag/theuselessai/Pipelit?label=version&style=flat-square" alt="Version" /></a>
  <a href="#license"><img src="https://img.shields.io/badge/license-Apache%202.0-blue.svg?style=flat-square" alt="License: Apache 2.0" /></a>
</p>

---

Pipelit is a self-hosted workflow automation engine for designing LLM agent pipelines on a drag-and-drop canvas. Wire up triggers, agents, tools, and routing logic — then watch them execute in real time with live WebSocket status updates on every node.

Typically run via the [plit](https://github.com/theuselessai/plit) CLI, which manages Pipelit alongside the message gateway as Docker containers.

<!-- TODO: Add a screenshot of the workflow editor here -->
<!-- <p align="center"><img src="docs/assets/screenshot.png" alt="Workflow Editor" width="90%" /></p> -->

---

## Highlights

|  |  |  |
|:---:|:---:|:---:|
| **Visual Canvas** | **Multi-Trigger** | **LLM Agents** |
| Drag-and-drop React Flow editor with node palette, config panel, and live execution badges | Webhooks, chat, scheduled intervals, manual — all unified as workflow nodes. External messaging via [plit gateway](https://github.com/theuselessai/plit) | LangGraph react agents with tool-calling: shell, HTTP, web search, calculator, datetime, and more |
| **Conditional Routing** | **Scheduled Execution** | **Real-time Updates** |
| Switch nodes evaluate rules and route to different branches via conditional edges | Recurring runs with configurable interval, retry with exponential backoff, pause/resume, and crash recovery | Single global WebSocket pushes node status, execution events, and canvas mutations — no polling |
| **Cost Tracking** | **Conversation Memory** | **Self-Improving Agents** |
| Per-execution token counting and USD cost calculation with Epic-level budget enforcement | Optional per-agent conversation persistence across executions via SQLite checkpointer | Agents can read epics/tasks, spawn child workflows, modify their own graphs, and schedule future work |

---

## Quick Start

### Via plit CLI (Recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/theuselessai/plit/main/install.sh | bash
plit init
plit start
```

### Standalone (Development)

<details>
<summary><strong>Prerequisites</strong></summary>

- Python 3.10+
- Redis 8.0+ (includes RediSearch natively — see [Redis Setup](#redis-setup))
- Node.js 18+
- Bubblewrap 0.4+ (Linux: `apt install bubblewrap` — macOS uses built-in `sandbox-exec`)

</details>

```bash
git clone git@github.com:theuselessai/Pipelit.git
cd Pipelit

# Backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r platform/requirements.txt

# Frontend
cd platform/frontend && npm install
```

Configure:

```bash
echo "FIELD_ENCRYPTION_KEY=$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" >> .env
echo "REDIS_URL=redis://localhost:6379/0" >> .env
```

Start services:

```bash
cd platform && source ../.venv/bin/activate
honcho start
```

Create admin account:

```bash
python -m cli setup --username admin --password <your-password>
```

Optionally bootstrap a working workflow with an LLM credential:

```bash
python -m cli apply-fixture default-agent \
  --provider anthropic \
  --model claude-sonnet-4-20250514 \
  --api-key sk-ant-...
```

Open `http://localhost:5173` (dev) or `http://localhost:8000` (production) and log in.

> **Production:** Skip the frontend dev server — run `cd platform/frontend && npm run build` once, then access the app directly at `http://localhost:8000` (FastAPI serves the built SPA).

---

## Stack

| Layer | Technologies |
|-------|-------------|
| **Backend** | FastAPI, SQLAlchemy 2.0, Alembic, Pydantic, RQ (Redis Queue) |
| **Frontend** | React, Vite, TypeScript, Shadcn/ui, React Flow (@xyflow/react v12), TanStack Query |
| **Execution** | LangGraph, LangChain, Redis pub/sub, WebSocket |
| **Auth** | Bearer token API keys, RBAC (admin/normal), TOTP-based MFA |

---

## Features

### Visual Workflow Editor
Design agent pipelines on an interactive React Flow canvas. Add nodes from the palette, configure them in the side panel, and connect them with typed edges. Live execution badges show running/success/failed status on each node.

### Triggers
Every trigger is a first-class workflow node:

| Trigger | Description |
|---------|-------------|
| **Chat** | Receives messages from chat clients via the message gateway |
| **Telegram** | Receives messages from Telegram via the message gateway |
| **Webhook** | Accept external HTTP payloads |
| **Scheduler** | Recurring interval execution with retry, backoff, and pause/resume |
| **Manual** | One-click execution from the UI |

### Agent Components

| Component | Description |
|-----------|-------------|
| **Agent** | LangGraph react agent with system prompt, tools, and optional conversation memory |
| **Deep Agent** | Advanced agent with built-in task planning, filesystem tools, and subagent delegation |
| **Categorizer** | Classifies input into predefined categories |
| **Router** | Routes messages to different branches based on content |
| **Extractor** | Extracts structured data from unstructured text |
| **Switch** | Rule-based conditional routing with per-edge condition values |
| **Loop** | Iterates over collections, executing a body node per item |
| **Spawn & Await** | Launches a child workflow and waits for its result |

### Tools
Agents can call any combination of built-in tools:

`run_command` | `http_request` | `web_search` | `calculator` | `datetime` | `epic_tools` | `task_tools` | `workflow_discover` | `workflow_create`

### Jinja2 Expressions
Reference upstream node outputs in prompts and config fields with `{{ nodeId.portName }}` syntax. Full Jinja2 filter support. The editor provides a variable picker and syntax highlighting.

### Cost Tracking & Budgets
Automatic token counting and USD cost calculation per execution. Set token or USD budgets on Epics — the orchestrator gates every node execution against the budget before running.

### Scheduled Execution
Create recurring jobs that fire workflow triggers at configurable intervals. Self-rescheduling via RQ `enqueue_in()` — no external cron needed. Features exponential backoff on failure, pause/resume, and automatic recovery of missed jobs on startup.

### Security
- Role-based access control (admin / normal)
- Encrypted credential storage (Fernet)
- TOTP-based MFA with rate limiting and account lockout
- Bearer token authentication with multi-key support
- Agent-to-agent identity verification via TOTP
- Sandboxed shell execution (bubblewrap on Linux, no unsandboxed fallback)

---

## API

All endpoints under `/api/v1/`, authenticated via `Authorization: Bearer <key>`.

| Resource | Endpoints |
|----------|-----------|
| **Auth** | `POST /auth/token/`, `GET /auth/me/` |
| **Workflows** | `GET/POST /workflows/`, `GET/PATCH/DELETE /workflows/{slug}/`, `POST .../validate/` |
| **Nodes** | `GET/POST /workflows/{slug}/nodes/`, `PATCH/DELETE .../nodes/{node_id}/` |
| **Edges** | `GET/POST /workflows/{slug}/edges/`, `PATCH/DELETE .../edges/{id}/` |
| **Executions** | `GET /executions/`, `GET .../executions/{id}/`, `POST .../cancel/` |
| **Chat** | `POST /workflows/{slug}/chat/`, `DELETE .../chat/history` |
| **Credentials** | `GET/POST /credentials/`, `GET/PATCH/DELETE .../credentials/{id}/`, `POST .../test/` |
| **Schedules** | `GET/POST /schedules/`, `GET/PATCH/DELETE .../schedules/{id}/`, `POST .../pause/`, `POST .../resume/` |
| **Users** | `GET/POST /users/`, `PATCH/DELETE .../users/{id}/`, `POST .../users/me/keys` |
| **Memory** | Facts, episodes, procedures, users, checkpoints — all with batch delete |

All list endpoints return `{"items": [...], "total": N}` with `limit`/`offset` pagination.

---

## Testing

```bash
cd platform
source ../.venv/bin/activate
export FIELD_ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
python -m pytest tests/ -v
```

---

## Redis Setup

Pipelit requires **Redis 8.0+** which includes RediSearch natively. Older versions will fail with `unknown command 'FT._LIST'`.

<details>
<summary><strong>Installing Redis 8.0+</strong></summary>

```bash
# Docker (easiest)
docker run -d --name redis -p 6379:6379 redis:8

# Debian/Ubuntu
curl -fsSL https://packages.redis.io/gpg | sudo gpg --dearmor -o /usr/share/keyrings/redis-archive-keyring.gpg
sudo chmod 644 /usr/share/keyrings/redis-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/redis-archive-keyring.gpg] https://packages.redis.io/deb $(lsb_release -cs) main" \
  | sudo tee /etc/apt/sources.list.d/redis.list
sudo apt-get update && sudo apt-get install redis

# macOS
brew install redis && brew services start redis
```

Verify: `redis-cli MODULE LIST` should include the `search` (ft) module.

</details>

<details>
<summary><strong>Removing older Redis</strong></summary>

```bash
# Debian/Ubuntu
sudo systemctl stop redis-server && sudo systemctl disable redis-server
sudo apt remove --purge redis-server

# macOS
brew services stop redis && brew uninstall redis

# Docker
docker stop redis && docker rm redis
```

</details>

<details>
<summary><strong>Workaround without Redis 8</strong></summary>

Enable `conversation_memory` on agent nodes that use `spawn_and_await`. This switches the checkpointer from RedisSaver to SqliteSaver, bypassing the RediSearch requirement.

</details>

---

## Documentation

Full documentation at [pipelit.theuseless.ai](https://pipelit.theuseless.ai).

---

## License

Apache 2.0 — see [LICENSE](LICENSE) for details.

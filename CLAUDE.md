# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AIChat Telegram Bot bridges Telegram messaging with a local AIChat server (Rust binary providing an OpenAI-compatible API gateway to Venice.ai GLM-4.7). Uses FastAPI + RQ for background task processing with Redis.

**Architecture Flow:**
```
┌─────────────────────────────────────────────────────────────┐
│                     Local Machine                           │
│                                                             │
│  ┌──────────────┐     ┌──────────────┐     ┌─────────────┐ │
│  │  Telegram    │     │   FastAPI    │     │ RQ Worker   │ │
│  │  Poller      │────▶│   Server     │────▶│  (tasks)    │ │
│  │  (async)     │     │  (optional)  │     │             │ │
│  └──────────────┘     └──────────────┘     └─────────────┘ │
│         │                    │                    │        │
│         └────────────────────┼────────────────────┘        │
│                              ▼                             │
│           ┌─────────────────────────────────┐              │
│           │         Redis + SQLite          │              │
│           └─────────────────────────────────┘              │
└─────────────────────────────────────────────────────────────┘
```

## Commands

### Run the Application

**Terminal 1 - Start Redis:**
```bash
# macOS: brew services start redis
# Linux: sudo systemctl start redis
redis-cli ping  # Should return PONG
```

**Terminal 2 - Start AIChat Server:**
```bash
aichat --serve
```

**Terminal 3 - Start RQ Worker:**
```bash
source .venv/bin/activate
rq worker high default low
```

**Terminal 4 - Start Telegram Bot:**
```bash
source .venv/bin/activate
python -m app.main
```

**Optional - RQ Dashboard (monitoring):**
```bash
rq-dashboard  # Opens at http://localhost:9181
```

### Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your TELEGRAM_BOT_TOKEN and ALLOWED_USER_IDS
```

## Code Architecture

```
app/
├── __init__.py
├── main.py              # Entry point - starts poller + optional API
├── config.py            # Pydantic settings
├── bot/
│   ├── poller.py        # Telegram polling (python-telegram-bot)
│   └── handlers.py      # Command & message handlers
├── gateway/             # Gateway for agent routing
│   ├── __init__.py
│   ├── router.py        # Classify messages → macro/agent/dynamic plan
│   ├── planner.py       # LLM-based dynamic planning
│   ├── executor.py      # Enqueue tasks to RQ
│   └── confirmation.py  # Redis-backed confirmations
├── api/                 # Optional - for future web UI
│   ├── health.py        # Health check endpoints
│   └── sessions.py      # REST API for sessions
├── services/
│   ├── telegram.py      # Bot API client (sync, for workers)
│   ├── aichat.py        # AIChat client (sync + async)
│   ├── sessions.py      # Session logic
│   └── tokens.py        # Token counting
├── models/
│   ├── database.py      # Database models
│   └── schemas.py       # Pydantic schemas
├── db/
│   └── repository.py    # Data access layer
└── tasks/
    ├── queues.py        # RQ queue definitions
    ├── chat.py          # Chat processing tasks
    └── agent_tasks.py   # Agent/macro execution tasks
```

### Key Components

- **app/config.py** - Pydantic settings loaded from `.env`
- **app/bot/handlers.py** - Telegram command handlers (`/start`, `/clear`, `/stats`, `/context`, `/pending`, `/confirm_*`, `/cancel_*`)
- **app/bot/poller.py** - Telegram polling setup
- **app/gateway/router.py** - Classifies messages to macro/agent/dynamic plan/chat
- **app/gateway/planner.py** - LLM-based dynamic planning for complex tasks
- **app/gateway/executor.py** - Enqueues tasks to appropriate RQ queues
- **app/gateway/confirmation.py** - Redis-backed confirmation for sensitive actions
- **app/services/sessions.py** - Session management with compression
- **app/tasks/chat.py** - Background tasks for RQ workers
- **app/tasks/agent_tasks.py** - Agent and macro execution via `aichat` CLI
- **app/tasks/queues.py** - Redis/RQ queue configuration

### Gateway Routing

When `GATEWAY_ENABLED=true`, messages are classified by the Router:

| Strategy | Trigger Pattern | Example |
|----------|-----------------|---------|
| **MACRO** | Predefined workflows | "generate commit message" |
| **AGENT** | Direct agent tasks | "go to google.com", "screenshot" |
| **DYNAMIC_PLAN** | Complex multi-step tasks | "find houses and compare them" |
| **CHAT** | Everything else | Regular conversation |

Actions matching confirmation patterns (buy, delete, send) require user confirmation.

### RQ Queues

- `high` - Commands, small messages (fast processing)
- `default` - Normal chat messages, agent tasks
- `low` - Compression, cleanup tasks
- `browser` - Browser agent tasks (single worker for Playwright)

## Key Technical Details

- Uses `httpx` for HTTP calls (async for bot, sync for workers)
- OpenAI-compatible request format: `{"model": ..., "messages": [...]}`
- All messages processed via RQ workers for consistent architecture
- Automatic conversation compression when tokens exceed threshold
- SQLite for session persistence (`sessions.db`)
- Redis for task queue (`localhost:6379`)

## Configuration

Key environment variables (see `.env.example`):

```bash
# Required
TELEGRAM_BOT_TOKEN=your_bot_token
ALLOWED_USER_IDS=123456789  # Comma-separated

# AIChat
AICHAT_BASE_URL=http://127.0.0.1:8000
AICHAT_MODEL=venice:zai-org-glm-4.7

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# Task settings
JOB_TIMEOUT=300  # 5 minutes

# Gateway settings
GATEWAY_ENABLED=true                    # Enable agent routing
CONFIRMATION_TIMEOUT_MINUTES=5          # Confirmation expiry
CHROME_PROFILE_PATH=~/.config/agent-chrome-profile
BROWSER_HEADLESS=true

# Optional API
API_ENABLED=false
API_PORT=8080
```

## Documentation

Detailed architecture diagrams, systemd service files, and roadmap are in `docs/main.md`.

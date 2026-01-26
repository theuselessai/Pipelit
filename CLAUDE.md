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
    └── chat.py          # Chat processing tasks
```

### Key Components

- **app/config.py** - Pydantic settings loaded from `.env`
- **app/bot/handlers.py** - Telegram command handlers (`/start`, `/clear`, `/stats`, `/context`)
- **app/bot/poller.py** - Telegram polling setup
- **app/services/sessions.py** - Session management with compression
- **app/tasks/chat.py** - Background tasks for RQ workers
- **app/tasks/queues.py** - Redis/RQ queue configuration

### RQ Queues

- `high` - Commands, small messages (fast processing)
- `default` - Normal chat messages
- `low` - Compression, cleanup tasks

## Key Technical Details

- Uses `httpx` for HTTP calls (async for bot, sync for workers)
- OpenAI-compatible request format: `{"model": ..., "messages": [...]}`
- Messages over `BACKGROUND_THRESHOLD_TOKENS` are processed via RQ
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

# Task thresholds
BACKGROUND_THRESHOLD_TOKENS=5000  # Use RQ above this
JOB_TIMEOUT=300  # 5 minutes

# Optional API
API_ENABLED=false
API_PORT=8080
```

## Documentation

Detailed architecture diagrams, systemd service files, and roadmap are in `docs/main.md`.

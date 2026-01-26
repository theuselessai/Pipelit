# AIChat Telegram Bot

A Python bot that bridges Telegram messaging with a local [AIChat](https://github.com/sigoden/aichat) server, providing access to Venice.ai GLM-4.7 through Telegram. Features session management, automatic context compression, and background task processing with Redis Queue.

## Architecture

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

## Features

- **Session Management** - Persistent conversations stored in SQLite
- **Context Compression** - Automatic summarization when context gets too long
- **Background Processing** - Long-running tasks handled via Redis Queue
- **Monitoring** - Built-in rq-dashboard for job monitoring
- **Access Control** - Whitelist users by Telegram ID

## Prerequisites

- Python 3.10+
- Redis server
- [AIChat](https://github.com/sigoden/aichat) installed and configured with Venice.ai
- Telegram Bot Token (from [@BotFather](https://t.me/botfather))

## Setup

1. **Clone the repository**
   ```bash
   git clone git@github.com:theuselessai/aibot_telegram_server.git
   cd aibot_telegram_server
   ```

2. **Create virtual environment and install dependencies**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Install Redis**
   ```bash
   # macOS
   brew install redis
   brew services start redis

   # Linux (Debian/Ubuntu)
   sudo apt install redis-server
   sudo systemctl start redis
   ```

4. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your TELEGRAM_BOT_TOKEN and ALLOWED_USER_IDS
   ```

## Running

**Terminal 1 - Start Redis (if not running as service):**
```bash
redis-server
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

## Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message and help |
| `/clear` | Clear conversation history |
| `/stats` | Show session statistics |
| `/context` | Show context window usage |

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather | Required |
| `ALLOWED_USER_IDS` | Comma-separated user IDs (empty = allow all) | Empty |
| `AICHAT_BASE_URL` | AIChat server URL | `http://127.0.0.1:8000` |
| `AICHAT_MODEL` | Model to use | `venice:zai-org-glm-4.7` |
| `REDIS_HOST` | Redis server host | `localhost` |
| `REDIS_PORT` | Redis server port | `6379` |
| `JOB_TIMEOUT` | Max time for RQ job (seconds) | `300` |
| `API_ENABLED` | Enable optional FastAPI server | `false` |

## Project Structure

```
app/
├── main.py              # Entry point
├── config.py            # Pydantic settings
├── bot/
│   ├── poller.py        # Telegram polling
│   └── handlers.py      # Command handlers
├── api/
│   ├── health.py        # Health endpoints
│   └── sessions.py      # REST API
├── services/
│   ├── telegram.py      # Telegram API client
│   ├── aichat.py        # AIChat client
│   ├── sessions.py      # Session management
│   └── tokens.py        # Token counting
├── models/
│   ├── database.py      # DB models
│   └── schemas.py       # Pydantic schemas
├── db/
│   └── repository.py    # Data access layer
└── tasks/
    ├── queues.py        # RQ queue definitions
    └── chat.py          # Background tasks
```

## License

MIT

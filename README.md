# AIChat Telegram Bot

A Python bot that bridges Telegram messaging with a local [AIChat](https://github.com/sigoden/aichat) server, providing access to Venice.ai GLM-4.7 through Telegram. Features intelligent agent routing, session management, automatic context compression, and background task processing with Redis Queue.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              LOCAL MACHINE                               │
│                                                                          │
│  ┌──────────────┐                                                        │
│  │   Telegram   │                                                        │
│  │     Bot      │                                                        │
│  └──────┬───────┘                                                        │
│         │                                                                │
│         ▼                                                                │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                          GATEWAY                                 │    │
│  │  ┌──────────┐   ┌──────────┐   ┌────────────┐   ┌────────────┐  │    │
│  │  │  Router  │ → │ Planner  │ → │  Executor  │ → │ Confirmer  │  │    │
│  │  │(classify)│   │(dynamic) │   │ (enqueue)  │   │  (Redis)   │  │    │
│  │  └──────────┘   └──────────┘   └────────────┘   └────────────┘  │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                    │                                     │
│         ┌──────────────────────────┼──────────────────────────┐         │
│         ▼                          ▼                          ▼         │
│  ┌─────────────┐          ┌─────────────┐          ┌─────────────┐      │
│  │   browser   │          │   default   │          │    high     │      │
│  │    queue    │          │    queue    │          │    queue    │      │
│  └──────┬──────┘          └──────┬──────┘          └──────┬──────┘      │
│         │                        │                        │             │
│         ▼                        ▼                        ▼             │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                         RQ WORKERS                               │    │
│  │     aichat --agent browser_agent    aichat --agent system_agent  │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                    │                                     │
│                                    ▼                                     │
│                    ┌───────────────────────────────┐                    │
│                    │       Redis + SQLite          │                    │
│                    └───────────────────────────────┘                    │
└─────────────────────────────────────────────────────────────────────────┘
```

## Features

- **LLM-based Routing** - Gateway classifies messages via aichat categorizer role
- **AIChat Agents** - Execute system commands, browser automation, and more via AIChat function calling
- **Dynamic Planning** - LLM-based planning for complex multi-step tasks
- **Confirmation Flow** - Sensitive actions require user confirmation
- **Session Management** - Persistent conversations stored in SQLite
- **Context Compression** - Automatic summarization when context gets too long
- **Background Processing** - Long-running tasks handled via Redis Queue
- **Access Control** - Whitelist users by Telegram ID

## Prerequisites

- Python 3.10+
- Redis server
- [AIChat](https://github.com/sigoden/aichat) installed and configured with Venice.ai
- [argc](https://github.com/sigoden/argc) (for agent tools): `cargo install argc`
- jq (for JSON parsing): `apt install jq` or `brew install jq`
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

5. **Setup AIChat categorizer role and agents** (required for gateway routing)
   ```bash
   ./scripts/create_categorizer_role.sh
   ./scripts/setup_system_agent.sh
   # Verify: aichat -r categorizer "hello"
   # Verify: aichat --list-agents
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
rq worker high default low browser
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
| `/pending` | Show pending confirmations |
| `/confirm_<id>` | Confirm a pending action |
| `/cancel_<id>` | Cancel a pending action |

## Gateway Routing

When `GATEWAY_ENABLED=true`, messages are classified by an LLM via `aichat -r categorizer`:

| Strategy | Description | Example |
|----------|-------------|---------|
| **AGENT** | System/browser tasks | "list files in /tmp", "check disk usage" |
| **MACRO** | Predefined workflows | "generate commit message" |
| **DYNAMIC** | Complex multi-step | "find houses and compare them" |
| **CHAT** | Everything else | Regular conversation |

The categorizer also determines when confirmation is needed (buy, delete, send, install, reboot).

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather | Required |
| `ALLOWED_USER_IDS` | Comma-separated user IDs | Empty (allow all) |
| `AICHAT_BASE_URL` | AIChat server URL | `http://127.0.0.1:8000` |
| `AICHAT_MODEL` | Model to use | `venice:zai-org-glm-4.7` |
| `REDIS_HOST` | Redis server host | `localhost` |
| `REDIS_PORT` | Redis server port | `6379` |
| `JOB_TIMEOUT` | Max time for RQ job (seconds) | `300` |
| `GATEWAY_ENABLED` | Enable agent routing | `true` |
| `CONFIRMATION_TIMEOUT_MINUTES` | Confirmation expiry | `5` |

## Project Structure

```
app/
├── main.py              # Entry point
├── config.py            # Pydantic settings
├── bot/
│   ├── poller.py        # Telegram polling
│   └── handlers.py      # Command handlers
├── gateway/
│   ├── router.py        # Route dataclasses + categorizer parser
│   ├── planner.py       # Dynamic planning
│   ├── executor.py      # Task enqueueing
│   └── confirmation.py  # Confirmation handling
├── services/
│   ├── telegram.py      # Telegram API client
│   ├── aichat.py        # AIChat client
│   ├── sessions.py      # Session management
│   ├── agent_setup.py   # Agent setup utilities
│   └── tokens.py        # Token counting
├── tasks/
│   ├── queues.py        # RQ queue definitions
│   ├── categorizer.py   # LLM message categorization
│   ├── chat.py          # Chat processing
│   └── agent_tasks.py   # Agent execution
├── models/              # DB models & schemas
└── db/                  # Data access layer

docs/
├── aichat_agents_setup.md   # Agent setup guide
└── dev_plan_gateway.md      # Architecture plan

scripts/
├── create_categorizer_role.sh  # Categorizer role setup
└── setup_system_agent.sh       # Agent setup script
```

## Documentation

- [AIChat Agents Setup Guide](docs/aichat_agents_setup.md) - How to create and configure agents
- [Gateway Architecture Plan](docs/dev_plan_gateway.md) - Detailed architecture and roadmap

## License

MIT

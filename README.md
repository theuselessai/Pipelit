# LangChain Telegram Bot

A Python bot that bridges Telegram messaging with LLM providers via LangChain. Supports OpenAI, Anthropic, and any OpenAI-compatible endpoint (Venice.ai, Ollama, etc.). Features intelligent agent routing, session management, automatic context compression, and background task processing with Redis Queue.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                          LOCAL MACHINE                           │
│                                                                  │
│  ┌──────────────┐                                                │
│  │   Telegram   │                                                │
│  │   Message    │                                                │
│  └──────┬───────┘                                                │
│         │                                                        │
│         ▼                                                        │
│  ┌──────────────┐     ┌──────────────────────────────────────┐  │
│  │   Telegram   │     │             GATEWAY                   │  │
│  │   Poller     │────▶│                                       │  │
│  │  (async)     │     │  ┌────────────┐    ┌──────────────┐  │  │
│  └──────────────┘     │  │ Categorizer│───▶│   Executor   │  │  │
│                       │  │  (LLM)     │    │  (enqueue)   │  │  │
│                       │  └────────────┘    └──────┬───────┘  │  │
│                       │                           │          │  │
│                       │         ┌─────────────────┼────┐     │  │
│                       │         │                 │    │     │  │
│                       │         ▼                 ▼    ▼     │  │
│                       │  ┌───────────┐  ┌─────┐  ┌────────┐ │  │
│                       │  │  Planner  │  │Chat │  │Confirm │ │  │
│                       │  │ (dynamic) │  │     │  │(Redis) │ │  │
│                       │  └───────────┘  └─────┘  └────────┘ │  │
│                       └──────────────────────────────────────┘  │
│                                    │                             │
│         ┌──────────────────────────┼──────────────────┐         │
│         ▼                          ▼                  ▼         │
│  ┌─────────────┐          ┌─────────────┐     ┌───────────┐    │
│  │   browser   │          │   default   │     │   high    │    │
│  │    queue    │          │    queue    │     │   queue   │    │
│  └──────┬──────┘          └──────┬──────┘     └─────┬─────┘    │
│         │                        │                  │          │
│         ▼                        ▼                  ▼          │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                       RQ WORKERS                         │   │
│  │                                                          │   │
│  │  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐  │   │
│  │  │   Browser   │  │    System    │  │    Research    │  │   │
│  │  │   Agent     │  │    Agent     │  │    Agent       │  │   │
│  │  │ (Playwright)│  │   (shell)    │  │  (analysis)    │  │   │
│  │  └─────────────┘  └──────────────┘  └────────────────┘  │   │
│  │                                                          │   │
│  │  LangGraph react agents with tool-calling                │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                    │                            │
│                                    ▼                            │
│                    ┌───────────────────────────────┐           │
│                    │     Redis + SQLite + LLM      │           │
│                    │  (queues) (sessions) (provider)│           │
│                    └───────────────────────────────┘           │
└─────────────────────────────────────────────────────────────────┘
```

### Message Flow

```
User sends message on Telegram
         │
         ▼
   ┌───────────┐    GATEWAY_ENABLED=false    ┌───────────────┐
   │  Poller   │───────────────────────────▶│  Chat (LLM)   │──▶ Reply
   │           │                             └───────────────┘
   │           │    GATEWAY_ENABLED=true
   │           │──────────┐
   └───────────┘          ▼
                   ┌──────────────┐
                   │  Categorizer │  Classifies message using LLM
                   │  (+ history) │  with recent conversation context
                   └──────┬───────┘
                          │
              ┌───────────┼───────────┐
              ▼           ▼           ▼
        ┌──────────┐ ┌────────┐ ┌──────────┐
        │  AGENT   │ │  CHAT  │ │ DYNAMIC  │
        │          │ │        │ │  PLAN    │
        └────┬─────┘ └───┬────┘ └────┬─────┘
             │           │           │
             ▼           ▼           ▼
       ┌──────────┐ ┌────────┐ ┌──────────┐
       │ LangGraph│ │  LLM   │ │ Planner  │
       │  Agent   │ │  Chat  │ │  creates │
       │ (tools)  │ │  (no   │ │  steps,  │
       │          │ │ tools) │ │  runs    │
       │ system/  │ │        │ │  agents  │
       │ browser/ │ │        │ │  in      │
       │ research │ │        │ │ sequence │
       └────┬─────┘ └───┬────┘ └────┬─────┘
            │           │           │
            └───────────┼───────────┘
                        ▼
              ┌──────────────────┐
              │  Save to session │
              │  Reply to user   │
              └──────────────────┘
```

## Features

- **LLM-based Routing** - Gateway classifies messages using LangChain LLM with conversation context
- **LangGraph Agents** - System commands, browser automation, and research via LangGraph react agents with tool-calling
- **Dynamic Planning** - LLM-based planning for complex multi-step tasks
- **Confirmation Flow** - Sensitive actions (buy, delete, install, reboot) require user confirmation
- **Session Management** - Persistent conversations stored in SQLite with full history
- **Context Compression** - Automatic summarization when token count exceeds threshold
- **Background Processing** - All tasks processed via Redis Queue workers
- **Access Control** - Whitelist users by Telegram ID

## Prerequisites

- Python 3.10+
- Redis server
- Telegram Bot Token (from [@BotFather](https://t.me/botfather))
- An LLM provider: OpenAI API key, Anthropic API key, or any OpenAI-compatible endpoint

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
   # Edit .env with your TELEGRAM_BOT_TOKEN, ALLOWED_USER_IDS, and LLM settings
   ```

## Running

**Terminal 1 - Start Redis (if not running as service):**
```bash
redis-server
```

**Terminal 2 - Start RQ Worker:**
```bash
source .venv/bin/activate
rq worker high default low browser
```

**Terminal 3 - Start Telegram Bot:**
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

When `GATEWAY_ENABLED=true`, messages are classified by an LLM categorizer with conversation context:

| Strategy | Description | Example |
|----------|-------------|---------|
| **AGENT** | System/browser/research tasks | "run df", "go to google.com", "analyze this text" |
| **DYNAMIC** | Complex multi-step tasks | "find houses and compare them" |
| **CHAT** | Everything else | Regular conversation, questions, greetings |

The categorizer also determines when confirmation is needed (buy, delete, send, install, reboot).

### Agents

| Agent | Queue | Description |
|-------|-------|-------------|
| `system_agent` | `default` | Shell commands, file operations, process management |
| `browser_agent` | `browser` | Web navigation, screenshots, form filling (Playwright) |
| `research_agent` | `default` | Text analysis, comparison, summarization |

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather | Required |
| `ALLOWED_USER_IDS` | Comma-separated user IDs | Empty (allow all) |
| `LLM_PROVIDER` | `openai`, `anthropic`, or `openai_compatible` | `openai_compatible` |
| `LLM_MODEL` | Model name | Required |
| `LLM_API_KEY` | API key for the provider | Required |
| `LLM_BASE_URL` | Base URL (for openai_compatible) | `http://127.0.0.1:8000/v1` |
| `LLM_TEMPERATURE` | Temperature for generation | `0.7` |
| `CATEGORIZER_MODEL` | Separate model for categorization | Same as `LLM_MODEL` |
| `REDIS_HOST` | Redis server host | `localhost` |
| `REDIS_PORT` | Redis server port | `6379` |
| `JOB_TIMEOUT` | Max time for RQ job (seconds) | `300` |
| `GATEWAY_ENABLED` | Enable agent routing | `true` |
| `CONFIRMATION_TIMEOUT_MINUTES` | Confirmation expiry | `5` |
| `CHROME_PROFILE_PATH` | Chrome profile for browser agent | `~/.config/agent-chrome-profile` |
| `BROWSER_HEADLESS` | Run browser headless | `true` |
| `API_ENABLED` | Enable optional REST API | `false` |
| `API_PORT` | REST API port | `8080` |

## Project Structure

```
app/
├── main.py              # Entry point
├── config.py            # Pydantic settings
├── bot/
│   ├── poller.py        # Telegram polling
│   └── handlers.py      # Command & message handlers
├── gateway/
│   ├── router.py        # Route dataclasses + categorizer parser
│   ├── planner.py       # Dynamic planning
│   ├── executor.py      # Task enqueueing
│   └── confirmation.py  # Confirmation handling
├── agents/
│   ├── base.py          # Agent factory (LangGraph react agents)
│   ├── system_agent.py  # Shell, file, process tools
│   ├── browser_agent.py # Playwright browser tools
│   └── research_agent.py# Analysis and summarization
├── tools/
│   ├── system.py        # shell_execute, file_read/write, disk_usage, etc.
│   ├── browser.py       # navigate, screenshot, click, type, get_page_text
│   └── research.py      # analyze_text, compare_items
├── services/
│   ├── telegram.py      # Telegram API client (sync, for workers)
│   ├── llm.py           # LangChain LLM factory + service
│   ├── sessions.py      # Session management
│   └── tokens.py        # Token counting
├── tasks/
│   ├── queues.py        # RQ queue definitions
│   ├── categorizer.py   # LLM message categorization
│   ├── chat.py          # Chat processing
│   └── agent_tasks.py   # Agent execution
├── models/              # DB models & schemas
└── db/                  # Data access layer
```

## License

MIT

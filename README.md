# AIChat Telegram Bot

A lightweight Python relay that bridges Telegram messaging with a local [AIChat](https://github.com/sigoden/aichat) server, providing access to Venice.ai GLM-4.7 through Telegram.

## Architecture

```
Telegram User → Telegram Cloud → This Bot (Python) → AIChat Server (localhost:8000) → Venice.ai
```

## Prerequisites

- Python 3.10+
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

3. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your TELEGRAM_BOT_TOKEN and ALLOWED_USER_IDS
   ```

## Running

**Terminal 1 - Start AIChat Server:**
```bash
aichat --serve
```

**Terminal 2 - Start Telegram Bot:**
```bash
source .venv/bin/activate
python main.py
```

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather | Required |
| `ALLOWED_USER_IDS` | Comma-separated user IDs (empty = allow all) | Empty |
| `AICHAT_BASE_URL` | AIChat server URL | `http://127.0.0.1:8000` |
| `AICHAT_MODEL` | Model to use | `venice:glm-4.7` |

## Project Structure

```
├── main.py          # Telegram bot handlers
├── config.py        # Environment configuration
├── requirements.txt # Python dependencies
├── .env.example     # Environment template
└── docs/main.md     # Detailed architecture docs
```

## License

MIT

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AIChat Telegram Bot is a lightweight Python relay that bridges Telegram messaging with a local AIChat server (Rust binary providing an OpenAI-compatible API gateway to Venice.ai GLM-4.7).

**Architecture Flow:**
```
Telegram User → Telegram Cloud → This Bot (Python) → AIChat Server (localhost:8000) → Venice.ai API
```

## Commands

### Run the Application

**Terminal 1 - Start AIChat Server:**
```bash
aichat --serve
```

**Terminal 2 - Start Telegram Bot:**
```bash
source .venv/bin/activate
python main.py
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

The bot is intentionally minimal (~120 lines total across 2 files):

- **main.py** - Entry point with Telegram handlers
  - `chat_with_aichat()` - Makes POST to `{AICHAT_BASE_URL}/v1/chat/completions`
  - `is_allowed()` - Whitelist check (empty whitelist = allow all)
  - `handle_message()` - Relays user text to AIChat, splits long responses (>4096 chars)

- **config.py** - Loads `.env` and exposes `config` object with:
  - `TELEGRAM_BOT_TOKEN`, `ALLOWED_USER_IDS` (list of ints)
  - `AICHAT_BASE_URL` (default: http://127.0.0.1:8000)
  - `AICHAT_MODEL` (default: venice:glm-4.7)

## Key Technical Details

- Uses `httpx.AsyncClient` with 120s timeout for AIChat calls
- OpenAI-compatible request format: `{"model": ..., "messages": [{"role": "user", "content": ...}]}`
- Response extraction: `choices[0]["message"]["content"]`
- Full async implementation using `python-telegram-bot` Application
- Stateless relay - AIChat handles any session/context management

## Documentation

Detailed architecture diagrams, systemd service files, and Phase 2+ roadmap (sessions, roles, RAG) are in `docs/main.md`.

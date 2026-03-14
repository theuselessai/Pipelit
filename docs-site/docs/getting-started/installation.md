# Installation

## Via plit CLI (Recommended)

The simplest way to get Pipelit running is via the [plit](https://github.com/theuselessai/plit) CLI, which manages Pipelit and the message gateway as Docker containers:

```bash
curl -fsSL https://raw.githubusercontent.com/theuselessai/plit/main/install.sh | bash
```

This installs the `plit` binary to `~/.local/bin/`. Then run `plit init` to configure and `plit start` to launch everything.

---

## Standalone Setup (Development)

For contributors or anyone running Pipelit outside Docker.

### Prerequisites

| Requirement | Minimum Version | Purpose |
|-------------|----------------|---------|
| Python | 3.10+ | Backend runtime |
| Redis | 8.0+ | Task queue, pub/sub, search |
| Node.js | 18+ | Frontend build |
| bubblewrap | 0.4+ | Sandboxed shell execution (Linux only) |

!!! warning "Redis 8.0+ Required"
    Pipelit requires Redis 8.0+ which includes RediSearch natively. Older versions will fail with `unknown command 'FT._LIST'`. See the [Redis setup guide](../deployment/redis.md) for installation instructions.

!!! note "Bubblewrap (Linux only)"
    Deep agent nodes use bubblewrap (`bwrap`) to sandbox shell command execution.
    Most Linux distros ship it by default. Install via `apt install bubblewrap` or
    `dnf install bubblewrap`. On macOS, the built-in `sandbox-exec` is used instead.
    If neither is available, shell execution is **refused** — Pipelit does not fall back to unsandboxed execution.

### Clone the Repository

```bash
git clone git@github.com:theuselessai/Pipelit.git
cd Pipelit
```

### Backend Setup

Create a Python virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r platform/requirements.txt
```

### Frontend Setup

Install Node.js dependencies:

```bash
cd platform/frontend
npm install
```

### Verify Installation

```bash
# Python packages
python -c "import fastapi; print(f'FastAPI {fastapi.__version__}')"
python -c "import sqlalchemy; print(f'SQLAlchemy {sqlalchemy.__version__}')"

# Redis
redis-cli ping  # Should return PONG

# Node
node --version   # Should be 18+
```

## Next Step

Continue to [Configuration](configuration.md) to set up your environment variables.

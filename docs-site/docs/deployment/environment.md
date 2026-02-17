# Environment Variables

Pipelit is configured through environment variables, loaded from a `.env` file in the repository root (one level above `platform/`). The configuration is managed by Pydantic Settings in `platform/config.py`.

## Variable Reference

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `FIELD_ENCRYPTION_KEY` | `""` (empty) | **Yes** | Fernet encryption key for securing stored credentials (API keys, bot tokens, etc.). Generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Without this key, credential storage will not work. |
| `SECRET_KEY` | `change-me-in-production` | **Yes** (production) | Secret key used for cryptographic signing. Must be changed from the default in production deployments. Use a long, random string. |
| `DATABASE_URL` | `sqlite:///platform/db.sqlite3` | No | SQLAlchemy database connection string. Defaults to a SQLite file inside the `platform/` directory. Set to a PostgreSQL URL for production (e.g., `postgresql://user:pass@localhost/pipelit`). |
| `REDIS_URL` | `redis://localhost:6379/0` | No | Redis connection URL. Used for RQ task queuing, pub/sub broadcasting, and RediSearch. Format: `redis://[:password]@host:port/db_number`. |
| `DEBUG` | `false` | No | Enable debug mode. Set to `true` for development. Should always be `false` in production. |
| `ALLOWED_HOSTS` | `localhost` | No | Comma-separated list of allowed hostnames. Set to your domain name in production (e.g., `pipelit.example.com`). |
| `CORS_ALLOW_ALL_ORIGINS` | `true` | No | Allow cross-origin requests from any domain. Set to `false` in production and configure specific allowed origins through your reverse proxy. |
| `ZOMBIE_EXECUTION_THRESHOLD_SECONDS` | `900` (15 min) | No | Time in seconds after which a running execution is considered a zombie and eligible for cleanup. The system marks stale executions as failed and releases their resources. |
| `LOG_LEVEL` | `INFO` | No | Logging level. Supported values: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |
| `LOG_FILE` | `""` (empty) | No | Path to a log file. When set, logs are written to this file in addition to the console. Example: `logs/pipelit.log`. The parent directory must exist. |

## `.env` File Location

The `.env` file should be placed in the **repository root** (the directory containing `platform/`), not inside the `platform/` directory:

```
Pipelit/
├── .env              <-- here
├── platform/
│   ├── main.py
│   ├── config.py
│   └── ...
└── ...
```

Pipelit uses `python-dotenv` to load the `.env` file from `BASE_DIR.parent` (one level above `platform/`).

## Minimal Development Configuration

```env title=".env"
FIELD_ENCRYPTION_KEY=your-generated-fernet-key
REDIS_URL=redis://localhost:6379/0
```

## Production Configuration

```env title=".env"
FIELD_ENCRYPTION_KEY=your-generated-fernet-key
SECRET_KEY=a-long-random-string-at-least-32-characters
DEBUG=false
ALLOWED_HOSTS=pipelit.example.com
CORS_ALLOW_ALL_ORIGINS=false
REDIS_URL=redis://localhost:6379/0
DATABASE_URL=sqlite:///opt/pipelit/platform/db.sqlite3
ZOMBIE_EXECUTION_THRESHOLD_SECONDS=900
LOG_FILE=logs/pipelit.log
LOG_LEVEL=INFO
```

## Generating the Encryption Key

The `FIELD_ENCRYPTION_KEY` is a Fernet key used to encrypt sensitive credential data (LLM API keys, Telegram bot tokens, etc.) at rest in the database. Generate one with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

!!! danger "Keep your encryption key safe"
    If you lose the `FIELD_ENCRYPTION_KEY`, all stored credentials become unreadable. Back up this key securely. If you change the key, existing encrypted credentials cannot be decrypted -- you will need to re-enter them.

## Environment Variables for Tests

Tests require `FIELD_ENCRYPTION_KEY` to be set. The test `conftest.py` auto-generates a temporary key if one is not provided:

```bash
cd platform
export FIELD_ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
python -m pytest tests/ -v
```

## How Configuration is Loaded

Configuration is managed by Pydantic Settings (`platform/config.py`):

1. Values from the `.env` file are loaded via `python-dotenv`
2. Environment variables override `.env` file values
3. Default values are used if neither is provided
4. The `Settings` class validates types and provides the `settings` singleton

```python
from config import settings

# Access any setting
print(settings.REDIS_URL)
print(settings.DATABASE_URL)
print(settings.DEBUG)
```

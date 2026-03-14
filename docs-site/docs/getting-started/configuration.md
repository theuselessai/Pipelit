# Configuration

Pipelit uses a `.env` file in the project root for configuration. The backend loads it via Pydantic Settings.

## Generate Encryption Key (Optional)

Pipelit encrypts sensitive credential data (API keys, tokens) at rest using Fernet symmetric encryption. For production, generate your own key:

```bash
python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Copy the output to use in your `.env` file (for production deployments).

## Create `.env` File

Create a `.env` file in the project root (not inside `platform/`):

```env
# FIELD_ENCRYPTION_KEY=your-generated-fernet-key-here  # Optional: auto-generated if not set
REDIS_URL=redis://localhost:6379/0
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `FIELD_ENCRYPTION_KEY` | *(auto-generated if not set)* | Fernet key for encrypting credential secrets |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL for RQ and pub/sub |
| `DATABASE_URL` | `sqlite:///platform/db.sqlite3` | SQLAlchemy database URL |
| `SECRET_KEY` | `change-me-in-production` | Key for token signing |
| `DEBUG` | `false` | Enable debug mode |
| `ALLOWED_HOSTS` | `localhost` | Comma-separated allowed hosts |
| `CORS_ALLOW_ALL_ORIGINS` | `true` | Allow all CORS origins (disable in production) |
| `ZOMBIE_EXECUTION_THRESHOLD_SECONDS` | `900` | Seconds before a running execution is considered stuck (15 min) |

### Gateway Integration

If running alongside the [plit message gateway](https://github.com/theuselessai/plit), configure these additional variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `GATEWAY_URL` | *(none)* | Gateway base URL (e.g., `http://localhost:8080`) |
| `GATEWAY_ADMIN_TOKEN` | *(none)* | Token for gateway admin API (credential sync) |
| `GATEWAY_SEND_TOKEN` | *(none)* | Token for sending messages via gateway |
| `GATEWAY_INBOUND_TOKEN` | *(none)* | Token the gateway uses to send inbound messages to Pipelit |

!!! tip "Production Configuration"
    For production deployments, see the [Environment Variables](../deployment/environment.md) reference for the full list of settings and recommended values.

## conf.json

`conf.json` is a second configuration layer managed by the CLI. It is created by `python -m cli setup` at `platform/conf.json` and stores auto-generated secrets:

| Key | Description |
|-----|-------------|
| `field_encryption_key` | Auto-generated Fernet key if `FIELD_ENCRYPTION_KEY` is not present in `.env`. |

Values in `.env` always take precedence over `conf.json`.

!!! tip "What this means in practice"
    On a fresh install you do not need to generate a Fernet key manually — the CLI setup command creates one and persists it in `conf.json`. For production, set `FIELD_ENCRYPTION_KEY` explicitly in `.env` so the key is under your control and backed up.

!!! warning "Do not delete conf.json"
    If you delete `conf.json`, the auto-generated keys are lost. Any credentials encrypted with the old `field_encryption_key` will become unreadable.

## Database

By default, Pipelit uses SQLite for development. The database file is created automatically at `platform/db.sqlite3` on first startup. For production, consider [PostgreSQL](../deployment/database.md).

## Next Step

Continue to [First Run](first-run.md) to start the services.

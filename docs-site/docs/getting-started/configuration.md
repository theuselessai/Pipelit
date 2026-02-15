# Configuration

Pipelit uses a `.env` file in the project root for configuration. The backend loads it via Pydantic Settings.

## Generate Encryption Key

Pipelit encrypts sensitive credential data (API keys, tokens) at rest using Fernet symmetric encryption. You must generate a key before first use:

```bash
python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Copy the output — you'll need it for your `.env` file.

## Create `.env` File

Create a `.env` file in the project root (not inside `platform/`):

```env
FIELD_ENCRYPTION_KEY=your-generated-fernet-key-here
REDIS_URL=redis://localhost:6379/0
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `FIELD_ENCRYPTION_KEY` | *(required)* | Fernet key for encrypting credential secrets |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL for RQ and pub/sub |
| `DATABASE_URL` | `sqlite:///platform/db.sqlite3` | SQLAlchemy database URL |
| `SECRET_KEY` | `change-me-in-production` | Key for token signing |
| `DEBUG` | `false` | Enable debug mode |
| `ALLOWED_HOSTS` | `localhost` | Comma-separated allowed hosts |
| `CORS_ALLOW_ALL_ORIGINS` | `true` | Allow all CORS origins (disable in production) |
| `ZOMBIE_EXECUTION_THRESHOLD_SECONDS` | `900` | Seconds before a running execution is considered stuck (15 min) |

!!! tip "Production Configuration"
    For production deployments, see the [Environment Variables](../deployment/environment.md) reference for the full list of settings and recommended values.

## Database

By default, Pipelit uses SQLite for development. The database file is created automatically at `platform/db.sqlite3` on first startup. For production, consider [PostgreSQL](../deployment/database.md).

## Next Step

Continue to [First Run](first-run.md) to start the services.

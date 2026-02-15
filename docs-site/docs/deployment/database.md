# Database Setup

Pipelit uses SQLAlchemy 2.0 as its ORM and supports both SQLite and PostgreSQL as database backends. The database stores workflows, nodes, edges, executions, credentials, user accounts, and all other persistent state.

## SQLite (Development)

SQLite is the default database backend and requires zero configuration. On first startup, Pipelit automatically creates the database file at `platform/db.sqlite3`.

```env title=".env"
# This is the default — no configuration needed
DATABASE_URL=sqlite:///platform/db.sqlite3
```

SQLite is a good choice for:

- Local development
- Single-user or small-team deployments
- Quick prototyping and testing

!!! warning "SQLite limitations"
    SQLite allows only one writer at a time. Under heavy concurrent load (multiple RQ workers, many simultaneous API requests), you may encounter `database is locked` errors. For production deployments with significant traffic, use PostgreSQL.

### Checkpoints Database

Agent conversation memory uses a separate SQLite database at `platform/checkpoints.db`. This file is created automatically when an agent with `conversation_memory` enabled runs for the first time.

## PostgreSQL (Production)

For production deployments, PostgreSQL is recommended. It handles concurrent reads and writes efficiently and supports advanced features like connection pooling.

### Setup

1. Install PostgreSQL:

    ```bash
    # Debian/Ubuntu
    sudo apt install postgresql postgresql-contrib

    # macOS
    brew install postgresql && brew services start postgresql
    ```

2. Create a database and user:

    ```bash
    sudo -u postgres psql

    CREATE USER pipelit WITH PASSWORD 'your-password';
    CREATE DATABASE pipelit OWNER pipelit;
    \q
    ```

3. Update your `.env` file:

    ```env
    DATABASE_URL=postgresql://pipelit:your-password@localhost/pipelit
    ```

4. Install the PostgreSQL driver:

    ```bash
    pip install psycopg2-binary
    ```

5. Restart the backend — tables are created automatically on startup.

## Alembic Migrations

Pipelit uses [Alembic](https://alembic.sqlalchemy.org/) for database schema migrations. Migrations track every change to the database schema over time, allowing safe upgrades and rollbacks.

### Automatic Migration on Startup

The FastAPI application calls `Base.metadata.create_all()` during its `lifespan` startup handler. This ensures that all tables exist when the application starts. For development, this is sufficient.

### Running Migrations Manually

For production deployments, you can run Alembic migrations explicitly:

```bash
cd platform
source ../.venv/bin/activate

# Apply all pending migrations
alembic upgrade head

# Check current migration version
alembic current

# View migration history
alembic history --verbose
```

### Creating New Migrations

When you modify SQLAlchemy models, generate a new migration:

```bash
cd platform
source ../.venv/bin/activate

# Check for conflicting migration heads first
alembic heads

# Auto-generate a migration from model changes
alembic revision --autogenerate -m "describe your change"

# Review the generated migration file in platform/alembic/versions/
# Then apply it
alembic upgrade head
```

!!! warning "Always check for conflicts"
    Before creating a new migration, run `alembic heads` to verify there is only one head. Multiple heads indicate conflicting migrations that must be merged before proceeding. See [Migrations](../contributing/migrations.md) for details.

## Backup Strategies

### SQLite Backups

SQLite databases are single files, making backups straightforward:

```bash
# Simple file copy (stop the application first for consistency)
cp platform/db.sqlite3 backups/db-$(date +%Y%m%d-%H%M%S).sqlite3

# Using SQLite's online backup API (safe while running)
sqlite3 platform/db.sqlite3 ".backup 'backups/db-backup.sqlite3'"

# Also back up the checkpoints database
sqlite3 platform/checkpoints.db ".backup 'backups/checkpoints-backup.db'"
```

Set up a cron job for automated backups:

```bash
# Daily backup at 2 AM
0 2 * * * sqlite3 /opt/pipelit/platform/db.sqlite3 ".backup '/opt/backups/pipelit-$(date +\%Y\%m\%d).sqlite3'"
```

### PostgreSQL Backups

```bash
# Full database dump
pg_dump -U pipelit pipelit > backups/pipelit-$(date +%Y%m%d-%H%M%S).sql

# Compressed dump
pg_dump -U pipelit pipelit | gzip > backups/pipelit-$(date +%Y%m%d).sql.gz

# Restore from backup
psql -U pipelit pipelit < backups/pipelit-20260215.sql
```

### What to Back Up

| Item | Location | Purpose |
|------|----------|---------|
| Main database | `platform/db.sqlite3` or PostgreSQL | All workflows, nodes, executions, users, credentials |
| Checkpoints database | `platform/checkpoints.db` | Agent conversation memory |
| `.env` file | Repository root | Configuration and encryption key |
| `FIELD_ENCRYPTION_KEY` | In `.env` | Required to decrypt stored credentials |

!!! danger "Back up your encryption key"
    The `FIELD_ENCRYPTION_KEY` is essential. Without it, all encrypted credentials in the database are permanently unreadable. Store a copy of this key in a secure location separate from your database backups.

## Migrating from SQLite to PostgreSQL

To migrate an existing SQLite deployment to PostgreSQL:

1. Export data from SQLite (application-level, not raw SQL)
2. Set up PostgreSQL as described above
3. Update `DATABASE_URL` in `.env`
4. Start the application (tables are created automatically)
5. Import the data

!!! note
    There is no built-in migration tool for moving data between database backends. For small deployments, re-creating workflows through the UI or API is often simpler than attempting a raw data migration.

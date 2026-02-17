# First Run

With dependencies installed and your `.env` configured, you're ready to start Pipelit.

## Start Redis

Ensure Redis 8.0+ is running:

```bash
# If installed via package manager
sudo systemctl start redis

# Or via Docker
docker run -d --name redis -p 6379:6379 redis:8
```

Verify: `redis-cli ping` should return `PONG`.

## Start All Services

Start everything with a single command using honcho:

```bash
cd platform
source ../.venv/bin/activate
honcho start
```

This launches four processes defined in the `Procfile`:

| Process | Description |
|---------|-------------|
| **server** | FastAPI backend on `:8000` with auto-reload |
| **frontend** | Vite dev server on `:5173`, proxies `/api` to `:8000` |
| **scheduler** | RQ worker with `--with-scheduler` for delayed/recurring jobs |
| **worker** | RQ worker pool (2 workers) for parallel job processing |

The backend auto-creates the SQLite database and runs Alembic migrations on first startup.

!!! tip "Production Mode"
    For production, build the frontend once with `npm run build` and access everything through the FastAPI server at `http://localhost:8000`. No separate frontend server needed.

??? note "Manual startup (without honcho)"
    If you prefer to start services individually in separate terminals:

    ```bash
    # Terminal 1 — Backend
    cd platform && source ../.venv/bin/activate
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload

    # Terminal 2 — RQ Worker with scheduler
    cd platform && source ../.venv/bin/activate
    rq worker --worker-class worker_class.PipelitWorker workflows --with-scheduler

    # Terminal 3 — Frontend (dev)
    cd platform/frontend
    npm run dev
    ```

## Setup Wizard

Open `http://localhost:5173` in your browser. On first visit, the setup wizard will prompt you to create your admin account:

1. Choose a **username**
2. Set a **password**
3. Click **Create Account**

This creates the first user with full admin privileges and generates an API key for authentication.

## Verify Everything Works

After logging in, you should see the workflow dashboard. Verify the backend is healthy:

```bash
# Check API is responding
curl -s http://localhost:8000/api/v1/auth/setup-status/ | python -m json.tool

# Check Redis connection
redis-cli ping
```

## Next Step

Continue to the [Quickstart Tutorial](quickstart-tutorial.md) to build your first workflow.

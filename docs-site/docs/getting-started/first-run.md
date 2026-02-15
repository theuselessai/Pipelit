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

## Start the Backend

Open a terminal and start the FastAPI server:

```bash
cd platform
source ../.venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

The backend auto-creates the SQLite database and runs Alembic migrations on first startup.

## Start the RQ Worker

Open a second terminal for the background task worker:

```bash
cd platform
source ../.venv/bin/activate
rq worker workflows --with-scheduler
```

The RQ worker executes workflow runs and scheduled jobs. The `--with-scheduler` flag enables the built-in scheduler for delayed/recurring tasks.

## Start the Frontend (Development)

Open a third terminal for the Vite dev server:

```bash
cd platform/frontend
npm run dev
```

The dev server runs at `http://localhost:5173` and proxies `/api` requests to the FastAPI backend at port 8000.

!!! tip "Production Mode"
    For production, build the frontend once with `npm run build` and access everything through the FastAPI server at `http://localhost:8000`. No separate frontend server needed.

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

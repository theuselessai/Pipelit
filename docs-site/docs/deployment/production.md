# Production Deployment

This guide covers deploying Pipelit on a bare-metal server or VM with production-grade process management, frontend builds, and security hardening.

## Overview

A production Pipelit deployment consists of:

1. **Gunicorn** with Uvicorn workers serving the FastAPI application
2. **RQ worker** processing background jobs
3. **Redis 8.0+** for task queuing and pub/sub
4. **A reverse proxy** (Nginx or Caddy) handling HTTPS and WebSocket upgrade
5. **A database** (SQLite for small deployments, PostgreSQL recommended)

## Building the Frontend

In production, the frontend is compiled into static files and served directly by FastAPI. There is no need for the Vite dev server.

```bash
cd platform/frontend
npm install
npm run build
```

This produces optimized static assets in `platform/frontend/dist/`. FastAPI automatically serves these files and the SPA's `index.html` for all non-API routes.

!!! tip
    Run `npm run build` once after each update. The built files are served directly by FastAPI at `http://your-server:8000/`.

## Gunicorn with Uvicorn Workers

For production, use Gunicorn as the process manager with Uvicorn workers:

```bash
cd platform
source ../.venv/bin/activate

gunicorn main:app \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers 4 \
    --bind 0.0.0.0:8000 \
    --timeout 120 \
    --graceful-timeout 30 \
    --access-logfile - \
    --error-logfile -
```

**Worker count:** A common rule of thumb is `(2 * CPU_CORES) + 1`. For a 2-core server, use 4--5 workers.

!!! warning "WebSocket and worker count"
    Each WebSocket connection is held open by a single worker. With Gunicorn's pre-fork model, WebSocket connections are pinned to the worker that accepted them. Ensure you have enough workers to handle both HTTP requests and persistent WebSocket connections.

## Process Management with systemd

Create systemd service files to ensure Pipelit starts on boot and restarts on failure.

### Backend Service

```ini title="/etc/systemd/system/pipelit.service"
[Unit]
Description=Pipelit Backend
After=network.target redis.service
Requires=redis.service

[Service]
Type=simple
User=pipelit
Group=pipelit
WorkingDirectory=/opt/pipelit/platform
Environment="PATH=/opt/pipelit/.venv/bin:/usr/bin"
EnvironmentFile=/opt/pipelit/.env
ExecStart=/opt/pipelit/.venv/bin/gunicorn main:app \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers 4 \
    --bind 127.0.0.1:8000 \
    --timeout 120 \
    --access-logfile -
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### RQ Worker Service

```ini title="/etc/systemd/system/pipelit-worker.service"
[Unit]
Description=Pipelit RQ Worker
After=network.target redis.service
Requires=redis.service

[Service]
Type=simple
User=pipelit
Group=pipelit
WorkingDirectory=/opt/pipelit/platform
Environment="PATH=/opt/pipelit/.venv/bin:/usr/bin"
EnvironmentFile=/opt/pipelit/.env
ExecStart=/opt/pipelit/.venv/bin/rq worker workflows --with-scheduler
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Enable and Start

```bash
sudo systemctl daemon-reload
sudo systemctl enable pipelit pipelit-worker
sudo systemctl start pipelit pipelit-worker

# Check status
sudo systemctl status pipelit
sudo systemctl status pipelit-worker

# View logs
sudo journalctl -u pipelit -f
sudo journalctl -u pipelit-worker -f
```

## Environment File

Create `/opt/pipelit/.env` with production values:

```env
FIELD_ENCRYPTION_KEY=your-generated-fernet-key
SECRET_KEY=a-long-random-string-here
DEBUG=false
ALLOWED_HOSTS=your-domain.com
CORS_ALLOW_ALL_ORIGINS=false
REDIS_URL=redis://localhost:6379/0
DATABASE_URL=sqlite:////opt/pipelit/platform/db.sqlite3
```

See [Environment Variables](environment.md) for the full reference.

## Security Checklist

Before exposing Pipelit to the internet, verify each item:

- [ ] **`SECRET_KEY`** is set to a long, random value (not `change-me-in-production`)
- [ ] **`DEBUG`** is set to `false`
- [ ] **`CORS_ALLOW_ALL_ORIGINS`** is set to `false`
- [ ] **`ALLOWED_HOSTS`** is set to your actual domain name(s)
- [ ] **`FIELD_ENCRYPTION_KEY`** is generated and stored securely (never committed to version control)
- [ ] **HTTPS** is configured via a reverse proxy with valid SSL certificates
- [ ] **Firewall** blocks direct access to ports 8000 (backend) and 6379 (Redis) from the public internet
- [ ] **Redis** is bound to `127.0.0.1` or uses authentication (Redis does not require a password by default)
- [ ] **Database file** (if using SQLite) has restrictive file permissions (`chmod 600`)
- [ ] **System user** runs Pipelit with minimal privileges (do not run as root)
- [ ] **MFA** is enabled for admin accounts via the Settings page

!!! danger "Never expose Redis to the internet"
    Redis has no authentication by default. Always bind Redis to `127.0.0.1` or use a firewall to restrict access. An exposed Redis instance can be trivially exploited.

## Reverse Proxy

A reverse proxy is strongly recommended for production to handle HTTPS termination and WebSocket upgrades. See the [Reverse Proxy](reverse-proxy.md) guide for Nginx and Caddy configurations.

## Updating in Production

```bash
cd /opt/pipelit
git pull

# Rebuild frontend
cd platform/frontend && npm install && npm run build && cd ../..

# Restart services (migrations run automatically on startup)
sudo systemctl restart pipelit pipelit-worker
```

Alembic migrations are applied automatically when the FastAPI application starts. The `lifespan` handler in `main.py` calls `Base.metadata.create_all()` on startup for development convenience. In production, you can also run migrations explicitly:

```bash
cd /opt/pipelit/platform
source ../.venv/bin/activate
alembic upgrade head
```

## Monitoring

Monitor the following for a healthy deployment:

- **systemd service status** -- both `pipelit` and `pipelit-worker` should be `active (running)`
- **Redis connectivity** -- `redis-cli ping` should return `PONG`
- **Worker queue depth** -- `rq info` shows pending/active/failed job counts
- **Application logs** -- watch for unhandled exceptions via `journalctl`
- **Disk space** -- SQLite databases and Redis persistence files grow over time

# Docker Deployment

Docker is the recommended way to deploy Pipelit. This guide covers the Dockerfile structure, docker-compose configuration, and persistent storage setup.

## Prerequisites

- Docker 24+ and Docker Compose v2
- At least 2 GB of RAM available for containers

## Dockerfile Structure

Pipelit uses a **multi-stage build** to keep the final image small:

```dockerfile
# Stage 1: Build the frontend
FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend
COPY platform/frontend/package*.json ./
RUN npm ci
COPY platform/frontend/ ./
RUN npm run build

# Stage 2: Python backend
FROM python:3.12-slim AS backend
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY platform/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source
COPY platform/ ./

# Copy built frontend from stage 1
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Stage 1** installs Node.js dependencies and runs `npm run build` to produce the optimized static SPA in `frontend/dist/`. **Stage 2** installs Python dependencies, copies the backend source, and copies the built frontend assets. FastAPI serves the frontend from the `frontend/dist/` directory via its static file mount.

## Docker Compose

Create a `docker-compose.yml` in the project root:

```yaml
version: "3.9"

services:
  redis:
    image: redis:8
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5

  backend:
    build: .
    ports:
      - "8000:8000"
    env_file: .env
    environment:
      - REDIS_URL=redis://redis:6379/0
      - DATABASE_URL=sqlite:////app/data/db.sqlite3
    volumes:
      - app-data:/app/data
    depends_on:
      redis:
        condition: service_healthy
    command: >
      uvicorn main:app
      --host 0.0.0.0
      --port 8000
      --workers 2

  worker:
    build: .
    env_file: .env
    environment:
      - REDIS_URL=redis://redis:6379/0
      - DATABASE_URL=sqlite:////app/data/db.sqlite3
    volumes:
      - app-data:/app/data
    depends_on:
      redis:
        condition: service_healthy
    command: rq worker workflows --with-scheduler

volumes:
  redis-data:
  app-data:
```

## Environment Variables

Create a `.env` file in the project root before starting:

```env
FIELD_ENCRYPTION_KEY=your-generated-fernet-key
SECRET_KEY=change-me-to-a-random-string
DEBUG=false
CORS_ALLOW_ALL_ORIGINS=false
ALLOWED_HOSTS=your-domain.com
```

Generate a Fernet encryption key:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

See [Environment Variables](environment.md) for the full reference.

## Volume Mounts

Two volumes ensure data persists across container restarts:

| Volume | Mount Path | Contents |
|--------|-----------|----------|
| `app-data` | `/app/data/` | SQLite database, checkpoints database |
| `redis-data` | `/data/` | Redis persistence (RDB/AOF) |

!!! warning "SQLite concurrency"
    SQLite allows only one writer at a time. When using SQLite with Docker, the backend and worker containers share the same volume-mounted database file. This works for small deployments but can cause `database is locked` errors under heavy load. For production deployments, use [PostgreSQL](database.md) instead.

## Starting the Stack

```bash
# Build and start all services
docker compose up -d --build

# Check status
docker compose ps

# View logs
docker compose logs -f backend
docker compose logs -f worker

# Stop everything
docker compose down
```

After starting, open `http://localhost:8000` in your browser. The setup wizard will prompt you to create your admin account on first visit.

## Scaling Workers

You can run multiple RQ workers for higher throughput:

```yaml
  worker:
    build: .
    env_file: .env
    environment:
      - REDIS_URL=redis://redis:6379/0
      - DATABASE_URL=sqlite:////app/data/db.sqlite3
    volumes:
      - app-data:/app/data
    depends_on:
      redis:
        condition: service_healthy
    deploy:
      replicas: 3
    command: rq worker workflows --with-scheduler
```

!!! note
    When using SQLite, scaling workers beyond 1--2 may cause database lock contention. Switch to PostgreSQL for multi-worker deployments.

## Updating

To update to a newer version:

```bash
git pull
docker compose up -d --build
```

Alembic migrations run automatically on startup, so database schema changes are applied when the new backend container starts.

## Health Checks

The backend exposes the setup status endpoint at `/api/v1/auth/setup-status/` which can be used for container health checks:

```yaml
  backend:
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/v1/auth/setup-status/"]
      interval: 30s
      timeout: 5s
      retries: 3
```

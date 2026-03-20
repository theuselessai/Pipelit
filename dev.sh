#!/usr/bin/env bash
# dev.sh — AI-agent-optimized dev harness for Pipelit
# All status output goes to stdout as JSON. Human-readable logs go to stderr.
# Usage: ./dev.sh <up|down|restart|status|logs|exec|test> [args...]

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CONTAINER_NAME="plit-dev"
VOLUME_NAME="plit-dev-data"
PLIT_IMAGE="${PLIT_IMAGE:-plit-e2e:import-test}"
ADMIN_USERNAME="admin"
ADMIN_PASSWORD="testpass123"

# Paths inside the container
PLATFORM_INNER="/root/.local/share/plit/pipelit/platform"
VENV_BIN="/root/.local/share/plit/venv/bin"
PROCFILE_PATH="/root/.config/plit/Procfile"
DB_PATH="/root/.local/share/plit/pipelit.db"

# Host-side paths
PLATFORM_HOST="$(cd "$(dirname "$0")/platform" && pwd)"

# API health check
API_PORT="8000"
API_BASE="http://localhost:${API_PORT}"
HEALTH_URL="${API_BASE}/api/v1/auth/setup-status/"
HEALTH_TIMEOUT=120  # seconds

# Procfile content with --reload enabled for the pipelit process
# All other processes remain unchanged from the stock Procfile.
DEV_PROCFILE=$(cat <<'PROCFILE'
redis: /root/.config/plit/dragonfly --logtostderr --port 6399
gateway: GATEWAY_CONFIG=/root/.config/plit/config.json /usr/local/bin/plit-gw
pipelit: /root/.local/share/plit/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload --reload-dir /root/.local/share/plit/pipelit/platform
scheduler: /root/.local/share/plit/venv/bin/rq worker --worker-class worker_class.PipelitWorker workflows --with-scheduler
worker: /root/.local/share/plit/venv/bin/rq worker-pool workflows -w worker_class.PipelitWorker -n 4
PROCFILE
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

log() {
    # Human-readable log to stderr so stdout stays clean for JSON
    echo "[dev.sh] $*" >&2
}

json_error() {
    local msg="$1"
    printf '{"status":"error","message":"%s"}\n' "$msg"
}

container_running() {
    docker inspect --format '{{.State.Running}}' "$CONTAINER_NAME" 2>/dev/null | grep -q '^true$'
}

container_exists() {
    docker inspect "$CONTAINER_NAME" &>/dev/null
}

# ---------------------------------------------------------------------------
# Wait for the API to be healthy
# Returns 0 on success, 1 on timeout
# ---------------------------------------------------------------------------

wait_healthy() {
    log "Waiting for API at ${HEALTH_URL} (timeout: ${HEALTH_TIMEOUT}s)..."
    local elapsed=0
    local interval=3

    while [[ $elapsed -lt $HEALTH_TIMEOUT ]]; do
        local http_code
        http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$HEALTH_URL" 2>/dev/null || true)
        if [[ "$http_code" == "200" ]]; then
            log "API is healthy after ${elapsed}s."
            return 0
        fi
        log "  (${elapsed}s) HTTP ${http_code:-no response} — retrying in ${interval}s..."
        sleep "$interval"
        elapsed=$(( elapsed + interval ))
    done

    log "ERROR: API did not become healthy within ${HEALTH_TIMEOUT}s."
    return 1
}

# ---------------------------------------------------------------------------
# Query the admin API key from SQLite inside the container
# ---------------------------------------------------------------------------

get_admin_api_key() {
    docker exec "$CONTAINER_NAME" \
        python3 -c "import sqlite3; print(sqlite3.connect('${DB_PATH}').execute('SELECT key FROM api_keys LIMIT 1').fetchone()[0])" \
        2>/dev/null || true
}

# ---------------------------------------------------------------------------
# Ensure a dedicated agent API key exists (idempotent)
# Creates a key named "claude-agent" if one doesn't already exist.
# Returns the key value.
# ---------------------------------------------------------------------------

ensure_agent_key() {
    local admin_key="$1"

    # Check if agent key already exists
    local existing
    existing=$(docker exec "$CONTAINER_NAME" \
        python3 -c "
import sqlite3
conn = sqlite3.connect('${DB_PATH}')
row = conn.execute(\"SELECT key FROM api_keys WHERE name='claude-agent'\").fetchone()
print(row[0] if row else '')
" 2>/dev/null || true)

    if [[ -n "$existing" ]]; then
        echo "$existing"
        return
    fi

    # Create a new agent key via the API
    log "Creating agent API key 'claude-agent'..."
    local response
    response=$(curl -s -X POST "${API_BASE}/api/v1/users/me/keys" \
        -H "Authorization: Bearer ${admin_key}" \
        -H "Content-Type: application/json" \
        -d '{"name": "claude-agent"}' 2>/dev/null)

    local key
    key=$(echo "$response" | python3 -c "import json,sys; print(json.load(sys.stdin).get('key',''))" 2>/dev/null || true)

    if [[ -n "$key" ]]; then
        log "Agent API key created."
        echo "$key"
    else
        log "WARNING: Could not create agent API key. Response: ${response}"
        echo ""
    fi
}

# ---------------------------------------------------------------------------
# Emit the standard JSON status blob
# ---------------------------------------------------------------------------

emit_status_json() {
    local admin_key
    admin_key=$(get_admin_api_key)

    local agent_key
    agent_key=$(ensure_agent_key "$admin_key")

    printf '{
  "status": "ready",
  "container": "%s",
  "api_url": "%s",
  "frontend_url": "%s",
  "gateway_url": "http://localhost:8080",
  "admin": {
    "username": "%s",
    "password": "%s",
    "api_key": "%s"
  },
  "agent": {
    "api_key": "%s"
  }
}\n' \
        "$CONTAINER_NAME" \
        "$API_BASE" \
        "$API_BASE" \
        "$ADMIN_USERNAME" \
        "$ADMIN_PASSWORD" \
        "$admin_key" \
        "$agent_key"
}

# ---------------------------------------------------------------------------
# Install the dev Procfile into the running container
# ---------------------------------------------------------------------------

install_dev_procfile() {
    log "Installing dev Procfile (uvicorn --reload) into container..."
    printf '%s' "$DEV_PROCFILE" | docker exec -i "$CONTAINER_NAME" \
        bash -c "cat > ${PROCFILE_PATH}"
    log "Dev Procfile installed."
}

# ---------------------------------------------------------------------------
# Subcommand: up
# ---------------------------------------------------------------------------

cmd_up() {
    # Stop existing container if present
    if container_exists; then
        log "Stopping existing container '${CONTAINER_NAME}'..."
        docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
    fi

    # Ensure volume exists
    if ! docker volume inspect "$VOLUME_NAME" &>/dev/null; then
        log "Creating data volume '${VOLUME_NAME}'..."
        docker volume create "$VOLUME_NAME" >/dev/null
    fi

    # Resolve LLM_API_KEY from host environment
    local llm_api_key="${LLM_API_KEY:-}"
    if [[ -z "$llm_api_key" ]]; then
        log "ERROR: LLM_API_KEY env var is required. Export it or pass inline:"
        log "  LLM_API_KEY=sk-ant-... ./dev.sh up"
        json_error "LLM_API_KEY env var is required"
        exit 1
    fi

    log "Starting container '${CONTAINER_NAME}' from image '${PLIT_IMAGE}'..."
    docker run -d \
        --name "$CONTAINER_NAME" \
        --restart unless-stopped \
        -p "${API_PORT}:${API_PORT}" \
        -p 8080:8080 \
        -v "${VOLUME_NAME}:/root/.local/share/plit" \
        -v "${PLATFORM_HOST}:${PLATFORM_INNER}" \
        -e "ADMIN_USERNAME=${ADMIN_USERNAME}" \
        -e "ADMIN_PASSWORD=${ADMIN_PASSWORD}" \
        -e LLM_PROVIDER=anthropic \
        -e LLM_MODEL=claude-sonnet-4-20250514 \
        -e "LLM_API_KEY=${llm_api_key}" \
        "$PLIT_IMAGE" \
        >/dev/null

    log "Container started. Waiting for entrypoint init..."

    # Give the entrypoint a moment to start before we overwrite the Procfile.
    # We poll until the Procfile exists (entrypoint creates it via plit init).
    local wait_init=0
    while [[ $wait_init -lt 30 ]]; do
        if docker exec "$CONTAINER_NAME" test -f "$PROCFILE_PATH" 2>/dev/null; then
            break
        fi
        sleep 2
        wait_init=$(( wait_init + 2 ))
    done

    install_dev_procfile

    # The entrypoint runs `plit start --foreground` which reads the Procfile.
    # If the entrypoint already launched honcho before we wrote the file,
    # we need to restart the plit process so it picks up our Procfile.
    log "Restarting 'plit start' process inside container to pick up dev Procfile..."
    docker exec "$CONTAINER_NAME" bash -c \
        "pkill -f 'plit start' 2>/dev/null || true; sleep 1; nohup plit start --foreground </dev/null >>/tmp/plit.log 2>&1 &"

    # Wait for the API
    if ! wait_healthy; then
        json_error "API did not become healthy — check 'docker logs ${CONTAINER_NAME}'"
        exit 1
    fi

    emit_status_json
}

# ---------------------------------------------------------------------------
# Subcommand: down
# ---------------------------------------------------------------------------

cmd_down() {
    if container_exists; then
        log "Removing container '${CONTAINER_NAME}' (volumes preserved)..."
        docker rm -f "$CONTAINER_NAME" >/dev/null
        log "Container removed."
    else
        log "Container '${CONTAINER_NAME}' does not exist — nothing to do."
    fi
    printf '{"status":"stopped","container":"%s"}\n' "$CONTAINER_NAME"
}

# ---------------------------------------------------------------------------
# Subcommand: restart
# ---------------------------------------------------------------------------

cmd_restart() {
    if ! container_running; then
        json_error "Container '${CONTAINER_NAME}' is not running. Use 'up' first."
        exit 1
    fi

    log "Reinstalling dev Procfile..."
    install_dev_procfile

    log "Restarting honcho / plit start inside container..."
    docker exec "$CONTAINER_NAME" bash -c \
        "pkill -f 'plit start' 2>/dev/null || true; pkill -f honcho 2>/dev/null || true; sleep 2; nohup plit start --foreground </dev/null >>/tmp/plit.log 2>&1 &"

    if ! wait_healthy; then
        json_error "API did not become healthy after restart"
        exit 1
    fi

    emit_status_json
}

# ---------------------------------------------------------------------------
# Subcommand: status
# ---------------------------------------------------------------------------

cmd_status() {
    if ! container_running; then
        printf '{"status":"stopped","container":"%s"}\n' "$CONTAINER_NAME"
        return 0
    fi

    # Quick liveness check — don't wait, just try once
    local http_code
    http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$HEALTH_URL" 2>/dev/null || true)
    if [[ "$http_code" != "200" ]]; then
        printf '{"status":"starting","container":"%s","api_url":"%s"}\n' \
            "$CONTAINER_NAME" "$API_BASE"
        return 0
    fi

    emit_status_json
}

# ---------------------------------------------------------------------------
# Subcommand: logs
# ---------------------------------------------------------------------------

cmd_logs() {
    local service="${1:-}"

    if ! container_exists; then
        log "Container '${CONTAINER_NAME}' does not exist."
        exit 1
    fi

    if [[ -n "$service" ]]; then
        # Filter by service name, e.g. pipelit.1, worker.1
        docker logs -f "$CONTAINER_NAME" 2>&1 | grep --line-buffered "${service}"
    else
        docker logs -f "$CONTAINER_NAME" 2>&1
    fi
}

# ---------------------------------------------------------------------------
# Subcommand: exec
# ---------------------------------------------------------------------------

cmd_exec() {
    if [[ $# -eq 0 ]]; then
        json_error "exec requires a command argument"
        exit 1
    fi

    if ! container_running; then
        json_error "Container '${CONTAINER_NAME}' is not running"
        exit 1
    fi

    # Run in the platform working directory with the venv active.
    # Source both .env files so DATABASE_URL, FIELD_ENCRYPTION_KEY, etc. are set.
    docker exec \
        -w "$PLATFORM_INNER" \
        -e "PATH=${VENV_BIN}:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
        "$CONTAINER_NAME" \
        bash -c "set -a; source /root/.config/plit/.env 2>/dev/null; source /root/.local/share/plit/pipelit/.env 2>/dev/null; set +a; exec \"\$@\"" -- "$@"
}

# ---------------------------------------------------------------------------
# Subcommand: test
# ---------------------------------------------------------------------------

cmd_test() {
    if ! container_running; then
        json_error "Container '${CONTAINER_NAME}' is not running"
        exit 1
    fi

    log "Running pytest inside container..."
    docker exec \
        -w "$PLATFORM_INNER" \
        -e "PATH=${VENV_BIN}:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
        "$CONTAINER_NAME" \
        bash -c "set -a; source /root/.config/plit/.env 2>/dev/null; source /root/.local/share/plit/pipelit/.env 2>/dev/null; set +a; exec python -m pytest tests/ -v"
}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

if [[ $# -eq 0 ]]; then
    printf '{"status":"error","message":"Usage: dev.sh <up|down|restart|status|logs|exec|test> [args...]"}\n'
    exit 1
fi

SUBCOMMAND="$1"
shift

case "$SUBCOMMAND" in
    up)      cmd_up "$@" ;;
    down)    cmd_down "$@" ;;
    restart) cmd_restart "$@" ;;
    status)  cmd_status "$@" ;;
    logs)    cmd_logs "$@" ;;
    exec)    cmd_exec "$@" ;;
    test)    cmd_test "$@" ;;
    *)
        json_error "Unknown subcommand: ${SUBCOMMAND}"
        exit 1
        ;;
esac

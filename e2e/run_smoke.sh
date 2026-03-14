#!/usr/bin/env bash
# E2E smoke test for plit Docker container.
#
# Boots the container with a mock LLM server, then validates:
#   1. Container boot + fresh DB migration
#   2. Login
#   3. User management CRUD
#   4. API key lifecycle
#   5. Gateway health + credentials
#   6. Chat round-trip (send → gateway → Pipelit → RQ → mock LLM → WS response)
#
# Usage:
#   ./e2e/run_smoke.sh [IMAGE]
#   # IMAGE defaults to plit-e2e:local
#
# Environment:
#   ANTHROPIC_API_KEY  — if set, uses real Anthropic API instead of mock
#   LLM_MODEL          — model to use with real key (default: claude-sonnet-4-20250514)

set -euo pipefail

IMAGE="${1:-plit-e2e:local}"
CONTAINER_NAME="plit-e2e-smoke-$$"
MOCK_PORT=9999
MOCK_PID=""
PIPELIT_PORT=8000
GATEWAY_PORT=8080
ADMIN_USER="admin"
ADMIN_PASS="testpass123e2e"
PASS=0
FAIL=0
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── Helpers ──────────────────────────────────────────────────────────────────

cleanup() {
    echo ""
    echo "═══ Cleanup ═══"
    [ -n "$MOCK_PID" ] && kill "$MOCK_PID" 2>/dev/null && echo "  Stopped mock LLM server"
    docker rm -f "$CONTAINER_NAME" 2>/dev/null && echo "  Removed container $CONTAINER_NAME"
    echo ""
    echo "═══ Results: $PASS passed, $FAIL failed ═══"
    [ "$FAIL" -gt 0 ] && exit 1
    exit 0
}
trap cleanup EXIT

assert() {
    local name="$1" condition="$2"
    if eval "$condition"; then
        echo "  PASS  $name"
        PASS=$((PASS + 1))
    else
        echo "  FAIL  $name"
        FAIL=$((FAIL + 1))
    fi
}

wait_for_http() {
    local url="$1" max_attempts="${2:-30}" attempt=0
    while [ $attempt -lt "$max_attempts" ]; do
        if curl -sf "$url" > /dev/null 2>&1; then
            return 0
        fi
        sleep 2
        attempt=$((attempt + 1))
    done
    echo "  Timed out waiting for $url"
    return 1
}

api() {
    # api METHOD PATH [EXTRA_CURL_ARGS...]
    local method="$1" path="$2"
    shift 2
    curl -sf -X "$method" "http://localhost:${PIPELIT_PORT}/api/v1${path}" \
        -H "Content-Type: application/json" \
        "$@"
}

api_auth() {
    # api_auth METHOD PATH TOKEN [EXTRA_CURL_ARGS...]
    local method="$1" path="$2" token="$3"
    shift 3
    curl -sf -X "$method" "http://localhost:${PIPELIT_PORT}/api/v1${path}" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $token" \
        "$@"
}

# ── Start mock LLM (unless real key provided) ───────────────────────────────

echo "═══ E2E Smoke Test ═══"
echo "  Image: $IMAGE"

if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
    echo "  LLM:   Real Anthropic API"
    LLM_PROVIDER="anthropic"
    LLM_MODEL="${LLM_MODEL:-claude-sonnet-4-20250514}"
    LLM_API_KEY="$ANTHROPIC_API_KEY"
    LLM_BASE_URL=""
else
    echo "  LLM:   Mock server on port $MOCK_PORT"
    python3 "$SCRIPT_DIR/mock_llm_server.py" --port "$MOCK_PORT" &
    MOCK_PID=$!
    sleep 1
    if ! kill -0 "$MOCK_PID" 2>/dev/null; then
        echo "  FATAL: Mock LLM server failed to start"
        exit 1
    fi
    LLM_PROVIDER="anthropic"
    LLM_MODEL="mock-model"
    LLM_API_KEY="mock-key"
    # host.docker.internal works on Docker Desktop; on Linux CI use host network
    LLM_BASE_URL="http://host.docker.internal:${MOCK_PORT}"
fi

# ── Boot container ───────────────────────────────────────────────────────────

echo ""
echo "═══ 1. Container Boot ═══"

DOCKER_ARGS=(
    -d --name "$CONTAINER_NAME"
    -p "${PIPELIT_PORT}:8000" -p "${GATEWAY_PORT}:8080"
    -e "ADMIN_USERNAME=$ADMIN_USER"
    -e "ADMIN_PASSWORD=$ADMIN_PASS"
    -e "LLM_PROVIDER=$LLM_PROVIDER"
    -e "LLM_MODEL=$LLM_MODEL"
    -e "LLM_API_KEY=$LLM_API_KEY"
)
[ -n "$LLM_BASE_URL" ] && DOCKER_ARGS+=(-e "LLM_BASE_URL=$LLM_BASE_URL")
# On Linux (CI), add host.docker.internal mapping
if [ "$(uname)" = "Linux" ]; then
    DOCKER_ARGS+=(--add-host "host.docker.internal:host-gateway")
fi

docker run "${DOCKER_ARGS[@]}" "$IMAGE"

echo "  Waiting for Pipelit API..."
wait_for_http "http://localhost:${PIPELIT_PORT}/docs" 45
echo "  Waiting for Gateway..."
wait_for_http "http://localhost:${GATEWAY_PORT}/health" 45

assert "Container is running" "docker ps --format '{{.Names}}' | grep -q '$CONTAINER_NAME'"
assert "Pipelit API responds" "curl -sf http://localhost:${PIPELIT_PORT}/docs > /dev/null"
assert "Gateway health OK" "curl -sf http://localhost:${GATEWAY_PORT}/health > /dev/null"

# ── Login ────────────────────────────────────────────────────────────────────

echo ""
echo "═══ 2. Authentication ═══"

LOGIN_RESPONSE=$(api POST "/auth/token/" \
    -d "{\"username\":\"$ADMIN_USER\",\"password\":\"$ADMIN_PASS\"}")
TOKEN=$(echo "$LOGIN_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['key'])" 2>/dev/null || echo "")

assert "Login returns access_token" "[ -n '$TOKEN' ]"
assert "Token length >= 32" "[ ${#TOKEN} -ge 32 ]"

if [ -z "$TOKEN" ]; then
    echo "  FATAL: Cannot continue without auth token"
    echo "  Login response: $LOGIN_RESPONSE"
    exit 1
fi

# ── User Management ─────────────────────────────────────────────────────────

echo ""
echo "═══ 3. User Management ═══"

# Create user
CREATE_USER=$(api_auth POST "/users/" "$TOKEN" \
    -d '{"username":"e2e_testuser","password":"e2etestpass123","role":"normal"}')
USER_ID=$(echo "$CREATE_USER" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])" 2>/dev/null || echo "")
assert "Create user returns ID" "[ -n '$USER_ID' ]"

# List users
USER_LIST=$(api_auth GET "/users/" "$TOKEN")
USER_COUNT=$(echo "$USER_LIST" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
assert "List users returns >= 2" "[ '$USER_COUNT' -ge 2 ]"

# Get user
if [ -n "$USER_ID" ]; then
    GET_USER=$(api_auth GET "/users/$USER_ID" "$TOKEN")
    GET_USERNAME=$(echo "$GET_USER" | python3 -c "import sys,json; print(json.load(sys.stdin)['username'])" 2>/dev/null || echo "")
    assert "Get user returns correct username" "[ '$GET_USERNAME' = 'e2e_testuser' ]"
fi

# Update user
if [ -n "$USER_ID" ]; then
    UPDATE_USER=$(api_auth PATCH "/users/$USER_ID" "$TOKEN" \
        -d '{"first_name":"E2E","last_name":"TestUser"}')
    UPDATED_FIRST=$(echo "$UPDATE_USER" | python3 -c "import sys,json; print(json.load(sys.stdin)['first_name'])" 2>/dev/null || echo "")
    assert "Update user changes first_name" "[ '$UPDATED_FIRST' = 'E2E' ]"
fi

# ── API Key Lifecycle ────────────────────────────────────────────────────────

echo ""
echo "═══ 4. API Key Lifecycle ═══"

# Create API key
CREATE_KEY=$(api_auth POST "/users/me/keys" "$TOKEN" \
    -d '{"name":"e2e-test-key"}')
KEY_RAW=$(echo "$CREATE_KEY" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('raw_key','') or d.get('key',''))" 2>/dev/null || echo "")
KEY_ID=$(echo "$CREATE_KEY" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])" 2>/dev/null || echo "")
assert "Create API key returns key" "[ -n '$KEY_RAW' ] || [ -n '$KEY_ID' ]"

# List API keys
KEY_LIST=$(api_auth GET "/users/me/keys" "$TOKEN")
KEY_COUNT=$(echo "$KEY_LIST" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
assert "List API keys returns >= 1" "[ '$KEY_COUNT' -ge 1 ]"

# Revoke API key
if [ -n "$KEY_ID" ]; then
    REVOKE_STATUS=$(curl -sf -o /dev/null -w "%{http_code}" -X DELETE \
        "http://localhost:${PIPELIT_PORT}/api/v1/users/me/keys/$KEY_ID" \
        -H "Authorization: Bearer $TOKEN")
    assert "Revoke API key returns 200 or 204" "[ '$REVOKE_STATUS' = '200' ] || [ '$REVOKE_STATUS' = '204' ]"
fi

# ── Gateway Health & Credentials ─────────────────────────────────────────────

echo ""
echo "═══ 5. Gateway Health & Credentials ═══"

GW_HEALTH=$(curl -sf "http://localhost:${GATEWAY_PORT}/health")
GW_STATUS=$(echo "$GW_HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")
assert "Gateway health status OK" "[ '$GW_STATUS' = 'ok' ] || [ '$GW_STATUS' = 'healthy' ]"

# Check credentials are synced (need admin token from inside container)
GW_ADMIN_TOKEN=$(docker exec "$CONTAINER_NAME" python3 -c "
import json
cfg = json.load(open('/root/.config/plit/config.json'))
print(cfg['gateway']['admin_token'])
" 2>/dev/null || echo "")

if [ -n "$GW_ADMIN_TOKEN" ]; then
    GW_CREDS=$(curl -sf "http://localhost:${GATEWAY_PORT}/admin/credentials" \
        -H "Authorization: Bearer $GW_ADMIN_TOKEN")
    CRED_COUNT=$(echo "$GW_CREDS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('credentials',d) if isinstance(d,dict) else d))" 2>/dev/null || echo "0")
    assert "Gateway has credentials synced" "[ '$CRED_COUNT' -ge 1 ]"
fi

# ── Chat Round-Trip ──────────────────────────────────────────────────────────

echo ""
echo "═══ 6. Chat Round-Trip ═══"

# Get credential token from inside container
CRED_TOKEN=$(docker exec "$CONTAINER_NAME" python3 -c "
import json
cfg = json.load(open('/root/.config/plit/config.json'))
print(cfg['credentials']['default_agent']['token'])
" 2>/dev/null || echo "")

if [ -z "$CRED_TOKEN" ]; then
    echo "  SKIP: Could not get credential token"
else
    CHAT_ID="e2e-smoke-$$"

    # Start listener in background inside container, capture output
    docker exec -d "$CONTAINER_NAME" bash -c "
        timeout 60 plit local listen \
            --chat-id $CHAT_ID \
            --gateway-url http://localhost:8080 \
            --token $CRED_TOKEN \
            default_agent > /tmp/e2e_listen_output.txt 2>&1
    "
    sleep 3

    # Send message
    SEND_RESULT=$(docker exec "$CONTAINER_NAME" bash -c "
        plit local send \
            --chat-id $CHAT_ID \
            --gateway-url http://localhost:8080 \
            --token $CRED_TOKEN \
            --text 'E2E smoke test message' \
            default_agent 2>&1
    " || echo "SEND_FAILED")

    assert "Send message succeeds" "echo '$SEND_RESULT' | grep -qv 'SEND_FAILED'"

    # Wait for response
    echo "  Waiting for chat response (up to 45s)..."
    RESPONSE_RECEIVED=false
    for i in $(seq 1 15); do
        LISTEN_OUTPUT=$(docker exec "$CONTAINER_NAME" cat /tmp/e2e_listen_output.txt 2>/dev/null || echo "")
        if echo "$LISTEN_OUTPUT" | grep -q "E2E_MOCK_RESPONSE_OK\|message_id"; then
            RESPONSE_RECEIVED=true
            break
        fi
        sleep 3
    done

    assert "Chat response received via WS" "$RESPONSE_RECEIVED"

    if [ "$RESPONSE_RECEIVED" = true ] && [ -z "${ANTHROPIC_API_KEY:-}" ]; then
        assert "Response contains mock text" "echo '$LISTEN_OUTPUT' | grep -q 'E2E_MOCK_RESPONSE_OK'"
    fi
fi

echo ""
echo "═══ Done ═══"

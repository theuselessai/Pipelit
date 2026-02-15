# Troubleshooting

Common issues and their solutions.

## Redis Connection Errors

### `unknown command 'FT._LIST'`

**Cause:** Your Redis version doesn't include RediSearch.

**Solution:** Upgrade to Redis 8.0+ which includes RediSearch natively:

```bash
# Docker
docker run -d --name redis -p 6379:6379 redis:8

# Verify
redis-cli MODULE LIST  # Should include 'search' module
```

See the full [Redis setup guide](deployment/redis.md).

### `Connection refused` on Redis

**Cause:** Redis is not running or is on a different port.

**Solution:**

```bash
# Check if Redis is running
redis-cli ping

# Start Redis
sudo systemctl start redis
# or
docker start redis
```

Verify `REDIS_URL` in your `.env` matches the actual Redis address.

---

## Zombie Executions (Stuck in "Running")

### Symptom

Executions stay in "running" status indefinitely and never complete.

### Common Causes

1. **RQ worker crashed** — The worker processing the execution died mid-run
2. **LLM API timeout** — The LLM provider took too long to respond
3. **Infinite tool loop** — An agent keeps calling tools without converging
4. **Redis disconnection** — Worker lost connection to Redis during execution

### Diagnosis

```bash
# Check for stuck executions (running > 15 minutes)
curl -H "Authorization: Bearer YOUR_KEY" \
  "http://localhost:8000/api/v1/executions/?status=running"

# Check RQ worker status
rq info --url redis://localhost:6379/0

# Check worker logs for errors
```

### Solutions

1. **Cancel stuck executions** via API:
   ```bash
   curl -X POST -H "Authorization: Bearer YOUR_KEY" \
     "http://localhost:8000/api/v1/executions/{id}/cancel/"
   ```

2. **Restart the RQ worker:**
   ```bash
   # Kill existing worker
   pkill -f "rq worker"

   # Restart
   cd platform && rq worker workflows --with-scheduler
   ```

3. **Adjust the zombie threshold** in `.env`:
   ```env
   ZOMBIE_EXECUTION_THRESHOLD_SECONDS=1800  # 30 minutes
   ```

4. **Use the System Health tool** — Connect the `system_health` tool to an agent and ask it to diagnose infrastructure issues.

---

## Authentication Errors

### `401 Unauthorized`

**Cause:** Missing or invalid Bearer token.

**Solution:** Ensure your request includes the correct header:

```
Authorization: Bearer your-api-key-here
```

!!! warning "Common Mistakes"
    - Using `Token` instead of `Bearer`
    - Including extra whitespace
    - Using an expired or revoked API key

### Setup wizard doesn't appear

**Cause:** An admin user already exists.

**Solution:** Check setup status:

```bash
curl http://localhost:8000/api/v1/auth/setup-status/
```

If `{"needs_setup": false}`, an admin was already created. Log in with those credentials.

---

## Database Issues

### `OperationalError: database is locked`

**Cause:** Multiple processes writing to SQLite simultaneously.

**Solution:** This is a SQLite limitation with concurrent writes.

- For development: ensure only one RQ worker is running
- For production: switch to PostgreSQL:
  ```env
  DATABASE_URL=postgresql://user:pass@localhost:5432/pipelit
  ```

### Migration errors

**Cause:** Conflicting Alembic migration heads or corrupted migration state.

**Solution:**

```bash
cd platform

# Check for multiple heads
alembic heads

# If multiple heads exist, merge them
alembic merge heads -m "merge migration heads"

# Apply migrations
alembic upgrade head
```

---

## Frontend Issues

### Blank page after login

**Cause:** Frontend build is outdated or missing.

**Solution:**

```bash
cd platform/frontend
npm run build
```

Then access via `http://localhost:8000` (not the Vite dev server).

### WebSocket connection failed

**Cause:** WebSocket connection can't be established.

**Solutions:**

1. Check that the backend is running on the expected port
2. If behind a reverse proxy, ensure WebSocket upgrade headers are forwarded
3. Check browser console for specific error messages
4. Verify the API key is valid (WebSocket auth uses `?token=<key>`)

---

## Execution Issues

### Agent not using tools

**Cause:** Tools are not properly connected to the agent.

**Solution:**

1. Verify tool nodes are connected to the agent's **tools** handle (green diamond at the bottom)
2. Check that the edge label is `tool`
3. Validate the workflow: `POST /api/v1/workflows/{slug}/validate/`

### Node shows "failed" status

**Cause:** The node encountered an error during execution.

**Solution:**

1. Click the red "error" link on the failed node to see the error details
2. Check the execution logs: `GET /api/v1/executions/{id}/`
3. Common errors:
   - Missing LLM credential on AI model node
   - Invalid system prompt (Jinja2 syntax error)
   - Tool execution failure (network error, permission denied)

---

## Getting Help

If your issue isn't listed here:

1. Check the execution logs for detailed error messages
2. Use the `system_health` tool to diagnose infrastructure issues
3. [Open an issue](https://github.com/theuselessai/Pipelit/issues) on GitHub

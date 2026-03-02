# Health Check

Health check endpoint for monitoring and load balancer probes. No authentication required.

---

## GET /health

Returns the operational status of the Pipelit backend, including Redis and database connectivity.

**Authentication:** None required.

**Example request:**

```bash
curl http://localhost:8000/health
```

**Response (200) — all healthy:**

```json
{
  "status": "ok",
  "version": "0.2.0",
  "redis": true,
  "database": true
}
```

**Response (200) — degraded:**

```json
{
  "status": "degraded",
  "version": "0.2.0",
  "redis": false,
  "database": true
}
```

### Response Fields

| Field      | Type    | Description |
|------------|---------|-------------|
| `status`   | string  | `"ok"` if all checks pass, `"degraded"` if any check fails |
| `version`  | string  | Pipelit version from the `VERSION` file |
| `redis`    | boolean | `true` if Redis responded to `PING` |
| `database` | boolean | `true` if database responded to `SELECT 1` |

### Status Values

| Status     | Meaning |
|------------|---------|
| `ok`       | All infrastructure checks passed |
| `degraded` | One or more checks failed — the API may still serve requests but some features (e.g., background jobs, pub/sub) will be impaired |

---

## Usage

### Load Balancer Health Checks

Configure your load balancer to poll `/health` periodically:

```bash
# Check for healthy status
curl -sf http://localhost:8000/health | jq -e '.status == "ok"'
```

### Monitoring Integration

The endpoint works with any HTTP-based monitoring tool (Uptime Kuma, Prometheus blackbox exporter, etc.). Check for `status: "ok"` or inspect the individual `redis` and `database` fields for granular alerts.

### systemd Watchdog

Add a startup health check to your systemd unit:

```ini
ExecStartPost=/bin/sh -c 'sleep 3 && curl -sf http://localhost:8000/health'
```

!!! note "Not behind authentication"
    The health endpoint is intentionally unauthenticated so load balancers and monitoring tools can probe it without API keys. It does not expose any sensitive data.

# Schedules

Endpoints for managing scheduled jobs. Scheduled jobs execute workflows on a recurring interval using a self-rescheduling mechanism via RQ (Redis Queue).

All endpoints are under `/api/v1/schedules/` and require Bearer token authentication.

---

## Concepts

A `ScheduledJob` stores the interval, repeat count, retry configuration, and state machine status:

- **Status flow:** `active` -> `paused` / `done` / `dead`
- **Repeat:** Jobs run up to `total_repeats` times (0 = unlimited).
- **Retry:** On failure, exponential backoff up to 10x the interval. Max `max_retries` consecutive retries before marking as `dead`.
- **Recovery:** On server startup, any active jobs whose `next_run_at` is in the past are automatically re-enqueued.

---

## GET /api/v1/schedules/

List scheduled jobs with optional filtering.

**Query parameters:**

| Parameter     | Type   | Default | Description |
|---------------|--------|---------|-------------|
| `limit`       | int    | 50      | Max items per page |
| `offset`      | int    | 0       | Items to skip |
| `status`      | string | `null`  | Filter by status (`active`, `paused`, `done`, `dead`) |
| `workflow_id` | int    | `null`  | Filter by workflow ID |

**Example request:**

```bash
curl "http://localhost:8000/api/v1/schedules/?status=active&limit=10" \
  -H "Authorization: Bearer <api_key>"
```

**Response (200):**

```json
{
  "items": [
    {
      "id": "a1b2c3d4-e5f6-7890",
      "name": "schedule:trigger_schedule_abc",
      "description": "",
      "workflow_id": 1,
      "trigger_node_id": "trigger_schedule_abc",
      "user_profile_id": 1,
      "interval_seconds": 300,
      "total_repeats": 0,
      "max_retries": 3,
      "timeout_seconds": 600,
      "trigger_payload": null,
      "status": "active",
      "current_repeat": 5,
      "current_retry": 0,
      "last_run_at": "2025-01-15T10:30:00",
      "next_run_at": "2025-01-15T10:35:00",
      "run_count": 5,
      "error_count": 0,
      "last_error": "",
      "created_at": "2025-01-15T09:00:00",
      "updated_at": "2025-01-15T10:30:00"
    }
  ],
  "total": 1
}
```

---

## POST /api/v1/schedules/

Create and immediately start a new scheduled job.

**Request body:**

| Field              | Type        | Required | Default | Description |
|--------------------|-------------|----------|---------|-------------|
| `name`             | string      | yes      |         | Job name |
| `description`      | string      | no       | `""`    | Description |
| `workflow_id`      | int         | yes      |         | Target workflow ID |
| `trigger_node_id`  | string      | no       | `null`  | Specific trigger node to fire |
| `interval_seconds` | int         | yes      |         | Seconds between runs (must be >= 1) |
| `total_repeats`    | int         | no       | `0`     | Total runs (0 = unlimited, must be >= 0) |
| `max_retries`      | int         | no       | `3`     | Max consecutive retries (must be >= 0) |
| `timeout_seconds`  | int         | no       | `600`   | Timeout per run in seconds (must be >= 1) |
| `trigger_payload`  | object      | no       | `null`  | Payload passed to the trigger |

**Example request:**

```bash
curl -X POST http://localhost:8000/api/v1/schedules/ \
  -H "Authorization: Bearer <api_key>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Hourly health check",
    "workflow_id": 1,
    "trigger_node_id": "trigger_schedule_abc",
    "interval_seconds": 3600,
    "total_repeats": 0,
    "max_retries": 3
  }'
```

**Response (201):** Scheduled job object.

**Error (404):** `"Workflow not found."`

**Error (500):** `"Failed to start scheduled job."`

---

## GET /api/v1/schedules/{job_id}/

Get a scheduled job by ID.

**Path parameters:**

| Parameter | Type   | Description |
|-----------|--------|-------------|
| `job_id`  | string | Scheduled job UUID |

**Example request:**

```bash
curl http://localhost:8000/api/v1/schedules/a1b2c3d4-e5f6-7890/ \
  -H "Authorization: Bearer <api_key>"
```

**Response (200):** Scheduled job object.

**Error (404):** `"Scheduled job not found."`

---

## PATCH /api/v1/schedules/{job_id}/

Update a scheduled job's configuration. Only include fields you want to change.

**Path parameters:**

| Parameter | Type   | Description |
|-----------|--------|-------------|
| `job_id`  | string | Scheduled job UUID |

**Request body (all fields optional):**

| Field              | Type   | Description |
|--------------------|--------|-------------|
| `name`             | string | Job name |
| `description`      | string | Description |
| `interval_seconds` | int    | Seconds between runs (>= 1) |
| `total_repeats`    | int    | Total runs (>= 0) |
| `max_retries`      | int    | Max retries (>= 0) |
| `timeout_seconds`  | int    | Timeout per run (>= 1) |
| `trigger_payload`  | object | Trigger payload |

**Example request:**

```bash
curl -X PATCH http://localhost:8000/api/v1/schedules/a1b2c3d4-e5f6-7890/ \
  -H "Authorization: Bearer <api_key>" \
  -H "Content-Type: application/json" \
  -d '{"interval_seconds": 1800}'
```

**Response (200):** Updated scheduled job object.

**Error (404):** `"Scheduled job not found."`

---

## DELETE /api/v1/schedules/{job_id}/

Delete a scheduled job.

**Path parameters:**

| Parameter | Type   | Description |
|-----------|--------|-------------|
| `job_id`  | string | Scheduled job UUID |

**Example request:**

```bash
curl -X DELETE http://localhost:8000/api/v1/schedules/a1b2c3d4-e5f6-7890/ \
  -H "Authorization: Bearer <api_key>"
```

**Response (204):** No content.

**Error (404):** `"Scheduled job not found."`

---

## POST /api/v1/schedules/{job_id}/pause/

Pause an active scheduled job. Only jobs with status `active` can be paused.

**Path parameters:**

| Parameter | Type   | Description |
|-----------|--------|-------------|
| `job_id`  | string | Scheduled job UUID |

**Example request:**

```bash
curl -X POST http://localhost:8000/api/v1/schedules/a1b2c3d4-e5f6-7890/pause/ \
  -H "Authorization: Bearer <api_key>"
```

**Response (200):** Updated scheduled job object (status = `"paused"`).

**Error (400):** `"Cannot pause job with status 'paused'."`

**Error (404):** `"Scheduled job not found."`

---

## POST /api/v1/schedules/{job_id}/resume/

Resume a paused scheduled job. Only jobs with status `paused` can be resumed.

**Path parameters:**

| Parameter | Type   | Description |
|-----------|--------|-------------|
| `job_id`  | string | Scheduled job UUID |

**Example request:**

```bash
curl -X POST http://localhost:8000/api/v1/schedules/a1b2c3d4-e5f6-7890/resume/ \
  -H "Authorization: Bearer <api_key>"
```

**Response (200):** Updated scheduled job object (status = `"active"`).

**Error (400):** `"Cannot resume job with status 'active'."`

**Error (404):** `"Scheduled job not found."`

---

## POST /api/v1/schedules/batch-delete/

Batch delete multiple scheduled jobs.

**Request body:**

| Field          | Type     | Required | Description |
|----------------|----------|----------|-------------|
| `schedule_ids` | string[] | yes      | List of scheduled job UUIDs |

**Example request:**

```bash
curl -X POST http://localhost:8000/api/v1/schedules/batch-delete/ \
  -H "Authorization: Bearer <api_key>" \
  -H "Content-Type: application/json" \
  -d '{"schedule_ids": ["a1b2c3d4-e5f6-7890", "b2c3d4e5-f6a7-8901"]}'
```

**Response (204):** No content.

# Epics

Endpoints for managing epics -- high-level project containers that group related tasks. Epics track progress, budgets, and task completion.

All endpoints are under `/api/v1/epics/` and require Bearer token authentication.

---

## Epic Statuses

| Status      | Description |
|-------------|-------------|
| `planning`  | Initial state, epic is being defined |
| `active`    | Epic is in progress |
| `paused`    | Epic is temporarily paused |
| `completed` | All tasks completed successfully |
| `failed`    | Epic failed |
| `cancelled` | Epic was cancelled (cascades to pending/blocked/running tasks) |

---

## GET /api/v1/epics/

List epics with optional filtering.

**Query parameters:**

| Parameter | Type   | Default | Description |
|-----------|--------|---------|-------------|
| `limit`   | int    | 50      | Max items per page |
| `offset`  | int    | 0       | Items to skip |
| `status`  | string | `null`  | Filter by status |
| `tags`    | string | `null`  | Comma-separated tags to filter by |

**Example request:**

```bash
curl "http://localhost:8000/api/v1/epics/?status=active&tags=backend" \
  -H "Authorization: Bearer <api_key>"
```

**Response (200):**

```json
{
  "items": [
    {
      "id": "epic-uuid-1234",
      "title": "Implement user dashboard",
      "description": "Build the user-facing dashboard with analytics",
      "tags": ["frontend", "dashboard"],
      "created_by_node_id": null,
      "workflow_id": 1,
      "user_profile_id": 1,
      "status": "active",
      "priority": 2,
      "budget_tokens": 100000,
      "budget_usd": 5.0,
      "spent_tokens": 45000,
      "spent_usd": 2.25,
      "agent_overhead_tokens": 5000,
      "agent_overhead_usd": 0.25,
      "total_tasks": 8,
      "completed_tasks": 3,
      "failed_tasks": 0,
      "created_at": "2025-01-15T09:00:00",
      "updated_at": "2025-01-15T12:00:00",
      "completed_at": null,
      "result_summary": null
    }
  ],
  "total": 1
}
```

---

## POST /api/v1/epics/

Create a new epic.

**Request body:**

| Field           | Type        | Required | Default | Description |
|-----------------|-------------|----------|---------|-------------|
| `title`         | string      | yes      |         | Epic title |
| `description`   | string      | no       | `""`    | Description |
| `tags`          | string[]    | no       | `[]`    | Tags for categorization |
| `priority`      | int         | no       | `2`     | Priority level |
| `budget_tokens` | int or null | no       | `null`  | Token budget limit |
| `budget_usd`    | float or null | no     | `null`  | USD budget limit |
| `workflow_id`   | int or null | no       | `null`  | Associated workflow ID |

**Example request:**

```bash
curl -X POST http://localhost:8000/api/v1/epics/ \
  -H "Authorization: Bearer <api_key>" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Implement user dashboard",
    "description": "Build the user-facing dashboard with analytics",
    "tags": ["frontend", "dashboard"],
    "budget_tokens": 100000,
    "workflow_id": 1
  }'
```

**Response (201):** Epic object.

Broadcasts an `epic_created` WebSocket event on the `epic:<id>` channel.

---

## GET /api/v1/epics/{epic_id}/

Get an epic by ID.

**Path parameters:**

| Parameter | Type   | Description |
|-----------|--------|-------------|
| `epic_id` | string | Epic UUID |

**Response (200):** Epic object.

**Error (404):** `"Epic not found."`

---

## PATCH /api/v1/epics/{epic_id}/

Update an epic. Only include fields you want to change. Setting `status` to `"cancelled"` automatically cancels all pending, blocked, and running tasks.

**Path parameters:**

| Parameter | Type   | Description |
|-----------|--------|-------------|
| `epic_id` | string | Epic UUID |

**Request body (all fields optional):**

| Field            | Type          | Description |
|------------------|---------------|-------------|
| `title`          | string        | Epic title |
| `description`    | string        | Description |
| `tags`           | string[]      | Tags |
| `status`         | string        | New status (see [Epic Statuses](#epic-statuses)) |
| `priority`       | int           | Priority level |
| `budget_tokens`  | int or null   | Token budget |
| `budget_usd`     | float or null | USD budget |
| `result_summary` | string        | Summary of results |

**Response (200):** Updated epic object.

Broadcasts an `epic_updated` WebSocket event on the `epic:<id>` channel.

**Error (404):** `"Epic not found."`

---

## DELETE /api/v1/epics/{epic_id}/

Delete an epic and all its tasks.

**Path parameters:**

| Parameter | Type   | Description |
|-----------|--------|-------------|
| `epic_id` | string | Epic UUID |

**Response (204):** No content.

Broadcasts an `epic_deleted` WebSocket event on the `epic:<id>` channel.

**Error (404):** `"Epic not found."`

---

## POST /api/v1/epics/batch-delete/

Batch delete epics and their associated tasks.

**Request body:**

| Field      | Type     | Required | Description |
|------------|----------|----------|-------------|
| `epic_ids` | string[] | yes      | List of epic UUIDs to delete |

**Response (204):** No content.

---

## GET /api/v1/epics/{epic_id}/tasks/

List tasks belonging to a specific epic.

**Path parameters:**

| Parameter | Type   | Description |
|-----------|--------|-------------|
| `epic_id` | string | Epic UUID |

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit`   | int  | 50      | Max items per page |
| `offset`  | int  | 0       | Items to skip |

**Response (200):**

```json
{
  "items": [ ... ],
  "total": 8
}
```

See [Tasks](tasks.md) for the task object format.

**Error (404):** `"Epic not found."`

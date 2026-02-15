# Tasks

Endpoints for managing tasks within epics. Tasks represent individual units of work, support dependency chains, and track execution metrics.

All endpoints are under `/api/v1/tasks/` and require Bearer token authentication.

---

## Task Statuses

| Status      | Description |
|-------------|-------------|
| `pending`   | Ready to be worked on |
| `blocked`   | Waiting for dependencies to complete |
| `running`   | Currently being executed |
| `completed` | Successfully finished |
| `failed`    | Execution failed |
| `cancelled` | Task was cancelled |

Tasks with `depends_on` entries are automatically set to `blocked` on creation if their dependencies are not yet completed. When a dependency completes, blocked tasks are automatically unblocked.

---

## GET /api/v1/tasks/

List tasks with optional filtering.

**Query parameters:**

| Parameter | Type   | Default | Description |
|-----------|--------|---------|-------------|
| `limit`   | int    | 50      | Max items per page |
| `offset`  | int    | 0       | Items to skip |
| `epic_id` | string | `null`  | Filter by epic ID |
| `status`  | string | `null`  | Filter by status |
| `tags`    | string | `null`  | Comma-separated tags to filter by |

**Example request:**

```bash
curl "http://localhost:8000/api/v1/tasks/?epic_id=epic-uuid-1234&status=pending" \
  -H "Authorization: Bearer <api_key>"
```

**Response (200):**

```json
{
  "items": [
    {
      "id": "task-uuid-1234",
      "epic_id": "epic-uuid-1234",
      "title": "Create database schema",
      "description": "Design and implement the user table schema",
      "tags": ["backend", "database"],
      "created_by_node_id": null,
      "status": "completed",
      "priority": 1,
      "workflow_id": null,
      "workflow_slug": "schema-generator",
      "execution_id": "exec-uuid-5678",
      "workflow_source": "inline",
      "depends_on": [],
      "requirements": null,
      "estimated_tokens": 5000,
      "actual_tokens": 4200,
      "actual_usd": 0.021,
      "llm_calls": 3,
      "tool_invocations": 1,
      "duration_ms": 15000,
      "created_at": "2025-01-15T09:00:00",
      "updated_at": "2025-01-15T09:15:00",
      "started_at": "2025-01-15T09:00:05",
      "completed_at": "2025-01-15T09:15:00",
      "result_summary": "Created users table with 8 columns",
      "error_message": null,
      "retry_count": 0,
      "max_retries": 2,
      "notes": []
    }
  ],
  "total": 1
}
```

---

## POST /api/v1/tasks/

Create a new task within an epic.

**Request body:**

| Field              | Type        | Required | Default | Description |
|--------------------|-------------|----------|---------|-------------|
| `epic_id`          | string      | yes      |         | Parent epic ID |
| `title`            | string      | yes      |         | Task title |
| `description`      | string      | no       | `""`    | Description |
| `tags`             | string[]    | no       | `[]`    | Tags |
| `depends_on`       | string[]    | no       | `[]`    | List of task IDs this task depends on |
| `priority`         | int or null | no       | `2`     | Priority level |
| `workflow_slug`    | string      | no       | `null`  | Workflow to execute for this task |
| `estimated_tokens` | int or null | no       | `null`  | Estimated token usage |
| `max_retries`      | int         | no       | `2`     | Max retries on failure |
| `requirements`     | object      | no       | `null`  | Task requirements specification |

**Example request:**

```bash
curl -X POST http://localhost:8000/api/v1/tasks/ \
  -H "Authorization: Bearer <api_key>" \
  -H "Content-Type: application/json" \
  -d '{
    "epic_id": "epic-uuid-1234",
    "title": "Implement API endpoint",
    "description": "Create the REST endpoint for user creation",
    "depends_on": ["task-uuid-1234"],
    "workflow_slug": "code-generator",
    "estimated_tokens": 8000
  }'
```

**Response (201):** Task object. If `depends_on` contains uncompleted tasks, the initial status will be `"blocked"` instead of `"pending"`.

Broadcasts a `task_created` WebSocket event on the `epic:<epic_id>` channel.

**Error (404):** `"Epic not found."`

---

## GET /api/v1/tasks/{task_id}/

Get a task by ID.

**Path parameters:**

| Parameter | Type   | Description |
|-----------|--------|-------------|
| `task_id` | string | Task UUID |

**Response (200):** Task object.

**Error (404):** `"Task not found."`

---

## PATCH /api/v1/tasks/{task_id}/

Update a task. When a task is marked as `completed`, any dependent tasks that were `blocked` are automatically unblocked.

**Path parameters:**

| Parameter | Type   | Description |
|-----------|--------|-------------|
| `task_id` | string | Task UUID |

**Request body (all fields optional):**

| Field            | Type      | Description |
|------------------|-----------|-------------|
| `title`          | string    | Task title |
| `description`    | string    | Description |
| `tags`           | string[]  | Tags |
| `status`         | string    | New status (see [Task Statuses](#task-statuses)) |
| `priority`       | int       | Priority level |
| `workflow_slug`  | string    | Workflow slug |
| `execution_id`   | string    | Associated execution ID |
| `result_summary` | string    | Summary of results |
| `error_message`  | string    | Error message (on failure) |
| `notes`          | array     | Task notes |

**Example request:**

```bash
curl -X PATCH http://localhost:8000/api/v1/tasks/task-uuid-5678/ \
  -H "Authorization: Bearer <api_key>" \
  -H "Content-Type: application/json" \
  -d '{"status": "completed", "result_summary": "Endpoint created successfully"}'
```

**Response (200):** Updated task object.

Broadcasts a `task_updated` WebSocket event on the `epic:<epic_id>` channel.

**Error (404):** `"Task not found."`

---

## DELETE /api/v1/tasks/{task_id}/

Delete a task. Removes the task from any `depends_on` lists in sibling tasks and syncs the parent epic's progress counters.

**Path parameters:**

| Parameter | Type   | Description |
|-----------|--------|-------------|
| `task_id` | string | Task UUID |

**Response (204):** No content.

Broadcasts a `task_deleted` WebSocket event on the `epic:<epic_id>` channel.

**Error (404):** `"Task not found."`

---

## POST /api/v1/tasks/batch-delete/

Batch delete multiple tasks. Cleans up dependency references and syncs progress counters for all affected epics.

**Request body:**

| Field      | Type     | Required | Description |
|------------|----------|----------|-------------|
| `task_ids` | string[] | yes      | List of task UUIDs to delete |

**Example request:**

```bash
curl -X POST http://localhost:8000/api/v1/tasks/batch-delete/ \
  -H "Authorization: Bearer <api_key>" \
  -H "Content-Type: application/json" \
  -d '{"task_ids": ["task-uuid-1234", "task-uuid-5678"]}'
```

**Response (204):** No content.

Broadcasts `tasks_deleted` WebSocket events on the `epic:<epic_id>` channel for each affected epic.

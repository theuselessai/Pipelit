# Executions

Endpoints for listing, inspecting, cancelling, and batch-deleting workflow executions.

All endpoints are under `/api/v1/executions/` and require Bearer token authentication.

---

## GET /api/v1/executions/

List executions for the authenticated user, with optional filtering.

**Query parameters:**

| Parameter       | Type   | Default | Description |
|-----------------|--------|---------|-------------|
| `workflow_slug` | string | `null`  | Filter by workflow slug |
| `status`        | string | `null`  | Filter by status (`pending`, `running`, `completed`, `failed`, `cancelled`) |
| `limit`         | int    | 50      | Max items per page |
| `offset`        | int    | 0       | Items to skip |

**Example request:**

```bash
curl "http://localhost:8000/api/v1/executions/?workflow_slug=my-chatbot&status=completed&limit=10" \
  -H "Authorization: Bearer <api_key>"
```

**Response (200):**

```json
{
  "items": [
    {
      "execution_id": "abc12345-def6-7890-abcd-ef1234567890",
      "workflow_slug": "my-chatbot",
      "status": "completed",
      "error_message": "",
      "started_at": "2025-01-15T10:30:00",
      "completed_at": "2025-01-15T10:30:05",
      "total_tokens": 1500,
      "total_cost_usd": 0.0045,
      "llm_calls": 2
    }
  ],
  "total": 1
}
```

---

## GET /api/v1/executions/{execution_id}/

Get detailed execution information including logs.

**Path parameters:**

| Parameter      | Type   | Description |
|----------------|--------|-------------|
| `execution_id` | string | Execution UUID |

**Example request:**

```bash
curl http://localhost:8000/api/v1/executions/abc12345-def6-7890-abcd-ef1234567890/ \
  -H "Authorization: Bearer <api_key>"
```

**Response (200):**

```json
{
  "execution_id": "abc12345-def6-7890-abcd-ef1234567890",
  "workflow_slug": "my-chatbot",
  "status": "completed",
  "error_message": "",
  "started_at": "2025-01-15T10:30:00",
  "completed_at": "2025-01-15T10:30:05",
  "total_tokens": 1500,
  "total_cost_usd": 0.0045,
  "llm_calls": 2,
  "final_output": {"output": "Hello! How can I help you?"},
  "trigger_payload": {"text": "Hi there"},
  "logs": [
    {
      "id": 1,
      "node_id": "trigger_chat_a1b2c3",
      "status": "success",
      "input": null,
      "output": {"text": "Hi there"},
      "error": "",
      "error_code": null,
      "metadata": null,
      "duration_ms": 5,
      "timestamp": "2025-01-15T10:30:00"
    },
    {
      "id": 2,
      "node_id": "agent_abc123",
      "status": "success",
      "input": {"text": "Hi there"},
      "output": {"output": "Hello! How can I help you?"},
      "error": "",
      "error_code": null,
      "metadata": {"model": "claude-3-5-sonnet", "tokens": 1500},
      "duration_ms": 4200,
      "timestamp": "2025-01-15T10:30:01"
    }
  ]
}
```

**Error (404):** `"Execution not found."`

---

## Execution Log Fields

Each log entry represents one node's execution result:

| Field        | Type            | Description |
|--------------|-----------------|-------------|
| `id`         | int             | Log entry ID |
| `node_id`    | string          | Node that produced this log |
| `status`     | string          | `success`, `failed`, or `skipped` |
| `input`      | any or null     | Input data received by the node |
| `output`     | any or null     | Output data produced by the node |
| `error`      | string          | Error message (empty on success) |
| `error_code` | string or null  | Machine-readable error code |
| `metadata`   | object or null  | Execution metadata (model, tokens, etc.) |
| `duration_ms`| int             | Execution time in milliseconds |
| `timestamp`  | datetime        | When this log was recorded |

---

## POST /api/v1/executions/{execution_id}/cancel/

Cancel a running, pending, or interrupted execution.

**Path parameters:**

| Parameter      | Type   | Description |
|----------------|--------|-------------|
| `execution_id` | string | Execution UUID |

**Example request:**

```bash
curl -X POST http://localhost:8000/api/v1/executions/abc12345-def6-7890-abcd-ef1234567890/cancel/ \
  -H "Authorization: Bearer <api_key>"
```

**Response (200):** The execution object with updated status.

```json
{
  "execution_id": "abc12345-def6-7890-abcd-ef1234567890",
  "workflow_slug": "my-chatbot",
  "status": "cancelled",
  "error_message": "",
  "started_at": "2025-01-15T10:30:00",
  "completed_at": "2025-01-15T10:30:03",
  "total_tokens": 0,
  "total_cost_usd": 0.0,
  "llm_calls": 0
}
```

Broadcasts an `execution_cancelled` WebSocket event on the `workflow:<slug>` channel.

**Error (404):** `"Execution not found."`

!!! note
    Cancellation only applies to executions with status `pending`, `running`, or `interrupted`. Already completed or failed executions are returned unchanged.

---

## POST /api/v1/executions/batch-delete/

Permanently delete multiple executions and their associated logs.

**Request body:**

| Field           | Type     | Required | Description |
|-----------------|----------|----------|-------------|
| `execution_ids` | string[] | yes      | List of execution UUIDs to delete |

**Example request:**

```bash
curl -X POST http://localhost:8000/api/v1/executions/batch-delete/ \
  -H "Authorization: Bearer <api_key>" \
  -H "Content-Type: application/json" \
  -d '{"execution_ids": ["abc12345-def6-7890-abcd-ef1234567890"]}'
```

**Response (204):** No content.

!!! warning
    This permanently deletes executions and their logs. This action cannot be undone.

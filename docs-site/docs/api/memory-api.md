# Memory

Endpoints for managing agent memory stores: facts, episodes, procedures, memory users, and checkpoints. Each resource type supports listing (with pagination and filtering) and batch deletion.

All endpoints are under `/api/v1/memories/` and require Bearer token authentication.

---

## Facts

Facts are key-value knowledge entries stored by agents. They have a scope, type, and confidence level.

### GET /api/v1/memories/facts/

List memory facts with optional filtering.

**Query parameters:**

| Parameter   | Type   | Default | Description |
|-------------|--------|---------|-------------|
| `scope`     | string | `null`  | Filter by scope |
| `fact_type` | string | `null`  | Filter by fact type |
| `limit`     | int    | 50      | Max items per page |
| `offset`    | int    | 0       | Items to skip |

**Example request:**

```bash
curl "http://localhost:8000/api/v1/memories/facts/?scope=global&limit=20" \
  -H "Authorization: Bearer <api_key>"
```

**Response (200):**

```json
{
  "items": [
    {
      "id": "fact-uuid-1234",
      "scope": "global",
      "agent_id": "agent_abc123",
      "user_id": null,
      "key": "company_name",
      "value": "Acme Corp",
      "fact_type": "preference",
      "confidence": 0.95,
      "times_confirmed": 3,
      "access_count": 12,
      "created_at": "2025-01-15T10:30:00",
      "updated_at": "2025-01-15T12:00:00"
    }
  ],
  "total": 1
}
```

### POST /api/v1/memories/facts/batch-delete/

Batch delete facts by ID.

**Request body:**

| Field | Type     | Required | Description |
|-------|----------|----------|-------------|
| `ids` | string[] | yes      | List of fact UUIDs to delete |

**Example request:**

```bash
curl -X POST http://localhost:8000/api/v1/memories/facts/batch-delete/ \
  -H "Authorization: Bearer <api_key>" \
  -H "Content-Type: application/json" \
  -d '{"ids": ["fact-uuid-1234", "fact-uuid-5678"]}'
```

**Response (204):** No content.

---

## Episodes

Episodes represent interaction sessions between agents and users.

### GET /api/v1/memories/episodes/

List memory episodes with optional filtering.

**Query parameters:**

| Parameter  | Type   | Default | Description |
|------------|--------|---------|-------------|
| `agent_id` | string | `null`  | Filter by agent ID |
| `limit`    | int    | 50      | Max items per page |
| `offset`   | int    | 0       | Items to skip |

**Example request:**

```bash
curl "http://localhost:8000/api/v1/memories/episodes/?agent_id=agent_abc123" \
  -H "Authorization: Bearer <api_key>"
```

**Response (200):**

```json
{
  "items": [
    {
      "id": "episode-uuid-1234",
      "agent_id": "agent_abc123",
      "user_id": "user-uuid-5678",
      "trigger_type": "chat",
      "success": true,
      "error_code": null,
      "summary": "Helped user with order tracking",
      "started_at": "2025-01-15T10:30:00",
      "ended_at": "2025-01-15T10:35:00",
      "duration_ms": 300000,
      "created_at": "2025-01-15T10:35:00"
    }
  ],
  "total": 1
}
```

### POST /api/v1/memories/episodes/batch-delete/

Batch delete episodes by ID.

**Request body:**

| Field | Type     | Required | Description |
|-------|----------|----------|-------------|
| `ids` | string[] | yes      | List of episode UUIDs |

**Response (204):** No content.

---

## Procedures

Procedures are learned behavioral patterns that agents can reuse.

### GET /api/v1/memories/procedures/

List memory procedures with optional filtering.

**Query parameters:**

| Parameter  | Type   | Default | Description |
|------------|--------|---------|-------------|
| `agent_id` | string | `null`  | Filter by agent ID |
| `limit`    | int    | 50      | Max items per page |
| `offset`   | int    | 0       | Items to skip |

**Example request:**

```bash
curl "http://localhost:8000/api/v1/memories/procedures/" \
  -H "Authorization: Bearer <api_key>"
```

**Response (200):**

```json
{
  "items": [
    {
      "id": "proc-uuid-1234",
      "agent_id": "agent_abc123",
      "name": "order_lookup",
      "description": "Look up order status by order number",
      "procedure_type": "tool_chain",
      "times_used": 15,
      "times_succeeded": 14,
      "times_failed": 1,
      "success_rate": 0.933,
      "is_active": true,
      "created_at": "2025-01-10T08:00:00"
    }
  ],
  "total": 1
}
```

### POST /api/v1/memories/procedures/batch-delete/

Batch delete procedures by ID.

**Request body:**

| Field | Type     | Required | Description |
|-------|----------|----------|-------------|
| `ids` | string[] | yes      | List of procedure UUIDs |

**Response (204):** No content.

---

## Memory Users

Memory users represent end-users that agents have interacted with and remembered.

### GET /api/v1/memories/users/

List memory users.

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit`   | int  | 50      | Max items per page |
| `offset`  | int  | 0       | Items to skip |

**Example request:**

```bash
curl "http://localhost:8000/api/v1/memories/users/" \
  -H "Authorization: Bearer <api_key>"
```

**Response (200):**

```json
{
  "items": [
    {
      "id": "user-uuid-1234",
      "canonical_id": "telegram:123456789",
      "display_name": "John Doe",
      "telegram_id": "123456789",
      "email": null,
      "total_conversations": 15,
      "last_seen_at": "2025-01-15T10:30:00",
      "created_at": "2025-01-01T08:00:00"
    }
  ],
  "total": 1
}
```

### POST /api/v1/memories/users/batch-delete/

Batch delete memory users by ID.

**Request body:**

| Field | Type     | Required | Description |
|-------|----------|----------|-------------|
| `ids` | string[] | yes      | List of memory user UUIDs |

**Response (204):** No content.

---

## Checkpoints

Checkpoints store LangGraph conversation state. They are used for agent conversation memory persistence.

### GET /api/v1/memories/checkpoints/

List checkpoints with optional filtering by thread ID.

**Query parameters:**

| Parameter   | Type   | Default | Description |
|-------------|--------|---------|-------------|
| `thread_id` | string | `null`  | Filter by thread ID |
| `limit`     | int    | 50      | Max items per page |
| `offset`    | int    | 0       | Items to skip |

**Example request:**

```bash
curl "http://localhost:8000/api/v1/memories/checkpoints/?thread_id=1:5" \
  -H "Authorization: Bearer <api_key>"
```

**Response (200):**

```json
{
  "items": [
    {
      "thread_id": "1:5",
      "checkpoint_ns": "",
      "checkpoint_id": "ckpt-uuid-1234",
      "parent_checkpoint_id": "ckpt-uuid-0000",
      "step": 3,
      "source": "loop",
      "blob_size": 4096
    }
  ],
  "total": 1
}
```

| Field                    | Type          | Description |
|--------------------------|---------------|-------------|
| `thread_id`              | string        | Conversation thread identifier |
| `checkpoint_ns`          | string        | Checkpoint namespace |
| `checkpoint_id`          | string        | Unique checkpoint identifier |
| `parent_checkpoint_id`   | string or null | Parent checkpoint ID |
| `step`                   | int or null   | Step number in the graph execution |
| `source`                 | string or null | Source of the checkpoint (`loop`, `input`, etc.) |
| `blob_size`              | int           | Size of the serialized checkpoint in bytes |

### POST /api/v1/memories/checkpoints/batch-delete/

Batch delete checkpoints by thread ID or checkpoint ID.

**Request body:**

| Field            | Type     | Required | Description |
|------------------|----------|----------|-------------|
| `thread_ids`     | string[] | no       | Delete all checkpoints for these thread IDs |
| `checkpoint_ids` | string[] | no       | Delete specific checkpoints by ID |

At least one of `thread_ids` or `checkpoint_ids` should be provided.

**Example request:**

```bash
curl -X POST http://localhost:8000/api/v1/memories/checkpoints/batch-delete/ \
  -H "Authorization: Bearer <api_key>" \
  -H "Content-Type: application/json" \
  -d '{"thread_ids": ["1:5", "1:6"]}'
```

**Response (204):** No content.

!!! warning
    Deleting checkpoints removes the agent's conversation memory for the associated threads. This cannot be undone.

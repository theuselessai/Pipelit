# Users

Endpoints for managing agent users. Agent users are programmatically created accounts (without passwords) used by workflows and agents to perform API operations.

All endpoints are under `/api/v1/users/` and require Bearer token authentication.

---

## GET /api/v1/users/agents/

List all agent users.

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit`   | int  | 50      | Max items per page |
| `offset`  | int  | 0       | Items to skip |

**Example request:**

```bash
curl "http://localhost:8000/api/v1/users/agents/" \
  -H "Authorization: Bearer <api_key>"
```

**Response (200):**

```json
{
  "items": [
    {
      "id": 5,
      "username": "agent-workflow-chatbot",
      "purpose": "Customer support chatbot agent",
      "api_key_preview": "...abcd1234",
      "created_at": "2025-01-15T10:30:00",
      "created_by": "admin"
    }
  ],
  "total": 1
}
```

| Field             | Type          | Description |
|-------------------|---------------|-------------|
| `id`              | int           | Agent user ID |
| `username`        | string        | Agent username |
| `purpose`         | string        | Purpose/description of the agent |
| `api_key_preview` | string        | Last 8 characters of the API key (masked) |
| `created_at`      | datetime      | When the agent user was created |
| `created_by`      | string or null | Username of the creator |

---

## DELETE /api/v1/users/agents/{user_id}/

Delete an agent user and revoke their API key.

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `user_id` | int  | Agent user ID |

**Example request:**

```bash
curl -X DELETE http://localhost:8000/api/v1/users/agents/5/ \
  -H "Authorization: Bearer <api_key>"
```

**Response (204):** No content.

**Error (404):** `"Agent user not found"`

---

## POST /api/v1/users/agents/batch-delete/

Batch delete agent users and revoke their API keys.

**Request body:**

| Field | Type  | Required | Description |
|-------|-------|----------|-------------|
| `ids` | int[] | yes      | List of agent user IDs to delete |

**Example request:**

```bash
curl -X POST http://localhost:8000/api/v1/users/agents/batch-delete/ \
  -H "Authorization: Bearer <api_key>" \
  -H "Content-Type: application/json" \
  -d '{"ids": [5, 6, 7]}'
```

**Response (204):** No content.

!!! warning
    Deleting an agent user revokes their API key immediately. Any workflows or processes using that agent's key will lose access.

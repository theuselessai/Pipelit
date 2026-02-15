# API Reference

The Pipelit platform exposes a RESTful API under the `/api/v1/` prefix. All endpoints accept and return JSON.

## Base URL

```
http://localhost:8000/api/v1/
```

## Authentication

All API endpoints (except `/auth/setup-status/` and `/auth/setup/`) require a Bearer token in the `Authorization` header.

```
Authorization: Bearer <api_key>
```

Obtain a token by calling [POST /api/v1/auth/token/](auth.md#post-apiv1authtoken) with your username and password. If multi-factor authentication (MFA) is enabled on the account, an additional step via [POST /api/v1/auth/mfa/login-verify/](auth.md#post-apiv1authmfalogin-verify) is required.

Requests without a valid token receive a `401 Unauthorized` response.

## Pagination

All list endpoints accept `limit` and `offset` query parameters and return a paginated envelope:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit`   | int  | 50      | Maximum number of items to return |
| `offset`  | int  | 0       | Number of items to skip |

**Response format:**

```json
{
  "items": [ ... ],
  "total": 123
}
```

- `items` -- array of resource objects for the current page.
- `total` -- total count of matching resources (before pagination).

## Request Format

- Content-Type: `application/json`
- Request bodies use JSON. Fields marked as optional can be omitted.
- PATCH endpoints accept partial updates -- only include the fields you want to change.

## Response Format

All successful responses return JSON. Single-resource endpoints return the resource object directly. List endpoints return the paginated envelope described above.

## Error Codes

| HTTP Status | Meaning |
|-------------|---------|
| `400`       | Bad request -- invalid input or business rule violation |
| `401`       | Unauthorized -- missing or invalid Bearer token |
| `403`       | Forbidden -- action not allowed (e.g., MFA reset from non-localhost) |
| `404`       | Not found -- resource does not exist |
| `409`       | Conflict -- resource already exists (e.g., setup already completed) |
| `422`       | Validation error -- schema validation failed or edge type mismatch |
| `500`       | Internal server error |

**Error response body:**

```json
{
  "detail": "Human-readable error message"
}
```

For validation errors (422), the `detail` field may contain a structured object:

```json
{
  "detail": {
    "validation_errors": [
      "Source type 'trigger_chat' output 'text' is not compatible with target input 'model'"
    ]
  }
}
```

## API Sections

| Section | Prefix | Description |
|---------|--------|-------------|
| [Authentication](auth.md) | `/api/v1/auth/` | Login, setup, MFA, user info |
| [Workflows](workflows.md) | `/api/v1/workflows/` | Workflow CRUD, validation, node types |
| [Nodes](nodes.md) | `/api/v1/workflows/{slug}/nodes/` | Node CRUD within a workflow |
| [Edges](edges.md) | `/api/v1/workflows/{slug}/edges/` | Edge (connection) CRUD within a workflow |
| [Executions](executions.md) | `/api/v1/executions/` | Execution list, detail, cancel |
| [Chat](chat.md) | `/api/v1/workflows/{slug}/chat/` | Chat trigger messaging and history |
| [Credentials](credentials.md) | `/api/v1/credentials/` | API key and credential management |
| [Schedules](schedules.md) | `/api/v1/schedules/` | Scheduled job CRUD and control |
| [Memory](memory-api.md) | `/api/v1/memories/` | Facts, episodes, procedures, users, checkpoints |
| [Epics](epics.md) | `/api/v1/epics/` | Epic project management |
| [Tasks](tasks.md) | `/api/v1/tasks/` | Task management within epics |
| [Users](users.md) | `/api/v1/users/` | Agent user management |
| [WebSocket](websocket.md) | `/ws/` | Real-time event streaming |

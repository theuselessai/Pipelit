# Workflows

Workflow CRUD, validation, and node type discovery endpoints.

All endpoints are under `/api/v1/workflows/` and require Bearer token authentication.

---

## GET /api/v1/workflows/

List workflows accessible to the authenticated user (owned or collaborated).

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit`   | int  | 50      | Max items per page |
| `offset`  | int  | 0       | Items to skip |

**Example request:**

```bash
curl http://localhost:8000/api/v1/workflows/?limit=10&offset=0 \
  -H "Authorization: Bearer <api_key>"
```

**Response (200):**

```json
{
  "items": [
    {
      "id": 1,
      "name": "My Chatbot",
      "slug": "my-chatbot",
      "description": "A customer support chatbot",
      "is_active": true,
      "is_public": false,
      "is_default": false,
      "tags": ["support", "chatbot"],
      "error_handler_workflow_id": null,
      "input_schema": null,
      "output_schema": null,
      "node_count": 5,
      "edge_count": 4,
      "created_at": "2025-01-15T10:30:00",
      "updated_at": "2025-01-15T12:00:00"
    }
  ],
  "total": 1
}
```

---

## POST /api/v1/workflows/

Create a new workflow.

**Request body:**

| Field                       | Type        | Required | Default | Description |
|-----------------------------|-------------|----------|---------|-------------|
| `name`                      | string      | yes      |         | Display name |
| `slug`                      | string      | yes      |         | URL-friendly identifier (unique) |
| `description`               | string      | no       | `""`    | Description |
| `is_active`                 | boolean     | no       | `true`  | Whether the workflow is active |
| `is_public`                 | boolean     | no       | `false` | Whether the workflow is publicly accessible |
| `is_default`                | boolean     | no       | `false` | Whether this is the default workflow |
| `tags`                      | string[]    | no       | `null`  | Tags for categorization |
| `error_handler_workflow_id` | int or null | no       | `null`  | Workflow ID for error handling |
| `input_schema`              | object      | no       | `null`  | JSON Schema for workflow input |
| `output_schema`             | object      | no       | `null`  | JSON Schema for workflow output |

**Example request:**

```bash
curl -X POST http://localhost:8000/api/v1/workflows/ \
  -H "Authorization: Bearer <api_key>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Chatbot",
    "slug": "my-chatbot",
    "description": "A customer support chatbot",
    "tags": ["support"]
  }'
```

**Response (201):**

```json
{
  "id": 1,
  "name": "My Chatbot",
  "slug": "my-chatbot",
  "description": "A customer support chatbot",
  "is_active": true,
  "is_public": false,
  "is_default": false,
  "tags": ["support"],
  "error_handler_workflow_id": null,
  "input_schema": null,
  "output_schema": null,
  "node_count": 0,
  "edge_count": 0,
  "created_at": "2025-01-15T10:30:00",
  "updated_at": "2025-01-15T10:30:00"
}
```

---

## GET /api/v1/workflows/{slug}/

Get full workflow detail including all nodes and edges.

**Path parameters:**

| Parameter | Type   | Description |
|-----------|--------|-------------|
| `slug`    | string | Workflow slug |

**Example request:**

```bash
curl http://localhost:8000/api/v1/workflows/my-chatbot/ \
  -H "Authorization: Bearer <api_key>"
```

**Response (200):**

Returns the workflow object with additional `nodes` and `edges` arrays:

```json
{
  "id": 1,
  "name": "My Chatbot",
  "slug": "my-chatbot",
  "description": "A customer support chatbot",
  "is_active": true,
  "is_public": false,
  "is_default": false,
  "tags": ["support"],
  "error_handler_workflow_id": null,
  "input_schema": null,
  "output_schema": null,
  "node_count": 2,
  "edge_count": 1,
  "created_at": "2025-01-15T10:30:00",
  "updated_at": "2025-01-15T12:00:00",
  "nodes": [ ... ],
  "edges": [ ... ]
}
```

**Error (404):** `"Workflow not found."`

---

## PATCH /api/v1/workflows/{slug}/

Update a workflow. Only include fields you want to change.

**Path parameters:**

| Parameter | Type   | Description |
|-----------|--------|-------------|
| `slug`    | string | Workflow slug |

**Request body (all fields optional):**

| Field                       | Type        | Description |
|-----------------------------|-------------|-------------|
| `name`                      | string      | Display name |
| `slug`                      | string      | URL-friendly identifier |
| `description`               | string      | Description |
| `is_active`                 | boolean     | Active state |
| `is_public`                 | boolean     | Public visibility |
| `is_default`                | boolean     | Default workflow flag |
| `tags`                      | string[]    | Tags |
| `error_handler_workflow_id` | int or null | Error handler workflow ID |
| `input_schema`              | object      | Input JSON Schema |
| `output_schema`             | object      | Output JSON Schema |

**Example request:**

```bash
curl -X PATCH http://localhost:8000/api/v1/workflows/my-chatbot/ \
  -H "Authorization: Bearer <api_key>" \
  -H "Content-Type: application/json" \
  -d '{"description": "Updated description"}'
```

**Response (200):** Updated workflow object.

Broadcasts a `workflow_updated` WebSocket event on the `workflow:<slug>` channel.

---

## DELETE /api/v1/workflows/{slug}/

Soft-delete a workflow.

**Path parameters:**

| Parameter | Type   | Description |
|-----------|--------|-------------|
| `slug`    | string | Workflow slug |

**Example request:**

```bash
curl -X DELETE http://localhost:8000/api/v1/workflows/my-chatbot/ \
  -H "Authorization: Bearer <api_key>"
```

**Response (204):** No content.

---

## POST /api/v1/workflows/batch-delete/

Batch soft-delete multiple workflows.

**Request body:**

| Field   | Type     | Required | Description |
|---------|----------|----------|-------------|
| `slugs` | string[] | yes      | List of workflow slugs to delete |

**Example request:**

```bash
curl -X POST http://localhost:8000/api/v1/workflows/batch-delete/ \
  -H "Authorization: Bearer <api_key>" \
  -H "Content-Type: application/json" \
  -d '{"slugs": ["workflow-1", "workflow-2"]}'
```

**Response (204):** No content.

---

## POST /api/v1/workflows/{slug}/validate/

Validate a workflow's structural integrity. Checks edge type compatibility and required sub-component connections (e.g., agent nodes require a model connection).

**Path parameters:**

| Parameter | Type   | Description |
|-----------|--------|-------------|
| `slug`    | string | Workflow slug |

**Example request:**

```bash
curl -X POST http://localhost:8000/api/v1/workflows/my-chatbot/validate/ \
  -H "Authorization: Bearer <api_key>"
```

**Response (200) -- valid:**

```json
{
  "valid": true,
  "errors": []
}
```

**Response (200) -- invalid:**

```json
{
  "valid": false,
  "errors": [
    "Node 'agent_abc123' is missing required 'model' connection"
  ]
}
```

---

## GET /api/v1/workflows/node-types/

List all available component (node) types with their port definitions and configuration schemas.

**Example request:**

```bash
curl http://localhost:8000/api/v1/workflows/node-types/ \
  -H "Authorization: Bearer <api_key>"
```

**Response (200):**

Returns a dictionary keyed by component type:

```json
{
  "agent": {
    "label": "Agent",
    "category": "AI",
    "description": "LLM-powered agent with tool calling",
    "icon": "robot",
    "color": "#8b5cf6",
    "inputs": [
      {"name": "input", "data_type": "text", "required": true}
    ],
    "outputs": [
      {"name": "output", "data_type": "text"}
    ],
    "sub_inputs": [
      {"name": "model", "data_type": "llm", "required": true},
      {"name": "tools", "data_type": "tool", "required": false},
      {"name": "memory", "data_type": "memory", "required": false}
    ],
    "executable": true
  },
  "trigger_chat": {
    "label": "Chat Trigger",
    "category": "Triggers",
    "description": "Receives chat messages",
    "icon": "comments",
    "color": "#f97316",
    "inputs": [],
    "outputs": [
      {"name": "text", "data_type": "text"}
    ],
    "sub_inputs": [],
    "executable": true
  }
}
```

---

## POST /api/v1/workflows/validate-dsl/

Validate a YAML DSL workflow definition.

**Request body:**

| Field      | Type   | Required | Description |
|------------|--------|----------|-------------|
| `yaml_str` | string | yes      | YAML DSL string to validate |

**Example request:**

```bash
curl -X POST http://localhost:8000/api/v1/workflows/validate-dsl/ \
  -H "Authorization: Bearer <api_key>" \
  -H "Content-Type: application/json" \
  -d '{"yaml_str": "name: test\nnodes:\n  - id: trigger\n    type: trigger_chat"}'
```

**Response (200):** Validation result object.

# Edges

Edge (connection) CRUD endpoints for managing connections between workflow nodes. Edges are nested under their parent workflow.

All endpoints are under `/api/v1/workflows/{slug}/edges/` and require Bearer token authentication.

---

## Concepts

### Edge Types

| Type          | Description |
|---------------|-------------|
| `direct`      | Standard data flow between nodes |
| `conditional` | Conditional routing from `switch` nodes. Each conditional edge carries a `condition_value` that is matched against the switch node's output route. |

### Edge Labels

Edge labels indicate the type of connection:

| Label           | Description |
|-----------------|-------------|
| `""` (empty)    | Standard data flow |
| `llm`           | Model connection (ai_model to an AI node) |
| `tool`          | Tool connection (tool node to agent) |
| `memory`        | Memory connection |
| `output_parser` | Output parser connection |
| `loop_body`     | Loop node to body node (flow control) |
| `loop_return`   | Body node back to loop node (flow control) |

### Validation

When creating edges, the API validates type compatibility between source outputs and target inputs. Incompatible connections return a `422` error with validation details.

Loop flow-control edges (`loop_body`, `loop_return`) bypass type-compatibility validation.

Conditional edges can only originate from `switch` nodes.

---

## GET /api/v1/workflows/{slug}/edges/

List all edges in a workflow.

**Path parameters:**

| Parameter | Type   | Description |
|-----------|--------|-------------|
| `slug`    | string | Workflow slug |

**Example request:**

```bash
curl http://localhost:8000/api/v1/workflows/my-chatbot/edges/ \
  -H "Authorization: Bearer <api_key>"
```

**Response (200):**

```json
[
  {
    "id": 1,
    "source_node_id": "trigger_chat_a1b2c3",
    "target_node_id": "agent_abc123",
    "edge_type": "direct",
    "edge_label": "",
    "condition_mapping": null,
    "condition_value": "",
    "priority": 0
  },
  {
    "id": 2,
    "source_node_id": "ai_model_xyz789",
    "target_node_id": "agent_abc123",
    "edge_type": "direct",
    "edge_label": "llm",
    "condition_mapping": null,
    "condition_value": "",
    "priority": 0
  }
]
```

!!! note
    Edge list endpoints return a flat array, not a paginated envelope.

---

## POST /api/v1/workflows/{slug}/edges/

Create a new edge connecting two nodes.

**Path parameters:**

| Parameter | Type   | Description |
|-----------|--------|-------------|
| `slug`    | string | Workflow slug |

**Request body:**

| Field               | Type   | Required | Default    | Description |
|---------------------|--------|----------|------------|-------------|
| `source_node_id`    | string | yes      |            | Source node ID |
| `target_node_id`    | string | yes      |            | Target node ID |
| `edge_type`         | string | no       | `"direct"` | `"direct"` or `"conditional"` |
| `edge_label`        | string | no       | `""`       | Connection type label (see [Edge Labels](#edge-labels)) |
| `condition_mapping` | object | no       | `null`     | Legacy: mapping of route values to target node IDs |
| `condition_value`   | string | no       | `""`       | Route value for conditional edges |
| `priority`          | int    | no       | `0`        | Edge priority |

**Example -- data flow edge:**

```bash
curl -X POST http://localhost:8000/api/v1/workflows/my-chatbot/edges/ \
  -H "Authorization: Bearer <api_key>" \
  -H "Content-Type: application/json" \
  -d '{
    "source_node_id": "trigger_chat_a1b2c3",
    "target_node_id": "agent_abc123"
  }'
```

**Example -- model connection (LLM edge):**

```bash
curl -X POST http://localhost:8000/api/v1/workflows/my-chatbot/edges/ \
  -H "Authorization: Bearer <api_key>" \
  -H "Content-Type: application/json" \
  -d '{
    "source_node_id": "ai_model_xyz789",
    "target_node_id": "agent_abc123",
    "edge_label": "llm"
  }'
```

**Example -- conditional edge from a switch node:**

```bash
curl -X POST http://localhost:8000/api/v1/workflows/my-chatbot/edges/ \
  -H "Authorization: Bearer <api_key>" \
  -H "Content-Type: application/json" \
  -d '{
    "source_node_id": "switch_def456",
    "target_node_id": "agent_support",
    "edge_type": "conditional",
    "condition_value": "support"
  }'
```

**Response (201):**

```json
{
  "id": 3,
  "source_node_id": "trigger_chat_a1b2c3",
  "target_node_id": "agent_abc123",
  "edge_type": "direct",
  "edge_label": "",
  "condition_mapping": null,
  "condition_value": "",
  "priority": 0
}
```

Broadcasts an `edge_created` WebSocket event on the `workflow:<slug>` channel.

**Error (422) -- type mismatch:**

```json
{
  "detail": {
    "validation_errors": [
      "Source type 'calculator' output 'result' (number) is not compatible with target 'ai_model' input 'model' (llm)"
    ]
  }
}
```

**Error (422) -- conditional edge rules:**

- `"Conditional edges require a non-empty condition_value"`
- `"Conditional edges require a non-empty target_node_id"`
- `"Conditional edges can only originate from 'switch' nodes"`

---

## PATCH /api/v1/workflows/{slug}/edges/{edge_id}/

Update an existing edge.

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `slug`    | string | Workflow slug |
| `edge_id` | int    | Edge database ID |

**Request body (all fields optional):**

| Field               | Type   | Description |
|---------------------|--------|-------------|
| `source_node_id`    | string | Source node ID |
| `target_node_id`    | string | Target node ID |
| `edge_type`         | string | `"direct"` or `"conditional"` |
| `edge_label`        | string | Connection type label |
| `condition_mapping` | object | Route-to-target mapping |
| `condition_value`   | string | Route value for conditional edges |
| `priority`          | int    | Edge priority |

**Example request:**

```bash
curl -X PATCH http://localhost:8000/api/v1/workflows/my-chatbot/edges/3/ \
  -H "Authorization: Bearer <api_key>" \
  -H "Content-Type: application/json" \
  -d '{"condition_value": "billing"}'
```

**Response (200):** Updated edge object.

Broadcasts an `edge_updated` WebSocket event on the `workflow:<slug>` channel.

**Error (404):** `"Edge not found."`

---

## DELETE /api/v1/workflows/{slug}/edges/{edge_id}/

Delete an edge. If the edge has an `llm` label, the sub-component link on the target node is also cleared.

**Path parameters:**

| Parameter | Type   | Description |
|-----------|--------|-------------|
| `slug`    | string | Workflow slug |
| `edge_id` | int    | Edge database ID |

**Example request:**

```bash
curl -X DELETE http://localhost:8000/api/v1/workflows/my-chatbot/edges/3/ \
  -H "Authorization: Bearer <api_key>"
```

**Response (204):** No content.

Broadcasts an `edge_deleted` WebSocket event on the `workflow:<slug>` channel.

**Error (404):** `"Edge not found."`

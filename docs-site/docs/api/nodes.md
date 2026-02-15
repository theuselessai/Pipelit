# Nodes

Node CRUD endpoints for managing workflow nodes. Nodes are nested under their parent workflow.

All endpoints are under `/api/v1/workflows/{slug}/nodes/` and require Bearer token authentication.

---

## GET /api/v1/workflows/{slug}/nodes/

List all nodes in a workflow.

**Path parameters:**

| Parameter | Type   | Description |
|-----------|--------|-------------|
| `slug`    | string | Workflow slug |

**Example request:**

```bash
curl http://localhost:8000/api/v1/workflows/my-chatbot/nodes/ \
  -H "Authorization: Bearer <api_key>"
```

**Response (200):**

```json
[
  {
    "id": 1,
    "node_id": "trigger_chat_a1b2c3",
    "component_type": "trigger_chat",
    "is_entry_point": false,
    "interrupt_before": false,
    "interrupt_after": false,
    "position_x": 100,
    "position_y": 200,
    "config": {
      "system_prompt": "",
      "extra_config": {},
      "llm_credential_id": null,
      "model_name": "",
      "temperature": null,
      "max_tokens": null,
      "frequency_penalty": null,
      "presence_penalty": null,
      "top_p": null,
      "timeout": null,
      "max_retries": null,
      "response_format": null,
      "llm_model_config_id": null,
      "credential_id": null,
      "is_active": true,
      "priority": 0,
      "trigger_config": {}
    },
    "subworkflow_id": null,
    "code_block_id": null,
    "updated_at": "2025-01-15T10:30:00",
    "schedule_job": null
  }
]
```

!!! note
    Node list endpoints return a flat array, not a paginated envelope.

---

## POST /api/v1/workflows/{slug}/nodes/

Create a new node in a workflow.

**Path parameters:**

| Parameter | Type   | Description |
|-----------|--------|-------------|
| `slug`    | string | Workflow slug |

**Request body:**

| Field              | Type   | Required | Default | Description |
|--------------------|--------|----------|---------|-------------|
| `node_id`          | string | yes      |         | Unique node identifier (e.g., `agent_abc123`) |
| `component_type`   | string | yes      |         | Node type (see [Component Types](#component-types)) |
| `is_entry_point`   | bool   | no       | `false` | Whether this node is an entry point |
| `interrupt_before` | bool   | no       | `false` | Pause execution before this node |
| `interrupt_after`  | bool   | no       | `false` | Pause execution after this node |
| `position_x`       | int    | no       | `0`     | Canvas X position |
| `position_y`       | int    | no       | `0`     | Canvas Y position |
| `config`           | object | no       | `{}`    | Component configuration (see below) |
| `subworkflow_id`   | int    | no       | `null`  | ID of sub-workflow (for workflow nodes) |
| `code_block_id`    | int    | no       | `null`  | ID of code block (for code nodes) |

**Config object fields:**

| Field               | Type   | Applies To | Description |
|---------------------|--------|------------|-------------|
| `system_prompt`     | string | AI nodes (agent, categorizer, router, extractor) | System prompt for the LLM |
| `extra_config`      | object | All        | Type-specific configuration |
| `llm_credential_id` | int   | ai_model   | LLM credential to use |
| `model_name`        | string | ai_model   | Model identifier |
| `temperature`       | float  | ai_model   | Sampling temperature |
| `max_tokens`        | int    | ai_model   | Maximum output tokens |
| `frequency_penalty` | float  | ai_model   | Frequency penalty |
| `presence_penalty`  | float  | ai_model   | Presence penalty |
| `top_p`             | float  | ai_model   | Top-p sampling |
| `timeout`           | int    | ai_model   | Request timeout in seconds |
| `max_retries`       | int    | ai_model   | Max retry attempts |
| `response_format`   | object | ai_model   | Structured output format |
| `credential_id`     | int    | Triggers   | Credential for trigger authentication |
| `is_active`         | bool   | Triggers   | Whether the trigger is active |
| `priority`          | int    | Triggers   | Trigger priority (0 = default) |
| `trigger_config`    | object | Triggers   | Trigger-specific settings |

**Example request:**

```bash
curl -X POST http://localhost:8000/api/v1/workflows/my-chatbot/nodes/ \
  -H "Authorization: Bearer <api_key>" \
  -H "Content-Type: application/json" \
  -d '{
    "node_id": "agent_abc123",
    "component_type": "agent",
    "position_x": 400,
    "position_y": 200,
    "config": {
      "system_prompt": "You are a helpful assistant."
    }
  }'
```

**Response (201):** Node object (same format as list response items).

Broadcasts a `node_created` WebSocket event on the `workflow:<slug>` channel.

---

## PATCH /api/v1/workflows/{slug}/nodes/{node_id}/

Update an existing node's configuration or position.

**Path parameters:**

| Parameter | Type   | Description |
|-----------|--------|-------------|
| `slug`    | string | Workflow slug |
| `node_id` | string | Node identifier |

**Request body (all fields optional):**

Same fields as create, but all are optional. Only include the fields you want to update.

**Example request:**

```bash
curl -X PATCH http://localhost:8000/api/v1/workflows/my-chatbot/nodes/agent_abc123/ \
  -H "Authorization: Bearer <api_key>" \
  -H "Content-Type: application/json" \
  -d '{
    "position_x": 500,
    "config": {
      "system_prompt": "You are a customer support agent."
    }
  }'
```

**Response (200):** Updated node object.

Broadcasts a `node_updated` WebSocket event on the `workflow:<slug>` channel.

**Error (404):** `"Node not found."`

---

## DELETE /api/v1/workflows/{slug}/nodes/{node_id}/

Delete a node and all its connected edges. If the node is a `trigger_schedule`, any associated scheduled job is also cleaned up.

**Path parameters:**

| Parameter | Type   | Description |
|-----------|--------|-------------|
| `slug`    | string | Workflow slug |
| `node_id` | string | Node identifier |

**Example request:**

```bash
curl -X DELETE http://localhost:8000/api/v1/workflows/my-chatbot/nodes/agent_abc123/ \
  -H "Authorization: Bearer <api_key>"
```

**Response (204):** No content.

Broadcasts a `node_deleted` WebSocket event on the `workflow:<slug>` channel.

**Error (404):** `"Node not found."`

---

## Schedule Actions

These endpoints manage the scheduled execution of `trigger_schedule` nodes.

### POST /api/v1/workflows/{slug}/nodes/{node_id}/schedule/start

Start or restart a scheduled job for a `trigger_schedule` node. Configuration is read from the node's `extra_config`.

**Extra config fields:**

| Field               | Type   | Default | Description |
|---------------------|--------|---------|-------------|
| `interval_seconds`  | int    | 300     | Seconds between runs |
| `total_repeats`     | int    | 0       | Total runs (0 = unlimited) |
| `max_retries`       | int    | 3       | Max retries per run |
| `timeout_seconds`   | int    | 600     | Timeout per run |
| `trigger_payload`   | object | `{}`    | Payload passed to the trigger |

**Response (200):** Updated node object.

**Error (400):** `"Node is not a trigger_schedule."`

### POST /api/v1/workflows/{slug}/nodes/{node_id}/schedule/pause

Pause an active scheduled job.

**Response (200):** Updated node object.

**Error (400):** `"Cannot pause job with status 'paused'."`

### POST /api/v1/workflows/{slug}/nodes/{node_id}/schedule/stop

Stop and remove a scheduled job.

**Response (200):** Updated node object.

---

## Component Types

The following component types are available:

| Category | Types |
|----------|-------|
| **AI** | `agent`, `categorizer`, `router`, `extractor` |
| **Models** | `ai_model` |
| **Routing** | `switch` |
| **Tools** | `run_command`, `http_request`, `web_search`, `calculator`, `datetime`, `create_agent_user`, `platform_api`, `whoami`, `epic_tools`, `task_tools`, `spawn_and_await`, `workflow_create`, `workflow_discover`, `scheduler_tools`, `system_health` |
| **Processing** | `aggregator`, `human_confirmation`, `workflow`, `code`, `code_execute`, `loop`, `wait`, `merge`, `filter`, `error_handler`, `output_parser` |
| **Memory** | `memory_read`, `memory_write`, `identify_user` |
| **Triggers** | `trigger_telegram`, `trigger_schedule`, `trigger_manual`, `trigger_workflow`, `trigger_error`, `trigger_chat` |

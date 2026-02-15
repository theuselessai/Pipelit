# Chat

Chat endpoints for sending messages to workflows with chat triggers and managing chat history. Messages are sent to a workflow's `trigger_chat` node, which starts a new execution.

All endpoints are under `/api/v1/workflows/{slug}/chat/` and require Bearer token authentication.

---

## POST /api/v1/workflows/{slug}/chat/

Send a chat message to a workflow and start a new execution. The workflow must have at least one `trigger_chat` node.

The execution runs asynchronously via a background job. Use the [WebSocket](websocket.md) to receive real-time status updates and the final response.

**Path parameters:**

| Parameter | Type   | Description |
|-----------|--------|-------------|
| `slug`    | string | Workflow slug |

**Request body:**

| Field             | Type   | Required | Description |
|-------------------|--------|----------|-------------|
| `text`            | string | yes      | Chat message text |
| `trigger_node_id` | string | no       | Specific chat trigger node ID. If omitted, uses the first `trigger_chat` node. |

**Example request:**

```bash
curl -X POST http://localhost:8000/api/v1/workflows/my-chatbot/chat/ \
  -H "Authorization: Bearer <api_key>" \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello, I need help with my order"}'
```

**Response (200):**

```json
{
  "execution_id": "abc12345-def6-7890-abcd-ef1234567890",
  "status": "pending",
  "response": ""
}
```

| Field          | Type   | Description |
|----------------|--------|-------------|
| `execution_id` | string | UUID of the created execution |
| `status`       | string | Initial status (always `"pending"`) |
| `response`     | string | Empty initially; the actual response arrives via WebSocket |

**Error (404):**

- `"Workflow not found."` -- workflow with the given slug does not exist.
- `"No chat trigger found."` -- workflow has no `trigger_chat` node (or the specified `trigger_node_id` does not match a chat trigger).

---

## GET /api/v1/workflows/{slug}/chat/history

Load chat history from LangGraph checkpoints for the authenticated user's conversation with this workflow.

**Path parameters:**

| Parameter | Type   | Description |
|-----------|--------|-------------|
| `slug`    | string | Workflow slug |

**Query parameters:**

| Parameter | Type   | Default | Description |
|-----------|--------|---------|-------------|
| `limit`   | int    | 10      | Max messages to return |
| `before`  | string | `null`  | ISO datetime string -- only return messages before this time |

**Example request:**

```bash
curl "http://localhost:8000/api/v1/workflows/my-chatbot/chat/history?limit=20" \
  -H "Authorization: Bearer <api_key>"
```

**Response (200):**

```json
{
  "messages": [
    {
      "role": "user",
      "text": "Hello, I need help with my order",
      "timestamp": "2025-01-15T10:30:00"
    },
    {
      "role": "assistant",
      "text": "I'd be happy to help! Could you provide your order number?",
      "timestamp": "2025-01-15T10:30:05"
    }
  ],
  "thread_id": "1:5",
  "has_more": false
}
```

| Field       | Type     | Description |
|-------------|----------|-------------|
| `messages`  | array    | List of chat messages |
| `thread_id` | string   | Checkpoint thread ID (format: `{user_id}:{workflow_id}`) |
| `has_more`  | boolean  | Whether older messages exist beyond the current page |

**Message fields:**

| Field       | Type          | Description |
|-------------|---------------|-------------|
| `role`      | string        | `"user"` or `"assistant"` |
| `text`      | string        | Message content |
| `timestamp` | string or null | ISO datetime when the message was created |

---

## DELETE /api/v1/workflows/{slug}/chat/history

Clear all chat history for the authenticated user's conversation with this workflow. This deletes the LangGraph checkpoint data.

**Path parameters:**

| Parameter | Type   | Description |
|-----------|--------|-------------|
| `slug`    | string | Workflow slug |

**Example request:**

```bash
curl -X DELETE http://localhost:8000/api/v1/workflows/my-chatbot/chat/history \
  -H "Authorization: Bearer <api_key>"
```

**Response (204):** No content.

**Error (404):** `"Workflow not found."`

!!! warning
    This permanently deletes the conversation history stored in checkpoints. The agent will have no memory of previous conversations after this operation.

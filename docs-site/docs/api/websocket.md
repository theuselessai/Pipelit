# WebSocket

Pipelit uses a single global authenticated WebSocket connection for real-time event streaming. All workflow, node, edge, and execution events are delivered through this connection using Redis pub/sub fan-out.

---

## Connection

### Endpoint

```
ws://localhost:8000/ws/?token=<api_key>
```

The `token` query parameter must be a valid API key (the same key used for Bearer token authentication).

### Authentication

Authentication happens on connection. If the token is missing or invalid, the server closes the WebSocket with code `1008` and reason `"Invalid or missing token"`.

### Connection Example (JavaScript)

```javascript
const ws = new WebSocket(`ws://localhost:8000/ws/?token=${apiKey}`);

ws.onopen = () => {
  console.log("Connected");
  // Subscribe to a workflow channel
  ws.send(JSON.stringify({
    type: "subscribe",
    channel: "workflow:my-chatbot"
  }));
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log("Received:", data);
};
```

---

## Heartbeat

The server sends a `ping` message every 30 seconds of inactivity. The client must respond with a `pong` within 10 seconds, or the connection will be closed.

**Server sends:**

```json
{"type": "ping"}
```

**Client responds:**

```json
{"type": "pong"}
```

---

## Subscription Protocol

Clients subscribe to channels to receive events. Only events from subscribed channels are forwarded.

### Subscribe

**Client sends:**

```json
{
  "type": "subscribe",
  "channel": "workflow:my-chatbot"
}
```

**Server responds:**

```json
{
  "type": "subscribed",
  "channel": "workflow:my-chatbot"
}
```

### Unsubscribe

**Client sends:**

```json
{
  "type": "unsubscribe",
  "channel": "workflow:my-chatbot"
}
```

**Server responds:**

```json
{
  "type": "unsubscribed",
  "channel": "workflow:my-chatbot"
}
```

### Channel Naming

| Pattern               | Description |
|-----------------------|-------------|
| `workflow:<slug>`     | All events for a specific workflow (nodes, edges, executions) |
| `execution:<id>`      | Events for a specific execution |
| `epic:<id>`           | Events for a specific epic (epic and task updates) |

---

## Event Types

All events follow this envelope format:

```json
{
  "type": "<event_type>",
  "channel": "<channel>",
  "timestamp": 1705312200.123,
  "data": { ... }
}
```

| Field       | Type   | Description |
|-------------|--------|-------------|
| `type`      | string | Event type identifier |
| `channel`   | string | Channel this event was published to |
| `timestamp` | float  | Unix timestamp when the event was published |
| `data`      | object | Event-specific payload |

### Workflow Events

Published on `workflow:<slug>` channels.

#### workflow_updated

Fired when a workflow's metadata is updated.

```json
{
  "type": "workflow_updated",
  "channel": "workflow:my-chatbot",
  "timestamp": 1705312200.123,
  "data": {
    "id": 1,
    "name": "My Chatbot",
    "slug": "my-chatbot",
    "description": "Updated description",
    "is_active": true,
    "is_public": false,
    "is_default": false,
    "tags": [],
    "node_count": 3,
    "edge_count": 2,
    "created_at": "2025-01-15T10:30:00",
    "updated_at": "2025-01-15T12:00:00"
  }
}
```

### Node Events

Published on `workflow:<slug>` channels.

#### node_created

```json
{
  "type": "node_created",
  "channel": "workflow:my-chatbot",
  "timestamp": 1705312200.123,
  "data": {
    "id": 1,
    "node_id": "agent_abc123",
    "component_type": "agent",
    "is_entry_point": false,
    "interrupt_before": false,
    "interrupt_after": false,
    "position_x": 400,
    "position_y": 200,
    "config": { ... },
    "updated_at": "2025-01-15T10:30:00"
  }
}
```

#### node_updated

Same payload as `node_created` but with updated fields.

#### node_deleted

```json
{
  "type": "node_deleted",
  "channel": "workflow:my-chatbot",
  "timestamp": 1705312200.123,
  "data": {
    "node_id": "agent_abc123"
  }
}
```

### Edge Events

Published on `workflow:<slug>` channels.

#### edge_created

```json
{
  "type": "edge_created",
  "channel": "workflow:my-chatbot",
  "timestamp": 1705312200.123,
  "data": {
    "id": 1,
    "source_node_id": "trigger_chat_a1b2c3",
    "target_node_id": "agent_abc123",
    "edge_type": "direct",
    "edge_label": "",
    "condition_mapping": null,
    "condition_value": "",
    "priority": 0
  }
}
```

#### edge_updated

Same payload as `edge_created` but with updated fields.

#### edge_deleted

```json
{
  "type": "edge_deleted",
  "channel": "workflow:my-chatbot",
  "timestamp": 1705312200.123,
  "data": {
    "id": 1
  }
}
```

### Execution Events

Published on `workflow:<slug>` channels by the orchestrator.

#### node_status

Per-node execution status updates. Published as each node in the workflow starts and finishes.

```json
{
  "type": "node_status",
  "channel": "workflow:my-chatbot",
  "timestamp": 1705312200.123,
  "data": {
    "execution_id": "abc12345-def6-7890",
    "node_id": "agent_abc123",
    "status": "running"
  }
}
```

Status values: `pending`, `running`, `success`, `failed`, `skipped`.

On `success`, the `data` object includes the node output:

```json
{
  "type": "node_status",
  "channel": "workflow:my-chatbot",
  "timestamp": 1705312201.456,
  "data": {
    "execution_id": "abc12345-def6-7890",
    "node_id": "agent_abc123",
    "status": "success",
    "output": {
      "output": "Hello! How can I help you today?"
    }
  }
}
```

On `failed`, the `data` object includes error details:

```json
{
  "type": "node_status",
  "channel": "workflow:my-chatbot",
  "timestamp": 1705312201.456,
  "data": {
    "execution_id": "abc12345-def6-7890",
    "node_id": "agent_abc123",
    "status": "failed",
    "error": "LLM API returned 429: rate limit exceeded",
    "error_code": "LLM_ERROR"
  }
}
```

#### execution_completed

Fired when an entire execution finishes successfully.

```json
{
  "type": "execution_completed",
  "channel": "workflow:my-chatbot",
  "timestamp": 1705312205.789,
  "data": {
    "execution_id": "abc12345-def6-7890"
  }
}
```

#### execution_failed

Fired when an execution fails.

```json
{
  "type": "execution_failed",
  "channel": "workflow:my-chatbot",
  "timestamp": 1705312205.789,
  "data": {
    "execution_id": "abc12345-def6-7890",
    "error": "Node agent_abc123 failed: LLM API error"
  }
}
```

#### execution_interrupted

Fired when an execution is interrupted (e.g., at a human confirmation node).

```json
{
  "type": "execution_interrupted",
  "channel": "workflow:my-chatbot",
  "timestamp": 1705312205.789,
  "data": {
    "execution_id": "abc12345-def6-7890"
  }
}
```

#### execution_cancelled

Fired when an execution is cancelled via the API.

```json
{
  "type": "execution_cancelled",
  "channel": "workflow:my-chatbot",
  "timestamp": 1705312205.789,
  "data": {
    "execution_id": "abc12345-def6-7890"
  }
}
```

### Epic Events

Published on `epic:<id>` channels.

#### epic_created / epic_updated / epic_deleted

```json
{
  "type": "epic_updated",
  "channel": "epic:epic-uuid-1234",
  "timestamp": 1705312200.123,
  "data": { ... }
}
```

#### task_created / task_updated / task_deleted / tasks_deleted

```json
{
  "type": "task_updated",
  "channel": "epic:epic-uuid-1234",
  "timestamp": 1705312200.123,
  "data": { ... }
}
```

---

## Full Subscription Flow Example

Here is a complete example showing connection, subscription, receiving events, and cleanup:

```javascript
// 1. Connect with authentication
const ws = new WebSocket(`ws://localhost:8000/ws/?token=${apiKey}`);

// 2. Handle connection open
ws.onopen = () => {
  // Subscribe to workflow events
  ws.send(JSON.stringify({
    type: "subscribe",
    channel: "workflow:my-chatbot"
  }));
};

// 3. Handle incoming messages
ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);

  switch (msg.type) {
    case "subscribed":
      console.log(`Subscribed to ${msg.channel}`);
      break;

    case "ping":
      // Respond to heartbeat
      ws.send(JSON.stringify({ type: "pong" }));
      break;

    case "node_status":
      console.log(`Node ${msg.data.node_id}: ${msg.data.status}`);
      break;

    case "execution_completed":
      console.log(`Execution ${msg.data.execution_id} completed`);
      break;

    case "node_created":
    case "node_updated":
    case "node_deleted":
      // Update local node state
      console.log(`Node event: ${msg.type}`, msg.data);
      break;

    case "edge_created":
    case "edge_updated":
    case "edge_deleted":
      // Update local edge state
      console.log(`Edge event: ${msg.type}`, msg.data);
      break;
  }
};

// 4. Cleanup on close
ws.onclose = (event) => {
  console.log(`Disconnected: ${event.code} ${event.reason}`);
};

// 5. Unsubscribe when leaving a page
function cleanup() {
  ws.send(JSON.stringify({
    type: "unsubscribe",
    channel: "workflow:my-chatbot"
  }));
}
```

---

## Reconnection

The Pipelit frontend uses an exponential backoff strategy for reconnection:

1. Initial reconnect delay: 1 second.
2. Each failed attempt doubles the delay, up to a maximum of 30 seconds.
3. On successful reconnection, all previous subscriptions are automatically re-established.

Clients should implement similar reconnection logic to handle network interruptions.

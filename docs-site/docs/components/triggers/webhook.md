# Webhook Trigger

The webhook trigger starts a workflow when an HTTP POST request is received. This enables external services to initiate workflow executions.

## Endpoint

```
POST /api/v1/webhooks/{workflow_slug}
```

| Component | Value |
|-----------|-------|
| Base URL | `https://your-pipelit-instance.com` |
| Path | `/api/v1/webhooks/{workflow_slug}` |
| Method | `POST` |

## Authentication

### Option 1: API Key Header

Include your API key in the `Authorization` header:

```bash
curl -X POST https://your-pipelit-instance.com/api/v1/webhooks/my-workflow \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello from webhook"}'
```

### Option 2: Query Parameter

Pass the API key as a query parameter:

```bash
curl -X POST "https://your-pipelit-instance.com/api/v1/webhooks/my-workflow?api_key=YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello from webhook"}'
```

## Payload

The webhook payload is passed to the workflow as input. You can access it in your workflow nodes.

### Example Payload

```json
{
  "event": "payment_received",
  "data": {
    "amount": 99.00,
    "currency": "USD",
    "customer_id": "cus_123"
  },
  "timestamp": "2026-03-02T12:00:00Z"
}
```

### Accessing Payload in Workflow

In expression nodes or component configs:

```
{{ input.event }}
{{ input.data.amount }}
{{ input.timestamp }}
```

## Response

### Success (200)

```json
{
  "status": "accepted",
  "execution_id": "exec_abc123",
  "message": "Workflow execution started"
}
```

### Authentication Error (401)

```json
{
  "detail": "Invalid or missing API key"
}
```

### Not Found (404)

```json
{
  "detail": "Workflow 'my-workflow' not found"
}
```

## Testing

### Using curl

```bash
# Basic test
curl -X POST https://your-pipelit-instance.com/api/v1/webhooks/my-workflow \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"test": true}'
```

## Use Cases

- **GitHub/GitLab webhooks** — Trigger workflows on push, PR, or merge events
- **Payment webhooks** — Process payment events from Stripe, PayPal
- **IoT devices** — Start workflows when sensors trigger

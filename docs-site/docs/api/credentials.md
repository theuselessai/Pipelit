# Credentials

Endpoints for managing credentials (LLM providers, Telegram bots, Git repositories, tool configs). Credentials are global -- any authenticated user can access them. Sensitive fields (API keys, tokens) are masked in responses.

All endpoints are under `/api/v1/credentials/` and require Bearer token authentication.

---

## Credential Types

| Type       | Description | Detail Fields |
|------------|-------------|---------------|
| `llm`      | LLM provider API key | `provider_type`, `api_key`, `base_url`, `organization_id`, `custom_headers` |
| `telegram` | Telegram bot token | `bot_token`, `allowed_user_ids` |
| `git`      | Git repository credential | `provider`, `credential_type`, `username`, `ssh_private_key`, `access_token` |
| `tool`     | Tool-specific credential | `tool_type`, `config` |

---

## GET /api/v1/credentials/

List all credentials. API keys and tokens are masked in responses.

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit`   | int  | 50      | Max items per page |
| `offset`  | int  | 0       | Items to skip |

**Example request:**

```bash
curl http://localhost:8000/api/v1/credentials/ \
  -H "Authorization: Bearer <api_key>"
```

**Response (200):**

```json
{
  "items": [
    {
      "id": 1,
      "name": "OpenAI Production",
      "credential_type": "llm",
      "detail": {
        "provider_type": "openai_compatible",
        "api_key": "sk-p****ab12",
        "base_url": "https://api.openai.com/v1",
        "organization_id": "",
        "custom_headers": {}
      },
      "created_at": "2025-01-15T10:30:00",
      "updated_at": "2025-01-15T10:30:00"
    },
    {
      "id": 2,
      "name": "My Telegram Bot",
      "credential_type": "telegram",
      "detail": {
        "bot_token": "1234****6789",
        "allowed_user_ids": "123456789"
      },
      "created_at": "2025-01-15T11:00:00",
      "updated_at": "2025-01-15T11:00:00"
    }
  ],
  "total": 2
}
```

---

## POST /api/v1/credentials/

Create a new credential.

**Request body:**

| Field             | Type   | Required | Description |
|-------------------|--------|----------|-------------|
| `name`            | string | yes      | Display name |
| `credential_type` | string | yes      | One of: `llm`, `telegram`, `git`, `tool` |
| `detail`          | object | no       | Type-specific configuration (see below) |

### LLM Detail Fields

| Field             | Type   | Default              | Description |
|-------------------|--------|----------------------|-------------|
| `provider_type`   | string | `"openai_compatible"` | `"openai_compatible"` or `"anthropic"` |
| `api_key`         | string | `""`                 | API key |
| `base_url`        | string | `""`                 | API base URL (required for non-standard providers) |
| `organization_id` | string | `""`                 | Organization ID (OpenAI) |
| `custom_headers`  | object | `{}`                 | Custom HTTP headers |

### Telegram Detail Fields

| Field              | Type   | Default | Description |
|--------------------|--------|---------|-------------|
| `bot_token`        | string | `""`    | Telegram bot token from BotFather |
| `allowed_user_ids` | string | `""`    | Comma-separated allowed Telegram user IDs |

### Git Detail Fields

| Field             | Type   | Default    | Description |
|-------------------|--------|------------|-------------|
| `provider`        | string | `"github"` | Git provider (`github`, `gitlab`, etc.) |
| `credential_type` | string | `"token"`  | Auth method (`token`, `ssh`) |
| `username`        | string | `""`       | Git username |
| `ssh_private_key` | string | `""`       | SSH private key (for SSH auth) |
| `access_token`    | string | `""`       | Access token (for token auth) |
| `webhook_secret`  | string | `""`       | Webhook secret for verifying payloads |

### Tool Detail Fields

| Field       | Type   | Default  | Description |
|-------------|--------|----------|-------------|
| `tool_type` | string | `"api"`  | Tool type identifier |
| `config`    | object | `{}`     | Tool-specific configuration |

**Example request -- LLM credential:**

```bash
curl -X POST http://localhost:8000/api/v1/credentials/ \
  -H "Authorization: Bearer <api_key>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "OpenAI Production",
    "credential_type": "llm",
    "detail": {
      "provider_type": "openai_compatible",
      "api_key": "sk-proj-abc123...",
      "base_url": "https://api.openai.com/v1"
    }
  }'
```

**Response (201):** Credential object (API key masked in response).

---

## GET /api/v1/credentials/{credential_id}/

Get a single credential by ID.

**Path parameters:**

| Parameter       | Type | Description |
|-----------------|------|-------------|
| `credential_id` | int  | Credential ID |

**Example request:**

```bash
curl http://localhost:8000/api/v1/credentials/1/ \
  -H "Authorization: Bearer <api_key>"
```

**Response (200):** Credential object.

**Error (404):** `"Credential not found."`

---

## PATCH /api/v1/credentials/{credential_id}/

Update a credential. Only include fields you want to change.

**Path parameters:**

| Parameter       | Type | Description |
|-----------------|------|-------------|
| `credential_id` | int  | Credential ID |

**Request body:**

| Field    | Type   | Required | Description |
|----------|--------|----------|-------------|
| `name`   | string | no       | New display name |
| `detail` | object | no       | Updated type-specific fields |

**Example request:**

```bash
curl -X PATCH http://localhost:8000/api/v1/credentials/1/ \
  -H "Authorization: Bearer <api_key>" \
  -H "Content-Type: application/json" \
  -d '{
    "detail": {
      "api_key": "sk-proj-new-key-abc123..."
    }
  }'
```

**Response (200):** Updated credential object.

**Error (404):** `"Credential not found."`

---

## DELETE /api/v1/credentials/{credential_id}/

Delete a credential.

**Path parameters:**

| Parameter       | Type | Description |
|-----------------|------|-------------|
| `credential_id` | int  | Credential ID |

**Example request:**

```bash
curl -X DELETE http://localhost:8000/api/v1/credentials/1/ \
  -H "Authorization: Bearer <api_key>"
```

**Response (204):** No content.

**Error (404):** `"Credential not found."`

---

## POST /api/v1/credentials/batch-delete/

Batch delete multiple credentials.

**Request body:**

| Field | Type  | Required | Description |
|-------|-------|----------|-------------|
| `ids` | int[] | yes      | List of credential IDs to delete |

**Example request:**

```bash
curl -X POST http://localhost:8000/api/v1/credentials/batch-delete/ \
  -H "Authorization: Bearer <api_key>" \
  -H "Content-Type: application/json" \
  -d '{"ids": [1, 2, 3]}'
```

**Response (204):** No content.

---

## POST /api/v1/credentials/{credential_id}/test/

Test an LLM credential by making a minimal API call to verify the key works.

**Path parameters:**

| Parameter       | Type | Description |
|-----------------|------|-------------|
| `credential_id` | int  | Credential ID (must be type `llm`) |

**Example request:**

```bash
curl -X POST http://localhost:8000/api/v1/credentials/1/test/ \
  -H "Authorization: Bearer <api_key>"
```

**Response (200) -- success:**

```json
{
  "ok": true,
  "error": ""
}
```

**Response (200) -- failure:**

```json
{
  "ok": false,
  "error": "Authentication failed - invalid API key"
}
```

**Error (404):** `"LLM credential not found."`

---

## GET /api/v1/credentials/{credential_id}/models/

List available models for an LLM credential. For Anthropic credentials, returns a curated list. For OpenAI-compatible providers, queries the `/models` endpoint.

**Path parameters:**

| Parameter       | Type | Description |
|-----------------|------|-------------|
| `credential_id` | int  | Credential ID (must be type `llm`) |

**Example request:**

```bash
curl http://localhost:8000/api/v1/credentials/1/models/ \
  -H "Authorization: Bearer <api_key>"
```

**Response (200):**

```json
[
  {"id": "gpt-4o", "name": "gpt-4o"},
  {"id": "gpt-4o-mini", "name": "gpt-4o-mini"},
  {"id": "gpt-3.5-turbo", "name": "gpt-3.5-turbo"}
]
```

**Error (404):** `"LLM credential not found."`

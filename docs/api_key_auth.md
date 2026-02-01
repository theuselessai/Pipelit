# API Key Authentication

> Bearer token authentication for the Platform REST API

---

## Overview

API key authentication allows clients to authenticate with the Platform API using a Bearer token instead of session cookies. Each Django User gets a single API key (UUID), obtained by exchanging username/password credentials.

## How It Works

1. Client sends username + password to the public token endpoint
2. Server validates credentials, generates (or regenerates) a UUID API key
3. Client uses the key as a `Bearer` token in the `Authorization` header

## Obtaining a Token

```
POST /api/v1/auth/token/
Content-Type: application/json

{"username": "myuser", "password": "mypassword"}
```

Response (`200`):
```json
{"key": "3c73550a-c566-4467-b642-be625f6f4bb6"}
```

Response (`401`) — invalid credentials:
```json
{"detail": "Invalid credentials."}
```

**Note:** Calling this endpoint again regenerates the key and invalidates the previous one.

## Using the Token

Pass the key as a Bearer token on any protected endpoint:

```bash
curl -H "Authorization: Bearer 3c73550a-c566-4467-b642-be625f6f4bb6" \
     http://localhost:8000/api/v1/workflows/
```

## Authentication Backends

The API accepts these auth methods (first match wins):

| Backend | Method | Header / Cookie |
|---------|--------|-----------------|
| **SessionAuth** | Django session cookie | `sessionid` cookie |
| **BearerAuth** | API key (UUID) | `Authorization: Bearer <key>` |

## Model

`APIKey` in `apps/users/models.py`:

| Field | Type | Description |
|-------|------|-------------|
| `user` | OneToOneField → User | The Django user this key belongs to |
| `key` | UUIDField | Auto-generated UUID, unique |
| `created_at` | DateTimeField | Auto-set on creation |

## Files

| File | Role |
|------|------|
| `apps/users/models.py` | `APIKey` model |
| `apps/workflows/api/auth.py` | `SessionAuth` + `BearerAuth` backends |
| `apps/workflows/api/auth_views.py` | `POST /auth/token/` endpoint |
| `apps/workflows/api/__init__.py` | Wires auth router into the API |

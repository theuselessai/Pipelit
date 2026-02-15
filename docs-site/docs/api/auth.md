# Authentication

Authentication endpoints for login, user info, initial setup, and multi-factor authentication (MFA).

All endpoints are under `/api/v1/auth/`.

---

## POST /api/v1/auth/token/

Authenticate with username and password. Returns an API key for subsequent Bearer token auth.

If MFA is enabled on the account, the response returns `requires_mfa: true` with an empty key. The client must then call [POST /api/v1/auth/mfa/login-verify/](#post-apiv1authmfalogin-verify) to complete authentication.

**Authentication:** None required.

**Request body:**

| Field      | Type   | Required | Description |
|------------|--------|----------|-------------|
| `username` | string | yes      | Username    |
| `password` | string | yes      | Password    |

**Example request:**

```bash
curl -X POST http://localhost:8000/api/v1/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "secret"}'
```

**Response (200) -- no MFA:**

```json
{
  "key": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "requires_mfa": false
}
```

**Response (200) -- MFA enabled:**

```json
{
  "key": "",
  "requires_mfa": true
}
```

**Error (401):**

```json
{
  "detail": "Invalid credentials."
}
```

---

## GET /api/v1/auth/me/

Return the currently authenticated user's profile information.

**Authentication:** Bearer token required.

**Example request:**

```bash
curl http://localhost:8000/api/v1/auth/me/ \
  -H "Authorization: Bearer <api_key>"
```

**Response (200):**

```json
{
  "username": "admin",
  "mfa_enabled": false
}
```

---

## GET /api/v1/auth/setup-status/

Check whether the platform needs initial setup (i.e., no users exist yet).

**Authentication:** None required.

**Example request:**

```bash
curl http://localhost:8000/api/v1/auth/setup-status/
```

**Response (200):**

```json
{
  "needs_setup": true
}
```

---

## POST /api/v1/auth/setup/

Create the first admin user. This endpoint only works when no users exist in the database.

**Authentication:** None required.

**Request body:**

| Field      | Type   | Required | Description |
|------------|--------|----------|-------------|
| `username` | string | yes      | Admin username |
| `password` | string | yes      | Admin password |

**Example request:**

```bash
curl -X POST http://localhost:8000/api/v1/auth/setup/ \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "mypassword"}'
```

**Response (200):**

```json
{
  "key": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "requires_mfa": false
}
```

**Error (409):**

```json
{
  "detail": "Setup already completed."
}
```

---

## MFA Endpoints

Multi-factor authentication (MFA) uses TOTP (Time-based One-Time Passwords). Users can set up MFA with any TOTP-compatible authenticator app.

### POST /api/v1/auth/mfa/setup/

Generate a TOTP secret for the current user. Does **not** enable MFA until verified.

**Authentication:** Bearer token required.

**Response (200):**

```json
{
  "secret": "JBSWY3DPEHPK3PXP",
  "provisioning_uri": "otpauth://totp/Pipelit:admin?secret=JBSWY3DPEHPK3PXP&issuer=Pipelit"
}
```

**Error (400):** `"MFA is already enabled."`

---

### POST /api/v1/auth/mfa/verify/

Verify a TOTP code and enable MFA on the account.

**Authentication:** Bearer token required.

**Request body:**

| Field  | Type   | Required | Description |
|--------|--------|----------|-------------|
| `code` | string | yes      | 6-digit TOTP code |

**Example request:**

```bash
curl -X POST http://localhost:8000/api/v1/auth/mfa/verify/ \
  -H "Authorization: Bearer <api_key>" \
  -H "Content-Type: application/json" \
  -d '{"code": "123456"}'
```

**Response (200):**

```json
{
  "mfa_enabled": true
}
```

---

### POST /api/v1/auth/mfa/disable/

Disable MFA after verifying a TOTP code.

**Authentication:** Bearer token required.

**Request body:**

| Field  | Type   | Required | Description |
|--------|--------|----------|-------------|
| `code` | string | yes      | 6-digit TOTP code |

**Response (200):**

```json
{
  "mfa_enabled": false
}
```

---

### GET /api/v1/auth/mfa/status/

Return current MFA status for the authenticated user.

**Authentication:** Bearer token required.

**Response (200):**

```json
{
  "mfa_enabled": false
}
```

---

### POST /api/v1/auth/mfa/login-verify/

Complete MFA login. Called after `POST /token/` returns `requires_mfa: true`.

**Authentication:** None required.

**Request body:**

| Field      | Type   | Required | Description |
|------------|--------|----------|-------------|
| `username` | string | yes      | Username    |
| `code`     | string | yes      | 6-digit TOTP code |

**Example request:**

```bash
curl -X POST http://localhost:8000/api/v1/auth/mfa/login-verify/ \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "code": "123456"}'
```

**Response (200):**

```json
{
  "key": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "requires_mfa": false
}
```

**Error (401):** `"Invalid credentials."` or `"Invalid TOTP code."`

---

### POST /api/v1/auth/mfa/reset/

Emergency MFA reset. Only allowed from loopback addresses (127.0.0.1, ::1, localhost).

**Authentication:** Bearer token required.

**Response (200):**

```json
{
  "mfa_enabled": false
}
```

**Error (403):** `"MFA reset only allowed from localhost."`

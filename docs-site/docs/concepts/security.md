# Security

Pipelit includes multiple layers of security for authentication, authorization, credential management, and agent identity verification.

## Authentication

All API endpoints require **Bearer token authentication**:

```
Authorization: Bearer <api-key>
```

API keys are generated per user and stored hashed in the database. There is no session-based auth, no OAuth, and no basic auth.

!!! warning "No Default API Key"
    API keys are created during CLI setup or via the admin interface. There are no hardcoded or default keys.

## Role-Based Access Control (RBAC)

Pipelit has two roles:

| Role | Description |
|------|-------------|
| **admin** | Full access to all resources. Can manage users, assign roles, and access admin-only endpoints. |
| **normal** | Standard access. Can create and manage workflows, credentials, and executions. Cannot manage other users. |

The first user created via `python -m cli setup` is always assigned the **admin** role.

### Admin-Only Operations

The following operations require the `admin` role:

- Creating, updating, and deleting user accounts
- Changing user roles
- Managing API keys for other users

All other operations (workflows, credentials, executions, schedules, memory) are available to both roles.

### Last-Admin Protection

Pipelit prevents you from demoting or deleting the last admin user. There must always be at least one admin account.

## Multi-Key API System

Each user can have multiple API keys with different purposes:

| Field | Description |
|-------|-------------|
| `name` | Descriptive label (e.g., `github-ci`, `dev-session`) |
| `prefix` | First 8 characters, shown in the UI for identification |
| `expires_at` | Optional expiration timestamp |
| `is_active` | Can be revoked without deletion |
| `last_used_at` | Tracks when the key was last used |

API keys are shown in full only at creation time. After that, only the prefix is visible.

### Self-Service Key Management

Any authenticated user can manage their own keys:

- `POST /api/v1/users/me/keys` — Create a new API key
- `GET /api/v1/users/me/keys` — List your API keys
- `DELETE /api/v1/users/me/keys/{key_id}` — Revoke a key

Admins can also manage keys for other users via `/api/v1/users/{user_id}/keys`.

## Credential Encryption

Sensitive credential data (LLM provider API keys, gateway tokens, etc.) is encrypted at rest using **Fernet symmetric encryption**:

- Encryption key configured via `FIELD_ENCRYPTION_KEY` environment variable
- Uses `EncryptedString` SQLAlchemy column type
- Credentials are decrypted only when needed for execution
- API responses mask sensitive fields (show only last 4 characters)

!!! danger "Protect Your Encryption Key"
    If you lose the `FIELD_ENCRYPTION_KEY`, all stored credentials become unrecoverable. Back it up securely.

## TOTP-Based MFA

Pipelit supports **Time-based One-Time Password (TOTP)** for multi-factor authentication:

- Standard TOTP compatible with authenticator apps (Google Authenticator, Authy, etc.)
- Rate limiting on failed attempts
- Account lockout after repeated failures

## Agent Identity Verification

When agents communicate with each other (e.g., via `spawn_and_await`), they can verify identity using TOTP:

- Each agent user has a TOTP secret
- The `get_totp_code` tool retrieves the current code
- Receiving agents can verify the code to confirm the sender's identity
- Prevents unauthorized agent impersonation

## Credential Scope

Credentials are **global** — any authenticated user can use any credential for workflow execution. The `user_profile` field on credentials tracks who created them, not ownership.

## Agent Users

Agent users are special accounts created for automated operations:

- Created without passwords (API key only) via `create_agent_user`
- Separate API keys from the owner's personal key
- Used for agent-to-agent communication and self-modification

!!! tip "Best Practice"
    Never use your personal API key for agent operations. Always create separate agent users with their own API keys.

## Sandboxed Code Execution

Agent shell commands run inside an OS-level sandbox that isolates each workspace from the host filesystem, environment variables, and network. The sandbox uses bubblewrap (`bwrap`) on Linux with an Alpine rootfs, or container-level isolation when running inside Docker/Kubernetes.

If no sandbox is available, **execution is refused** — Pipelit does not fall back to unsandboxed execution.

Key protections:

- **Filesystem isolation** — agents can only read/write their workspace directory and `/tmp`
- **Environment scrubbing** — host secrets in environment variables are not visible
- **Network control** — network access is configurable per workspace
- **Process namespace** — agents cannot see host processes

See [Sandbox](sandbox.md) for the full architecture, detection logic, and configuration.

## Security Checklist

| Item | Development | Production |
|------|------------|------------|
| `FIELD_ENCRYPTION_KEY` | Generate any key | Generate and securely store |
| `SECRET_KEY` | Default OK | Must change |
| `CORS_ALLOW_ALL_ORIGINS` | `true` OK | Set to `false` |
| `DEBUG` | `true` OK | Must be `false` |
| HTTPS | Not required | Required |
| Redis auth | Not required | Enable `requirepass` |
| Bubblewrap | Must be installed | Must be installed (or run in container) |

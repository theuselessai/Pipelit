# Security

Pipelit includes multiple layers of security for authentication, credential management, and agent identity verification.

## Authentication

All API endpoints require **Bearer token authentication**:

```
Authorization: Bearer <api-key>
```

API keys are generated per user and stored hashed in the database. There is no session-based auth, no OAuth, and no basic auth.

!!! warning "No Default API Key"
    API keys are created during user setup or via the admin interface. There are no hardcoded or default keys.

## Credential Encryption

Sensitive credential data (LLM provider API keys, Telegram bot tokens, etc.) is encrypted at rest using **Fernet symmetric encryption**:

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

## Security Checklist

| Item | Development | Production |
|------|------------|------------|
| `FIELD_ENCRYPTION_KEY` | Generate any key | Generate and securely store |
| `SECRET_KEY` | Default OK | Must change |
| `CORS_ALLOW_ALL_ORIGINS` | `true` OK | Set to `false` |
| `DEBUG` | `true` OK | Must be `false` |
| HTTPS | Not required | Required |
| Redis auth | Not required | Enable `requirepass` |

# Gateway Architecture — Final Design

**Date:** 2026-03-22
**Status:** Design complete
**Context:** Design session on MCP hosting, credential security, adapter refactoring, and agentgateway adoption
**Supersedes:** gateway-mcp-design.v1.md (iterative design notes)

---

## Executive Summary

The plit gateway stack splits into two components:

- **agentgateway** (Linux Foundation, Rust, Apache 2.0) — owns ALL external credentials, LLM proxy, MCP server federation, RBAC enforcement via CEL policies. This is the **trust boundary**. No credential ever leaves this process.
- **plit-gw** (our Rust code) — identity provider (issues JWTs), adapter poll loops (inbound triggers), backend routing (Pipelit/OpenCode), message normalization. Thin orchestrator.

Backends (Pipelit, OpenCode, future) hold ZERO real external keys. They authenticate to agentgateway with JWTs. An LLM agent cannot leak what doesn't exist in its environment.

---

## Security Model: Gateway as Trust Boundary

### The Core Principle

**Credentials never leave agentgateway.** Agents and workflows interact with external services through agentgateway's MCP and LLM endpoints. They never hold tokens directly. This prevents LLM agents from accidentally leaking secrets in outputs, tool calls, error messages, or prompts sent to LLM providers.

```
┌─────────────────────────────────────────────────────────┐
│                    TRUST BOUNDARY                        │
│                                                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │              PLIT GATEWAY                         │    │
│  │                                                   │    │
│  │  Credentials: never leave this boundary           │    │
│  │  MCP servers: run inside this boundary            │    │
│  │  Secrets: encrypted at rest, in memory at runtime │    │
│  │                                                   │    │
│  │  External calls happen HERE:                      │    │
│  │    Slack API  ← MCP server ← gateway              │    │
│  │    Gmail API  ← MCP server ← gateway              │    │
│  │    Discord    ← MCP server ← gateway              │    │
│  │    Postgres   ← MCP server ← gateway              │    │
│  │                                                   │    │
│  └──────────────────────┬────────────────────────────┘    │
│                         │                                 │
│           Authenticated API only                          │
│           (role-based, capabilities not secrets)          │
│                                                          │
└─────────────────────────┼────────────────────────────────┘
                          │
              ┌───────────▼───────────┐
              │  Pipelit / Agents     │
              │                       │
              │  "send to #general"   │
              │  "read my inbox"      │
              │  "query postgres"     │
              │                       │
              │  Never sees tokens.   │
              │  Just makes requests. │
              └───────────────────────┘
```

### Why agentgateway, Not a Secrets Store (Vault/OpenBao)?

Vault/OpenBao are **secrets delivery services** — they hand out plaintext secrets to authorized clients. The secret leaves the boundary. An agent that reads a Slack token from Vault has that token in its LLM context and could leak it.

agentgateway is a **secrets usage service** — like Fireblocks for integrations. It holds credentials and performs operations on behalf of callers. Callers get results, never tokens. Credentials never leave the process.

| | Secrets delivery (Vault) | Secrets usage (agentgateway) |
|---|---|---|
| Agent gets | The actual token | A capability to act |
| LLM context contains | `xoxb-1234-secret...` | `"you can send Slack messages"` |
| If agent leaks output | Token is exposed | Nothing sensitive |
| Revocation | Rotate the leaked token | Revoke the agent's JWT |

### What Exists in Each Process

```
Backend processes (Pipelit, OpenCode, agents, sandboxes):
  ✅ JWTs issued by plit-gw (identify the user/agent)
  ✅ agentgateway URL
  ❌ No LLM API keys
  ❌ No Slack/Discord/Gmail tokens
  ❌ No database connection strings
  ❌ No OAuth tokens
  → An LLM/agent cannot leak what doesn't exist in its environment

agentgateway process (trust boundary):
  🔒 All LLM API keys (Anthropic, OpenAI, Ollama, etc.)
  🔒 All integration tokens (Slack, Discord, Gmail, etc.)
  🔒 All database credentials
  🔒 All OAuth tokens + refresh tokens
  🔒 Managed in agentgateway's own config/credential store
  🔒 Never exposed via any API response
```

### Gateway APIs

The gateway exposes three API surfaces — **capability API**, **LLM proxy**, and **admin API**:

#### Integration Capability API

Exposes **actions**, not credentials:

```
POST /api/v1/integrations/{integration}/tools/{tool}
  Authorization: Bearer <gateway-token>
  Body: { ...tool parameters... }

Examples:

POST /api/v1/integrations/slack/tools/send_message
  Body: { channel: "#general", text: "hello" }

GET /api/v1/integrations/slack/tools/conversations_history
  Body: { channel: "#general", limit: 10 }

POST /api/v1/integrations/gmail/tools/send_email
  Body: { to: "user@example.com", subject: "hi", body: "..." }

POST /api/v1/integrations/postgres/tools/execute_sql
  Body: { source_id: "production", query: "SELECT * FROM users LIMIT 10" }
```

#### LLM Proxy (OpenAI-Compatible)

Backends point their LLM clients at the gateway instead of real providers:

```
POST /api/v1/llm/v1/chat/completions
  Authorization: Bearer <gateway-token>
  Body: { model: "claude-sonnet-4-20250514", messages: [...] }

Gateway:
  1. Resolve gateway token → identity
  2. Check: does identity have llm access? Which models?
  3. Look up real LLM API key from encrypted credential store
  4. Proxy request to real provider (Anthropic, OpenAI, Ollama)
  5. Return response
  6. Log usage (tokens, cost) per identity
```

Backend configuration becomes trivial — no real API keys:
```
# Pipelit config (no real keys!)
LLM_BASE_URL=http://gateway:8080/api/v1/llm
LLM_API_KEY=gw-tok-aaa    # gateway token, not an LLM key

# OpenCode config (no real keys!)
providerID: "custom"
baseURL: "http://gateway:8080/api/v1/llm"
apiKey: gw-tok-bbb        # gateway token
```

This is seamless — LangChain, LiteLLM, OpenCode, any OpenAI-compatible client works without code changes. They just point at the gateway URL.

Benefits of LLM proxy:
- **Zero key exposure** — real LLM keys never exist in backend processes, agent sandboxes, or env files
- **Usage tracking** — gateway sees every LLM call, tracks tokens/cost per user
- **Budget enforcement** — per-user/per-identity spending limits
- **Model access control** — kid's token gets Haiku only, dad's gets Opus
- **Provider switching** — change Anthropic → OpenAI without touching backend config
- **Rate limiting** — centralized across all backends

#### Common Gateway Behavior

For all API surfaces, the gateway:
1. Validates the caller's gateway token
2. Resolves token → identity
3. Checks identity permissions (integration access, LLM model access)
4. Looks up the real credential from encrypted store
5. Performs the action (MCP tool call, LLM proxy)
6. Returns the result — real credentials never in the response
7. Logs usage per identity

### Gateway Identity Model (Backend-Agnostic)

The gateway has its own token-based identity. It doesn't know about Pipelit users, OpenCode sessions, or any backend's user model. Backends are just clients.

```
Gateway Token Registry (in Dragonfly):
  gw-tok-aaa → identity: "dad"
    owns: [slack-dad, gmail-dad, llm-anthropic]
    llm_models: [claude-sonnet-4-*, claude-opus-4-*]
    budget: $50/month

  gw-tok-bbb → identity: "kid"
    owns: [slack-kid]
    llm_models: [claude-haiku-*]
    budget: $5/month

  gw-tok-ccc → identity: "opencode-session"
    owns: [github-work]
    llm_models: [claude-sonnet-4-*]

  gw-tok-admin → identity: "admin"
    owns: * (all credentials)
    admin: true
```

Backends map their users to gateway tokens — how they do it is their business:

```
Pipelit:  UserProfile.gateway_token = "gw-tok-aaa"  (dad)
OpenCode: session config → gateway_token = "gw-tok-ccc"
plit CLI:  ~/.config/plit/auth.json → gateway_token = "gw-tok-admin"
```

Permission check on every capability/LLM call:
```
1. Resolve gateway token → identity
2. Does identity own this credential? (integration calls)
3. Does identity have access to this model? (LLM calls)
4. Is identity within budget? (cost enforcement)
→ Allow or deny. No knowledge of which backend called.
```

### Credential Administration

Only admin tokens can manage credentials:

```
POST   /admin/credentials             — store new credential (encrypted)
GET    /admin/credentials             — list (metadata only, no secret values)
DELETE /admin/credentials/{id}        — revoke
PATCH  /admin/credentials/{id}        — update (e.g., rotate token)
POST   /admin/credentials/{id}/test   — verify credential works
POST   /admin/identities              — create gateway identity + token
GET    /admin/identities              — list identities + their permissions
PATCH  /admin/identities/{id}         — update permissions, budget, model access
```

---

## Design Decisions

### Decision 1: MCP Server Instance Model → 1D (1:1 default, opt-in shared)

Default is one MCP server instance per credential. MCP servers that natively support multi-credential (email-mcp, dbhub) can opt into shared instances.

```json
{
  "mcp_servers": {
    "slack-workspace-a": {
      "package": "korotovsky/slack-mcp-server",
      "credential": "slack-a",
      "mode": "single"
    },
    "email": {
      "package": "codefuturist/email-mcp",
      "credentials": ["gmail-personal", "gmail-work"],
      "mode": "multi"
    }
  }
}
```

### Decision 2: Adapter ↔ MCP Relationship → 2D (Generic binary + custom)

One generic MCP adapter binary that works with any MCP server via config. Custom adapters only for protocols that need persistent connections (Telegram grammy).

```
Gateway spawns:
  generic-mcp-adapter (config: slack-mcp, poll 30s, send via send_message)
  generic-mcp-adapter (config: email-mcp, poll 60s, send via send_email)
  telegram-adapter    (custom, grammy — if needed later)
```

The generic adapter:
- Owns the poll loop (configurable interval)
- Talks to MCP server for polling + sending
- Tracks cursor/offset per source
- Normalizes MCP responses → gateway inbound protocol
- Receives /send → calls MCP send tool

### Decision 3: Credential Storage → Dragonfly + Fernet (unified config + secrets)

Two namespaces in the same Dragonfly instance:

```
Config (not encrypted, fast reads, hot-reload):
  config:slack-a:poll_interval → 30
  config:slack-a:normalize_map → {...}
  config:mcp:servers → {...}

Secrets (Fernet encrypted, read at spawn time):
  secret:slack-a:token → encrypted("xoxb-...")
  secret:gmail:oauth → encrypted({access_token, refresh_token, expiry})
  secret:postgres:dsn → encrypted("postgres://...")
```

- Fernet encryption for secret values (existing infrastructure)
- Redis ACLs for basic RBAC (admin, gateway-internal, read-only)
- Dragonfly persistence (RDB) survives restarts
- Keyspace notifications for config hot-reload
- No unseal ceremony — gateway decrypts on read with FIELD_ENCRYPTION_KEY
- redis/mcp-redis available for agent config access (config namespace only, not secrets)

**Secrets never leave the gateway process.** The gateway reads encrypted secrets from Dragonfly, decrypts in memory, injects as env vars when spawning MCP servers. No external process or API exposes plaintext credentials.

### Decision 4: Credential Setup UX → Schema-driven (4D) + Agent + CLI

Each MCP server integration publishes a credential schema:

```json
{
  "integration": "slack",
  "credential_schema": {
    "type": "token",
    "fields": {
      "bot_token": {
        "type": "string",
        "secret": true,
        "description": "Slack bot token (xoxb-...)",
        "setup_url": "https://api.slack.com/apps"
      }
    }
  }
}
```

For OAuth integrations:
```json
{
  "integration": "gmail",
  "credential_schema": {
    "type": "oauth2",
    "provider": "google",
    "scopes": ["gmail.readonly", "gmail.send"],
    "setup_url": "https://console.cloud.google.com"
  }
}
```

Any frontend renders from this schema:
- **CLI**: `plit credentials create --type slack` → prompts for fields from schema
- **Web UI**: Platform credential page → renders form from schema
- **Agent**: Reads schema, asks user conversationally, stores via admin API
- **TUI**: Renders form in terminal from schema

### Decision 5: Adapter Refactoring → 5A (Clean break)

Remove the current custom adapter protocol. Replace with:
- MCP server hosting (gateway spawns and manages MCP server processes)
- Generic MCP adapter (poll loop + MCP client + gateway inbound bridge)
- Gateway capability API (agents call integrations through gateway, not directly)

Telegram adapter is not needed currently — TUI talks to Pipelit chat directly.

---

## How Pipelit Agents Use Integrations

### Current Model (secrets exposed)

```python
# Agent has platform_api tool
# Agent reads credential, gets plaintext token
# Token is in LLM context — leak risk

@tool
def send_slack_message(channel, text):
    token = get_credential("slack-a")  # plaintext token in agent memory
    requests.post("https://slack.com/api/chat.postMessage",
                  headers={"Authorization": f"Bearer {token}"},
                  json={"channel": channel, "text": text})
```

### New Model (capabilities only)

```python
# Agent has gateway_integration tool
# Agent requests action, gateway executes with credential internally
# No token in LLM context

@tool
def gateway_call(integration, tool_name, params):
    """Call an integration tool through the gateway."""
    response = requests.post(
        f"{GATEWAY_URL}/api/v1/integrations/{integration}/tools/{tool_name}",
        headers={"Authorization": f"Bearer {AGENT_GATEWAY_TOKEN}"},
        json=params
    )
    return response.json()

# Agent calls:
gateway_call("slack", "send_message", {"channel": "#general", "text": "hello"})
# Agent never sees the Slack token
```

### Pipelit Node Types for Integrations

Integration nodes in workflows call the gateway capability API:

| Node | What it does | Gateway call |
|---|---|---|
| `trigger_slack` | Inbound messages | Adapter polls MCP via gateway |
| `send_slack` | Send message | `POST /integrations/slack/tools/send_message` |
| `query_postgres` | Run SQL | `POST /integrations/postgres/tools/execute_sql` |
| `send_email` | Send email | `POST /integrations/gmail/tools/send_email` |

All are thin wrappers around `gateway_call()`. No credentials in the workflow engine.

---

## Integration Lifecycle

### Adding a New Integration

```
1. plit mcp add slack
   → Downloads korotovsky/slack-mcp-server
   → Prompts for credential (reads schema, asks for bot token)
   → Stores encrypted credential in Dragonfly
   → Registers MCP server config in Dragonfly
   → Spawns MCP server process
   → Creates generic adapter with poll config
   → Gateway starts serving slack capabilities

2. Agent discovers:
   GET /api/v1/integrations/
   → [{ name: "slack", tools: ["send_message", "conversations_history", ...] }]

3. Agent uses:
   POST /api/v1/integrations/slack/tools/send_message
   → Gateway routes to MCP server → Slack API → result
```

### Credential Rotation

```
1. plit credentials rotate slack-a
   → Prompts for new token
   → Encrypts and stores in Dragonfly
   → Restarts MCP server with new credential
   → Zero downtime for other integrations
```

### OAuth Flow (Gmail, Microsoft 365)

```
1. plit credentials create --type gmail
   → Opens browser for Google OAuth consent
   → Captures authorization code
   → Exchanges for access_token + refresh_token
   → Encrypts and stores in Dragonfly
   → Gateway manages token refresh lifecycle
   → MCP server always has a valid token
```

---

## Implementation Phases

### Phase 1: Gateway Credential Store
- Dragonfly namespaces (config: / secret:) with Fernet encryption
- Admin credential CRUD API
- Redis ACLs for namespace isolation
- `plit credentials` CLI updates

### Phase 2: MCP Server Hosting
- Gateway spawns and manages MCP server processes
- Health monitoring, restart on failure
- Credential injection via env vars at spawn time
- `plit mcp add/remove/list` CLI commands

### Phase 3: Generic MCP Adapter
- Poll loop with configurable interval
- MCP client for tool calls
- Cursor tracking
- Normalization config (MCP response → gateway inbound format)
- Adapter process management

### Phase 4: Capability API
- `/api/v1/integrations/{integration}/tools/{tool}` endpoint
- Role-based permission checking
- Route to appropriate MCP server
- Integration discovery endpoint
- Pipelit agent tool: `gateway_call()`

### Phase 5: Credential Schema System
- Schema format for describing credential requirements
- CLI, web UI, agent, and TUI all render from schema
- OAuth flow handling for Google, Microsoft, etc.

---

## Architecture Diagram (Revised)

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                                 EXTERNAL WORLD                                   │
│  Telegram  Slack  Discord  Gmail  Postgres  GitHub  REST/Webhook  MCP Clients    │
└──────┬───────┬──────┬────────┬──────┬────────┬────────┬──────────────┬───────────┘
       │       │      │        │      │        │        │              │
       ▼       ▼      ▼        ▼      ▼        ▼        ▼              ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                                                                                  │
│                  ████████████████████████████████████████                         │
│                  █   PLIT GATEWAY  (Trust Boundary)     █                         │
│                  ████████████████████████████████████████                         │
│                                                                                  │
│  ┌─ Credential + Config Store (Dragonfly + Fernet) ───────────────────────────┐  │
│  │                                                                            │  │
│  │  secret:slack-a:token      ➜ fernet_encrypted    (read at spawn time)     │  │
│  │  secret:gmail:oauth        ➜ fernet_encrypted    (access + refresh token) │  │
│  │  secret:postgres:dsn       ➜ fernet_encrypted                             │  │
│  │  config:slack-a:poll_intv  ➜ 30                  (hot-reload via keyspace)│  │
│  │  config:slack-a:normalize  ➜ {...}               (normalization mapping)  │  │
│  │  config:mcp:servers        ➜ {...}               (registered servers)     │  │
│  │                                                                            │  │
│  │  Redis ACLs: admin (rw all), gateway (rw), pipelit (r config), agent (r)  │  │
│  │  🔒 Secrets NEVER leave this boundary                                      │  │
│  └────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                  │
│  ┌─ OAuth Refresh Manager ────────────────────────────────────────────────────┐  │
│  │  Watches: secret:*:oauth.expiry                                            │  │
│  │  When expiry < 5 min:                                                      │  │
│  │    1. Use refresh_token → call provider token endpoint                     │  │
│  │    2. Encrypt + update Dragonfly                                           │  │
│  │    3. Re-inject into running MCP server (or restart)                       │  │
│  │  Required for: Gmail, Microsoft 365, Slack OAuth                           │  │
│  └────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                  │
│  ┌─ MCP Server Processes (spawned + managed by gateway) ──────────────────────┐  │
│  │                                                                            │  │
│  │  ┌────────────────┐ ┌────────────────┐ ┌────────────────┐ ┌─────────────┐ │  │
│  │  │ Slack MCP      │ │ Email MCP      │ │ Discord MCP    │ │ Postgres MCP│ │  │
│  │  │ (workspace A)  │ │ (multi-account)│ │ (bot A)        │ │ (dbhub)     │ │  │
│  │  │                │ │                │ │                │ │             │ │  │
│  │  │ Token injected │ │ Config injected│ │ Token injected │ │ DSN injected│ │  │
│  │  │ as env var     │ │ as TOML file   │ │ as env var     │ │ as TOML     │ │  │
│  │  └───────┬────────┘ └───────┬────────┘ └───────┬────────┘ └──────┬──────┘ │  │
│  │          │ Slack API        │ IMAP/SMTP        │ Discord API     │ PG     │  │
│  │          ▼                  ▼                  ▼                 ▼        │  │
│  │     (credentials used here, inside the boundary, never exposed)           │  │
│  │                                                                            │  │
│  │  Transport: stdio servers ←→ MCP Bridge (stdio↔HTTP) ←→ internal routing  │  │
│  │             HTTP servers ←→ internal routing directly                      │  │
│  └────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                  │
│  ┌─ Generic MCP Adapters (bilateral normalization) ───────────────────────────┐  │
│  │                                                                            │  │
│  │  Each adapter is a generic binary configured per integration.              │  │
│  │  Same binary, different config. Bilateral: normalizes inbound + outbound.  │  │
│  │                                                                            │  │
│  │  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐         │  │
│  │  │ Slack Adapter     │  │ Email Adapter     │  │ Discord Adapter  │         │  │
│  │  │                   │  │                   │  │                  │         │  │
│  │  │ INBOUND:          │  │ INBOUND:          │  │ INBOUND:         │         │  │
│  │  │  poll: 30s        │  │  poll: 60s        │  │  poll: 30s       │         │  │
│  │  │  tool: convos_hist│  │  tool: list_emails│  │  tool: read_msgs │         │  │
│  │  │  cursor: date_aftr│  │  cursor: since    │  │  cursor: minId   │         │  │
│  │  │  normalize → Inbnd│  │  normalize → Inbnd│  │  normalize → Inb.│         │  │
│  │  │                   │  │                   │  │                  │         │  │
│  │  │ OUTBOUND:         │  │ OUTBOUND:         │  │ OUTBOUND:        │         │  │
│  │  │  std send request │  │  std send request │  │  std send request│         │  │
│  │  │  → add_message()  │  │  → send_email()   │  │  → discord_send()│         │  │
│  │  │  normalize params │  │  normalize params │  │  normalize params│         │  │
│  │  │                   │  │                   │  │                  │         │  │
│  │  │ talks to ↕        │  │ talks to ↕        │  │ talks to ↕       │         │  │
│  │  │ Slack MCP server  │  │ Email MCP server  │  │ Discord MCP srv  │         │  │
│  │  └────────┬──────────┘  └────────┬──────────┘  └────────┬────────┘         │  │
│  │           │                      │                      │                  │  │
│  └───────────┼──────────────────────┼──────────────────────┼──────────────────┘  │
│              │ inbound msgs         │ inbound emails       │ inbound msgs       │
│              ▼                      ▼                      ▼                    │
│  ┌─ Gateway Core Pipeline ────────────────────────────────────────────────────┐  │
│  │                                                                            │  │
│  │  Inbound:   adapter → guardrails (CEL, both directions) → route to backend│  │
│  │  Outbound:  capability API → guardrails (CEL) → adapter → MCP server      │  │
│  │                                                                            │  │
│  └──────────────────────────┬─────────────────────────────────────────────────┘  │
│                             │                                                    │
│  ┌─ Capability API ────────┼──────────────────────────────────────────────────┐  │
│  │                          │                                                 │  │
│  │  POST /api/v1/integrations/{integration}/tools/{tool}                      │  │
│  │    1. Validate caller token                                                │  │
│  │    2. Check role/permission (RBAC)                                         │  │
│  │    3. Route to adapter (outbound normalization → MCP server)               │  │
│  │    4. Return result (no secrets in response)                               │  │
│  │                                                                            │  │
│  │  GET /api/v1/integrations/                                                 │  │
│  │    → List available integrations + tools (agent discovery)                 │  │
│  │    → Auto-syncs with Pipelit node catalog on change                        │  │
│  │                                                                            │  │
│  └──────────────────────────┼─────────────────────────────────────────────────┘  │
│                             │                                                    │
│  ┌─ Response Cache (Dragonfly, TTL-based) ────────────────────────────────────┐  │
│  │  Read-heavy tools: cache 5-30s (conversations_history, list_emails)        │  │
│  │  Write tools: never cache (send_message, send_email)                       │  │
│  │  Protects against rate limits when multiple agents query same integration  │  │
│  └────────────────────────────────────────────────────────────────────────────┘  │
│                             │                                                    │
│  ┌─ Health Monitor ────────┼──────────────────────────────────────────────────┐  │
│  │  Per MCP server: ping interval, failure count, state machine              │  │
│  │  States: healthy → degraded → down → recovering                           │  │
│  │  Publishes: integration health status for TUI/UI consumption              │  │
│  │  Alerts: notify admin credentials on integration failure                  │  │
│  └──────────────────────────┼─────────────────────────────────────────────────┘  │
│                             │                                                    │
│  ┌─ Backend Routing ────────┼─────────────────────────────────────────────────┐  │
│  │  ┌─────────┐       ┌────▼────┐       ┌──────────┐                         │  │
│  │  │ Pipelit │       │ OpenCode│       │ Future   │                         │  │
│  │  │(webhook)│       │(REST+SSE│       │ backends │                         │  │
│  │  └────┬────┘       └────┬────┘       └──────────┘                         │  │
│  └───────┼─────────────────┼──────────────────────────────────────────────────┘  │
│          │                 │                                                     │
│  ┌─ Admin API ─────────────┼──────────────────────────────────────────────────┐  │
│  │  POST /admin/credentials            (store new, encrypted)                 │  │
│  │  POST /admin/mcp/add                (install MCP server package)           │  │
│  │  GET  /admin/mcp/list               (list running MCP servers + health)    │  │
│  │  POST /admin/mcp/{id}/restart       (restart MCP server)                   │  │
│  └────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                  │
└──────────┬─────────────────┬─────────────────────────────────────────────────────┘
           │                 │
           ▼                 ▼
┌──────────────────┐  ┌──────────────────┐
│  PIPELIT         │  │  OPENCODE        │
│  PLATFORM        │  │  SERVER          │
│                  │  │                  │
│  ┌────────────┐  │  │  AI-assisted     │
│  │ Workflow    │  │  │  code editing    │
│  │ Engine     │  │  │                  │
│  │            │  │  └──────────────────┘
│  │ Nodes call │  │
│  │ gateway    │  │
│  │ capability │  │
│  │ API — never│  │
│  │ hold tokens│  │
│  └──────┬─────┘  │
│         │        │
│  ┌──────▼─────┐  │
│  │ Agent      │  │
│  │ Backends   │  │
│  │            │  │
│  │ LangGraph  │  │
│  │ (current)  │  │
│  │ CC (future)│  │
│  └────────────┘  │
│                  │
│  ┌────────────┐  │
│  │ Node       │  │
│  │ Catalog    │  │
│  │            │  │
│  │ Auto-syncs │  │
│  │ from GW    │  │
│  │ integration│  │
│  │ list       │  │
│  └────────────┘  │
│                  │
└────────┬─────────┘
         │
         │ API + WebSocket
         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       USER INTERFACES                               │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Tela Situation Room                                         │   │
│  │                                                              │   │
│  │  ┌─ Graph ──────────────────┐  ┌─ Status ────────────────┐ │   │
│  │  │ live DAG visualization   │  │ Workflow: idle           │ │   │
│  │  │ algorithmic layout       │  │                          │ │   │
│  │  │ updates via WebSocket    │  │ Integrations:            │ │   │
│  │  └──────────────────────────┘  │  ✅ slack (3s ago)       │ │   │
│  │  ┌─ Chat ──────────────────────│  ✅ postgres (1s ago)    │ │   │
│  │  │ "send hello to #general"   ││  ❌ gmail (token exp.)   │ │   │
│  │  │ Agent: gateway_call(...)   ││  ⚠️  discord (slow)      │ │   │
│  │  │ → gateway handles it       │└──────────────────────────┘ │   │
│  │  │ Agent never sees token     │                              │   │
│  │  └────────────────────────────┘                              │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  PLIT CLI                                                    │   │
│  │  plit mcp add slack         Install + configure integration  │   │
│  │  plit credentials create    Store encrypted credential       │   │
│  │  plit mcp list              Running integrations + health    │   │
│  │  plit start / stop          Full stack lifecycle             │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  React SPA (maintained for casual users)                     │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Key Data Flows

**Inbound (trigger — new Slack message triggers workflow):**
```
Slack API ← Slack MCP server ← Adapter (poll, normalize) → Guardrails (CEL)
  → Gateway inbound pipeline → Pipelit backend → Workflow trigger
```

**Outbound (workflow sends Slack message):**
```
Workflow node → gateway_call("slack", "send_message", {channel, text})
  → Capability API → RBAC check → Guardrails (CEL, outbound)
  → Adapter (normalize std request → MCP tool params)
  → Slack MCP server → Slack API → result
```

**Agent mid-workflow tool call:**
```
Agent reasoning → gateway_call("postgres", "execute_sql", {query})
  → Capability API → RBAC check → Adapter (normalize) → Postgres MCP → PG → result
  (no DSN in agent context, ever)
```

**OAuth token refresh (automatic, background):**
```
OAuth Refresh Manager watches secret:gmail:oauth.expiry
  → expiry < 5 min → use refresh_token to call Google token endpoint
  → encrypt new access_token → update Dragonfly
  → re-inject into Email MCP server (restart or env update)
```

**Integration health monitoring:**
```
Health Monitor pings each MCP server on interval
  → healthy / degraded / down state machine
  → publishes status → TUI status panel shows integration health
  → on failure → alerts admin credentials
```

**Node catalog sync (new integration → available in palette):**
```
plit mcp add slack → Gateway registers Slack MCP server
  → Gateway notifies Pipelit: POST /api/v1/node-types/sync
  → Pipelit registers slack:send_message, slack:conversations_history, etc.
  → Available in node palette and workflow_discover results
```

---

## Architectural Notes

### Adapter as Bilateral Normalization Layer

The adapter is NOT just an inbound poller. It normalizes in both directions:

**Inbound:** MCP server returns Slack-specific JSON → adapter normalizes to gateway's standardized `InboundMessage` format.

**Outbound:** Capability API sends a standardized "send message" request → adapter translates to the specific MCP tool's parameter format.

Without the adapter on outbound, the capability API would need integration-specific code for every MCP server's tool signature. The adapter absorbs this complexity via normalization config:

```json
{
  "normalize_in": {
    "text": "$.text",
    "chat_id": "$.channel",
    "message_id": "$.ts",
    "from.name": "$.user"
  },
  "normalize_out": {
    "channel_id": "$.chat_id",
    "payload": "$.text",
    "content_type": "text"
  },
  "poll_tool": "conversations_history",
  "send_tool": "conversations_add_message",
  "poll_interval": "30s",
  "cursor_field": "filter_date_after"
}
```

This keeps the generic adapter binary truly generic — same code, different config per integration.

### MCP Transport Bridge

Most MCP servers default to stdio (JSON-RPC over stdin/stdout). This is single-threaded and one-request-at-a-time. The gateway needs concurrent access.

**Solution:** The gateway includes an MCP transport bridge:
- For stdio-only servers: gateway spawns process, bridges stdio ↔ internal HTTP, queues concurrent requests
- For HTTP-capable servers: connect directly, no bridge needed

```
MCP server (stdio only) ←stdio→ [Gateway MCP Bridge] ←→ internal routing
MCP server (HTTP native) ←HTTP→ internal routing directly
```

Server capability is detected at spawn time from the MCP server's manifest or transport config.

### Response Cache

Multiple agents or workflows querying the same integration (e.g., "what's in #general?") would result in duplicate external API calls, risking rate limits.

**Solution:** TTL-based response cache in Dragonfly:
- **Read tools** (conversations_history, list_emails, execute_sql): cache 5-30 seconds, configurable per tool
- **Write tools** (send_message, send_email): never cached
- **Cache key**: `cache:{integration}:{tool}:{hash(params)}`
- Cache invalidated on outbound write to same integration

### Integration Health in Status Panel

The Tela situation room surfaces integration health alongside workflow status:

```
Integrations:
  ✅ slack       — last poll 3s ago, 0 errors
  ✅ postgres    — last query 1s ago, 0 errors
  ❌ gmail       — token expired, refresh failed 2 min ago
  ⚠️  discord     — responding slowly (avg 2.1s, threshold 1s)
```

Health data published via WebSocket alongside existing workflow execution events.

---

## Open Questions

1. **MCP server packaging**: How are MCP servers distributed and installed? npm packages? Docker images? Binary downloads? `plit mcp add` needs to know how to fetch and run them. May need a registry or manifest format.

2. **Integration discovery protocol**: Should the gateway expose available integrations as MCP tools themselves? That would let agents discover capabilities via the same MCP protocol they use for everything else — a meta-MCP layer.

3. **Rate limiting strategy**: If multiple agents call the same Slack integration, who manages rate limits? Options: gateway-level rate limiter (centralized, per-integration), MCP server handles it (inconsistent across servers), or adapter manages it (per-adapter config).

4. **Multi-tenant credential isolation**: In SaaS, different users own different credentials. The RBAC needs to scope not just by integration but by user/org. This requires extending the capability API's permission model beyond flat roles.

5. **Adapter process model**: The generic adapter binary adds processes. Could the gateway run poll loops + normalization natively in Rust, eliminating adapter processes entirely? Trade-off: more gateway complexity vs fewer processes. For now, separate processes are simpler and more modular.

6. **Node catalog sync mechanism**: Push (gateway notifies Pipelit on change) vs pull (Pipelit polls gateway's integration list)? Push is more responsive but requires gateway-to-Pipelit callback. Pull is simpler but has latency.

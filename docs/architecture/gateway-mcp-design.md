# Gateway Architecture — Final Design

**Date:** 2026-03-22
**Status:** Design complete
**Context:** Design session on MCP hosting, credential security, adapter refactoring, and agentgateway adoption
**Previous iterations:** gateway-mcp-design.v1.md, gateway-mcp-design.v2-iterative.md

---

## Executive Summary

The plit gateway stack splits into two components:

- **agentgateway** ([Linux Foundation, Rust, Apache 2.0](https://github.com/agentgateway/agentgateway), 2,100+ stars) — owns ALL external credentials (LLM keys, integration tokens, OAuth), LLM proxy with provider translation, MCP server federation, CEL-based RBAC enforcement, prompt guards, budget/spend controls. This is the **trust boundary**.
- **plit-gw** (our Rust code) — identity provider (issues JWTs), adapter poll loops (inbound triggers), backend routing (Pipelit/OpenCode), message normalization. Thin orchestrator.

Backends (Pipelit, OpenCode, future) hold ZERO real external keys. They authenticate to agentgateway with JWTs issued by plit-gw. An LLM agent cannot leak what doesn't exist in its environment.

---

## Security Model: agentgateway as Trust Boundary

### Core Principle

**No credential ever leaves agentgateway.** Agents interact with external services (Slack, Gmail, LLM providers) through agentgateway's APIs. They never hold tokens. This prevents LLM agents from leaking secrets in outputs, tool calls, error messages, or prompts.

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

### Why agentgateway, Not Vault/OpenBao?

Vault/OpenBao are **secrets delivery services** — they hand out plaintext secrets to authorized clients. The secret leaves the boundary. An agent that reads a Slack token from Vault has that token in its LLM context.

agentgateway is a **secrets usage service** — like Fireblocks for integrations. It holds credentials and performs operations on behalf of callers. Callers get results, never tokens.

| | Secrets delivery (Vault) | Secrets usage (agentgateway) |
|---|---|---|
| Agent gets | The actual token | A capability to act |
| LLM context contains | `xoxb-1234-secret...` | `"you can send Slack messages"` |
| If agent leaks output | Token is exposed | Nothing sensitive |
| Revocation | Rotate the leaked token | Revoke the agent's JWT |

---

## What agentgateway Provides

agentgateway is a single Rust binary that handles:

### LLM Proxy (multi-provider, protocol translation)

- OpenAI-compatible endpoint: `/v1/chat/completions`
- Anthropic native endpoint: `/v1/messages`
- Embeddings: `/v1/embeddings`
- Provider translation: clients speak OpenAI/Anthropic, agentgateway translates to any provider
- Supported providers: OpenAI, Anthropic, Gemini, Vertex AI, Bedrock, Azure OpenAI, any OpenAI-compatible (Ollama, vLLM, Groq, etc.)
- Model aliases: map friendly names to real model names
- Credentials stored in agentgateway's config, never exposed

Backend configuration becomes trivial:
```
# Pipelit config (no real keys!)
LLM_BASE_URL=http://agentgateway:8080/v1
LLM_API_KEY=<jwt-token>    # JWT issued by plit-gw, not an LLM key

# OpenCode config (no real keys!)
providerID: "custom"
baseURL: "http://agentgateway:8080/v1"
apiKey: <jwt-token>
```

### MCP Server Federation

- Hosts and manages multiple MCP server processes (stdio, SSE, HTTP)
- Tool aggregation: single MCP endpoint federates tools from all upstream servers
- Tool name prefixing: `slack_send_message`, `postgres_execute_sql` (avoids conflicts)
- stdio to HTTP bridging for stdio-only servers
- OpenAPI to MCP conversion: point at a REST API, get MCP tools automatically
- Config hot-reload via file watcher

### RBAC via CEL Policies

CEL (Common Expression Language) rules control who can access what:

```yaml
mcpAuthorization:
  rules:
    # Only dad can use Gmail
    - 'jwt.sub == "dad" && mcp.tool.target == "gmail"'

    # Kid can only read Slack, not send
    - 'jwt.sub == "kid" && mcp.tool.name == "conversations_history"'

    # Admin gets everything
    - 'jwt.role == "admin"'

    # Model restrictions
    # (kid can't use opus)
    - 'jwt.sub == "kid" && llm.requestModel contains "opus"'  # → deny rule
```

Available CEL variables:

| Variable | What it gives you |
|---|---|
| `jwt.sub`, `jwt.role`, `jwt.*` | User identity from JWT claims |
| `apiKey.*` | API key metadata |
| `mcp.tool.name` | Which MCP tool is being called |
| `mcp.tool.target` | Which MCP server/integration |
| `mcp.prompt.name`, `mcp.resource.name` | MCP prompts and resources |
| `llm.requestModel`, `llm.provider` | Which LLM model/provider |
| `llm.inputTokens`, `llm.outputTokens` | Token usage |
| `request.headers`, `request.path` | HTTP request details |

Key feature: **unauthorized tools are automatically filtered from `list_tools`** — users don't even see tools they can't use.

### Additional Capabilities

- **Budget/spend controls** — per-model, rate limiting
- **Prompt guards** — PII detection, content moderation (regex, OpenAI mod, Bedrock Guardrails, Google Model Armor)
- **Prompt enrichment** — prepend/append system prompts
- **A2A protocol** — Agent-to-Agent protocol support
- **Observability** — OpenTelemetry, Prometheus metrics, traces to Langfuse/LangSmith

---

## What plit-gw Provides

plit-gw handles everything agentgateway doesn't:

### Identity Provider (JWT Issuer)

plit-gw manages users/identities and issues JWTs with appropriate claims:

```
User authenticates to plit-gw → JWT minted:
  {
    sub: "kid",
    role: "family",
    integrations: ["slack"],
    models: ["claude-haiku-*"],
    budget_remaining: 5.00
  }

Client uses this JWT to call agentgateway directly.
agentgateway validates JWT → evaluates CEL rules → allow/deny.
```

plit-gw is the **policy decision point** (decides what's allowed via JWT claims).
agentgateway is the **policy enforcement point** (enforces at runtime via CEL).

### Adapter Poll Loops (Inbound Triggers)

agentgateway doesn't poll MCP servers for new messages. plit-gw's adapters handle inbound:

```
Generic MCP Adapter:
  1. Poll agentgateway's MCP endpoint on interval (30s, 60s)
  2. Track cursor/offset per source
  3. Normalize MCP response → InboundMessage format
  4. Route to backend (Pipelit webhook, OpenCode, etc.)
```

### Backend Routing

Routes inbound messages and outbound delivery to the right backend:

```
Inbound: adapter → plit-gw pipeline → Pipelit webhook / OpenCode / future
Outbound: Pipelit says "send reply" → adapter → agentgateway MCP → external
```

### Health Monitoring

- Monitors agentgateway health
- Monitors MCP server health (via agentgateway)
- Monitors backend health (Pipelit, OpenCode)
- Publishes integration health for TUI status panel
- Emergency alerts on failure

---

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                              EXTERNAL WORLD                                  │
│  Slack  Discord  Gmail  Postgres  GitHub  Anthropic  OpenAI  Ollama         │
└────┬──────┬────────┬──────┬────────┬────────┬─────────┬────────┬────────────┘
     │      │        │      │        │        │         │        │
     ▼      ▼        ▼      ▼        ▼        ▼         ▼        ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                                                                              │
│       ██████████████████████████████████████████████████████████              │
│       █  AGENTGATEWAY  (Trust Boundary — Linux Foundation, Rust) █            │
│       ██████████████████████████████████████████████████████████              │
│                                                                              │
│  ┌─ LLM Proxy ──────────────────────────────────────────────────────────┐   │
│  │  /v1/chat/completions (OpenAI)  │  /v1/messages (Anthropic native)   │   │
│  │  Provider translation: OpenAI ↔ Anthropic ↔ Bedrock ↔ Vertex ↔ etc  │   │
│  │  Model aliases  │  Budget/spend controls  │  Prompt guards + PII     │   │
│  │  🔒 Real LLM API keys stored here, never exposed                     │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─ MCP Server Federation ──────────────────────────────────────────────┐   │
│  │                                                                      │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐            │   │
│  │  │Slack MCP │  │Email MCP │  │Discord   │  │Postgres  │  + more    │   │
│  │  │(stdio)   │  │(HTTP)    │  │MCP(stdio)│  │MCP(HTTP) │            │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘            │   │
│  │                                                                      │   │
│  │  Tool aggregation + prefixing  │  stdio ↔ HTTP bridge               │   │
│  │  OpenAPI → MCP conversion      │  Config hot-reload (file watcher)  │   │
│  │  🔒 Integration tokens stored here, never exposed                    │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─ RBAC (CEL Policies) ────────────────────────────────────────────────┐   │
│  │  jwt.sub == "kid" && mcp.tool.target == "gmail"        → deny        │   │
│  │  jwt.sub == "kid" && llm.requestModel contains "opus"  → deny        │   │
│  │  jwt.role == "admin"                                    → allow all   │   │
│  │  Unauthorized tools filtered from list_tools automatically           │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─ Credential Store ───────────────────────────────────────────────────┐   │
│  │  agentgateway's own config — LLM keys, MCP server tokens, OAuth     │   │
│  │  Written by plit-gw / plit CLI → file-watched, hot-reloaded         │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└──────────────────────────────┬───────────────────────────────────────────────┘
                               │ JWT-authenticated calls
                               │
┌──────────────────────────────┼───────────────────────────────────────────────┐
│                              │                                               │
│       ┌──────────────────────▼──────────────────────┐                        │
│       │              PLIT-GW (Rust)                   │                        │
│       │           (Thin Orchestrator)                │                        │
│       │                                              │                        │
│       │  Identity: issues JWTs with claims           │                        │
│       │  Adapters: poll loops for inbound triggers   │                        │
│       │  Routing: Pipelit / OpenCode / future        │                        │
│       │  Normalization: bilateral InboundMessage     │                        │
│       │  Health: monitors all components             │                        │
│       │  Config: writes agentgateway YAML            │                        │
│       │                                              │                        │
│       └──────┬──────────────────┬────────────────────┘                        │
│              │                  │                                             │
│       ┌──────▼──────┐   ┌──────▼──────┐                                      │
│       │  Pipelit    │   │  OpenCode   │                                      │
│       │  (webhook)  │   │  (REST+SSE) │                                      │
│       └──────┬──────┘   └──────┬──────┘                                      │
│              │                  │                                             │
│       ┌──────▼──────────────────▼──────┐                                      │
│       │          Dragonfly             │                                      │
│       │  (plit-gw config, RQ queues    │                                      │
│       │   NOT credentials — those are  │                                      │
│       │   in agentgateway)             │                                      │
│       └────────────────────────────────┘                                      │
│                                                                              │
└──────────────────────────────┬───────────────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                          PIPELIT PLATFORM                                     │
│                                                                              │
│  Workflow Engine │ Agent Backends (LangGraph, CC future) │ REST API + WS     │
│                                                                              │
│  LLM calls → agentgateway URL (no real keys in env)                         │
│  MCP calls → agentgateway MCP endpoint (JWT auth)                           │
│  Integration nodes → gateway_call() → agentgateway → external               │
│                                                                              │
└──────────────────────────────┬───────────────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                          USER INTERFACES                                     │
│                                                                              │
│  ┌─ Tela Situation Room ─────────────────────────────────────────────────┐  │
│  │  Graph (live DAG) │ Status (integrations + executions) │ Chat (agent)  │  │
│  │  Agent never sees tokens — talks through agentgateway                  │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌─ PLIT CLI ─────────────────────────────────────────────────────────────┐  │
│  │  plit mcp add slack       → writes agentgateway config, hot-reloaded   │  │
│  │  plit credentials create  → stores in agentgateway config              │  │
│  │  plit start / stop        → manages full stack lifecycle               │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  React SPA (maintained for casual users)                                     │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Key Data Flows

**LLM call from agent (no real keys in backend):**
```
Agent reasoning → LLM client → POST agentgateway/v1/chat/completions (JWT auth)
  → agentgateway: validate JWT → check model access (CEL) → inject real API key
  → proxy to Anthropic/OpenAI/Ollama → return response
  → agent never sees sk-ant-... key
```

**MCP tool call from agent (no integration tokens in backend):**
```
Agent → gateway_call("slack", "send_message", {channel, text}) (JWT auth)
  → agentgateway: validate JWT → check mcp.tool.target access (CEL)
  → route to Slack MCP server (internal) → Slack API → result
  → agent never sees xoxb-... token
```

**Inbound trigger (new Slack message → workflow):**
```
plit-gw adapter polls agentgateway MCP endpoint (JWT auth)
  → agentgateway: route to Slack MCP server → conversations_history
  → adapter: normalize → plit-gw inbound pipeline → Pipelit webhook
  → workflow trigger fires
```

**Outbound delivery (workflow sends reply):**
```
Workflow node → gateway_call("slack", "send_message", {...})
  → plit-gw adapter (normalize outbound params)
  → agentgateway MCP endpoint → Slack MCP server → Slack API
```

**Credential setup:**
```
plit credentials create --type slack
  → prompts for token (schema-driven)
  → writes to agentgateway YAML config
  → agentgateway file-watcher detects change → hot-reloads
  → Slack MCP server spawned with token injected
```

**Identity + RBAC flow:**
```
User authenticates to plit-gw → JWT minted:
  { sub: "kid", role: "family", integrations: ["slack"], models: ["haiku"] }

Client calls agentgateway with JWT:
  → agentgateway validates JWT
  → CEL: mcp.tool.target == "gmail"? JWT says integrations=["slack"] → deny
  → CEL: llm.requestModel == "opus"? JWT says models=["haiku"] → deny
  → CEL: mcp.tool.target == "slack"? JWT allows → proceed
```

---

## Adapter Architecture: Bilateral Normalization

The adapter normalizes in both directions — translation layer between plit-gw's standardized message format and each MCP server's tool-specific parameters:

```json
{
  "normalize_in": { "text": "$.text", "chat_id": "$.channel" },
  "normalize_out": { "channel_id": "$.chat_id", "payload": "$.text" },
  "poll_tool": "conversations_history",
  "send_tool": "conversations_add_message",
  "poll_interval": "30s",
  "cursor_field": "filter_date_after"
}
```

Same generic adapter binary, different config per integration. Without adapters on outbound, every send call would need integration-specific code.

---

## Pipelit Agent Integration

### Current Model (secrets exposed — being replaced)

```python
@tool
def send_slack_message(channel, text):
    token = get_credential("slack-a")  # plaintext token in agent memory!
    requests.post("https://slack.com/api/chat.postMessage",
                  headers={"Authorization": f"Bearer {token}"}, ...)
```

### New Model (capabilities only — no secrets)

```python
@tool
def gateway_call(integration, tool_name, params):
    """Call an integration tool through agentgateway."""
    response = requests.post(
        f"{AGENTGATEWAY_URL}/mcp/tools/call",
        headers={"Authorization": f"Bearer {JWT_TOKEN}"},
        json={"name": f"{integration}_{tool_name}", "arguments": params}
    )
    return response.json()

# Agent calls — never sees any token:
gateway_call("slack", "send_message", {"channel": "#general", "text": "hello"})
```

---

## Design Decisions Summary

| # | Decision | Choice | Rationale |
|---|---|---|---|
| 1 | MCP instance model | 1D: 1:1 default, opt-in shared | Safe default, leverages multi-credential servers when available |
| 2 | Adapter ↔ MCP | 2D: Generic adapter binary + custom | One codebase for most, custom only for persistent connections |
| 3 | Credential storage | agentgateway owns all credentials | Trust boundary — credentials never leave, agents can't leak them |
| 4 | Credential setup UX | Schema-driven (4D) | Zero per-integration UI code, works across CLI/web/agent/TUI |
| 5 | Adapter refactoring | 5A: Clean break | Telegram not needed (TUI talks to Pipelit chat directly) |
| 6 | LLM proxy | agentgateway (built-in) | Full provider translation, Anthropic native, budget controls |
| 7 | RBAC enforcement | agentgateway CEL policies | JWT claims + CEL rules cover all access control needs |
| 8 | Identity management | plit-gw issues JWTs | Backend-agnostic, works for Pipelit/OpenCode/future backends |

---

## Implementation Phases

### Phase 1: agentgateway Integration
- Run agentgateway as sidecar alongside plit-gw
- Configure LLM backends (Anthropic, OpenAI) in agentgateway config
- Point Pipelit's LLM client at agentgateway URL
- Remove real LLM keys from Pipelit config
- Validate: agent workflows run through agentgateway LLM proxy

### Phase 2: MCP Server Setup
- Configure MCP servers in agentgateway (Slack, Postgres, etc.)
- Test MCP tool federation via agentgateway's MCP endpoint
- Write CEL policies for tool access control
- `plit mcp add` CLI writes agentgateway config

### Phase 3: Adapter Refactoring (5A clean break)
- Build generic MCP adapter binary (poll loop + bilateral normalization)
- Remove current custom adapter protocol
- Connect adapters to agentgateway's MCP endpoint
- Bilateral normalization (inbound + outbound) via config

### Phase 4: Identity + JWT
- plit-gw becomes JWT issuer
- JWT claims carry user permissions (integrations, models, budget)
- agentgateway CEL policies enforce based on JWT claims
- Per-user model access, integration access, budget enforcement

### Phase 5: Credential Schema + Setup UX
- Schema format for credential requirements per MCP server
- `plit credentials create` renders from schema
- OAuth flow handling for Google, Microsoft
- TUI/web/agent all render credential forms from schema

---

## Open Questions

1. **agentgateway process restart**: agentgateway doesn't auto-restart dead stdio MCP server processes. plit-gw health monitor needs to detect and trigger restart (by rewriting config or via agentgateway admin API if available).

2. **MCP server packaging**: How are MCP servers installed? `plit mcp add slack` needs to know how to fetch npm packages, Docker images, or binaries.

3. **OAuth token refresh**: Does agentgateway handle OAuth token rotation natively, or does plit-gw need to manage refresh cycles and update agentgateway's config?

4. **Response caching**: agentgateway may not cache MCP tool responses. For rate limit protection, plit-gw or Dragonfly may need a TTL cache layer.

5. **Node catalog sync**: When new MCP servers are added to agentgateway, Pipelit's node palette needs updating. Push (agentgateway → Pipelit webhook) or pull (Pipelit polls agentgateway's tool list)?

6. **agentgateway stability**: The project is v0.0.0 with `publish = false`. API stability not guaranteed. Pin to a specific commit/release.

---

## MCP Ecosystem Research (2026-03-22)

Available MCP servers for planned integrations:

| Integration | Best MCP Server | Stars | Cursor Support | Transport |
|---|---|---|---|---|
| Discord | `barryyip0625/mcp-discord` | 76 | `minId`/`maxId` on search | stdio + HTTP |
| Slack | `korotovsky/slack-mcp-server` | 1,470 | `filter_date_after`, cursor pagination | stdio + SSE + HTTP |
| Email | `codefuturist/email-mcp` | 21 | `since` (ISO 8601), IMAP IDLE | stdio + HTTP |
| Postgres | `bytebase/dbhub` | 2,372 | Via SQL WHERE clause | stdio + HTTP |
| GitHub | `github/github-mcp-server` | Official | Via search queries | stdio |

All are request-response only — no push/subscription. The MCP protocol has no event primitive. This is why plit-gw adapters own the poll loops.

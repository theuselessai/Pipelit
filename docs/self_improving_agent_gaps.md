# Self-Improving Agent: Gap Analysis

## 1. Current Capabilities

### What works today

- **Task registry** (`platform/schemas/node_type_defs.py`) — 23 node types registered with port definitions
- **Agent tools** — epic_tools and task_tools components give agents CRUD over epics/tasks
- **spawn_and_await** (`platform/components/spawn_and_await.py`) — agent can spawn child workflow executions and await results
- **DSL compiler** (`platform/services/dsl_compiler.py`) — YAML DSL compiles to workflow graph (nodes + edges)
- **Workflow discovery** (`platform/components/workflow_discover.py`) — agent can list/inspect available workflows
- **Self-modification** — agents can create/update nodes and edges via API, effectively editing their own workflows
- **Memory** — conversation memory via SqliteSaver checkpointer, plus memory tools (facts, episodes, procedures)
- **Epics & tasks model** — full CRUD API for epics (goals) and tasks (units of work), with dependency tracking, progress sync, and WebSocket events
- **Global epics/tasks** — any agent can see and act on any epic or task (user_profile_id retained for audit only)
- **Redis 8.0+** — RediSearch and all former Stack modules included natively, no separate redis-stack-server needed

## 2. Completed This Round

- [x] **Global epics/tasks** — removed user_profile_id query filters from API endpoints and agent tool components
- [x] **Epics/tasks frontend** — fixed missing trailing slashes in list API hooks causing 404s, epics page now loads
- [x] **Anthropic credential test** — fixed wrong model ID (`claude-haiku-3-5-20241022` → `claude-3-5-haiku-20241022`)
- [x] **Redis 8.0+ docs** — replaced deprecated redis-stack-server instructions with Redis 8 install
- [x] **gh CLI** — confirmed working, added to CLAUDE.md
- [x] **Merged branch cleanup** — deleted 21+ stale remote branches
- [x] **Fix spawn failure stuck execution** — three fixes: (1) `spawn_and_await` raises `ToolException` on child `_error` instead of returning it as tool output (prevents infinite retry loop), (2) outer exception handler propagates failure to parent via `_propagate_failure_to_parent` helper, (3) child wait timeout with 600s deadline in Redis + periodic cleanup job (`services/cleanup.py`)
- [x] **TOTP-based MFA authentication** — full implementation: backend (pyotp, encrypted TOTP secret on UserProfile, MFA service with rate limiting/lockout/replay prevention, 6 API endpoints), frontend (login MFA step, Settings page with QR code setup/disable dialogs), agent TOTP (auto-generated secrets for agent users, `get_totp_code` tool component). 27 tests passing.

## 3. Bugs to Fix

### error_handler NotImplementedError
The error handler component raises `NotImplementedError` in some code paths. This should be replaced with a proper fallback that logs the error and marks the execution as failed gracefully.

## 4. Conversational TOTP Authentication

### Problem

The current `identify_user` component parses channel-specific payloads (Telegram `from.id`, webhook `user_id`, etc.) to resolve identity. This is brittle, inelegant, and not actually authentication — it's just reading metadata from the transport layer.

The real purpose of `identify_user` is **authentication**, especially as a required gate before human-in-the-loop interruptions. When an agent asks a human to approve a dangerous action, we must verify that the person responding is who they claim to be.

### Design — a ghost asks your name

```
Agent: "Who are you?"
User:  "Aka"
Agent: "Enter your code."
User:  "483291"
Agent: (validates TOTP) → confirmed, this is Aka
```

The identity lives in the conversation, not in the transport layer. A ghost asks your name, then asks you to prove it. Pure and channel-agnostic — works identically across Telegram, web chat, webhooks, or any future channel. Same protocol for humans and agents alike — a human reads their authenticator app, an agent calls `pyotp.TOTP(secret).now()`.

### Implementation

*Backend:*
- **TOTP secret storage** — encrypted column on `UserProfile` using existing `EncryptedString` (Fernet), plus `mfa_enabled` boolean
- **API endpoints** — `POST /auth/mfa/setup/` (generate secret + QR URI), `POST /auth/mfa/verify/` (confirm setup with a code), `POST /auth/mfa/disable/` (requires valid code)
- **Agent users** — `create_agent_user` auto-generates a TOTP secret at creation time. Agent tools include `get_my_totp_code` so agents can respond to **agent-to-agent** identity challenges only (see separation below).
- **`pyotp`** — dependency for TOTP generation and validation
- **1-minute validity window** — TOTP codes use `valid_window=1` (current 30s step + previous 30s step ≈ 1 minute). This is the default and only accepted window.

*TOTP hardening:*
- **Rate limiting** — max 5 TOTP attempts per minute per user. Prevents brute-force (6-digit codes have only 1M combinations).
- **Account lockout** — after 10 consecutive failures, lock the account for 15 minutes. Require password + local access to unlock early.
- **Code reuse prevention** — track last successfully used TOTP timestamp. Reject codes that have already been used within the same time window.

*Two distinct authentication flows:*
- **Agent-to-agent identity** — agents use TOTP to prove who they are to other agents. An agent can call `get_my_totp_code` and present it. This is fine — it's identity verification, not approval.
- **Human approval gates** — when a workflow requires human approval for a dangerous action, **only a human TOTP is accepted**. An agent cannot self-approve. The identify_user node must verify that the responder is a human user (not an agent user) before accepting the code.

*identify_user node:*
- **Conversational two-turn flow** — ask nickname, ask TOTP code, validate with `pyotp`
- **Human interruption integration** — when an agent hits an approval gate, the interruption flow requires a **human** TOTP before accepting the response. Agent self-approval is rejected.
- **No channel-specific logic** — remove all Telegram/webhook/manual payload parsing from the identity flow

*Frontend — Settings page MFA section:*
- **Enable MFA** — generate TOTP secret, display QR code (`otpauth://` URI) for scanning into authenticator app
- **Verify setup** — user enters a code to confirm their app works before the secret is saved
- **Disable MFA** — requires a valid TOTP code to turn off
- **Status indicator** — show whether MFA is currently enabled

*Recovery — physical access only:*
- **TOTP reset requires password + local access** — the reset/regenerate endpoint only works from the local web interface on the host machine. No remote reset, no email recovery, no backup codes.
- This is deliberate: if you lose your authenticator, you must be physically present at the machine that hosts the platform. An agent (or remote attacker) cannot reset MFA on your behalf.
- **Network restriction** — reset endpoint restricted to loopback only (`localhost`, `127.0.0.1`, `::1`). All other addresses — including RFC 1918 private ranges (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`) — are rejected to prevent local network attacks.

## 5. Missing Capabilities

| Capability | Description | Priority |
|---|---|---|
| **Cost tracking** | Track token usage and USD cost per execution/task/epic. Fields exist on the model but are never populated by the orchestrator. | High |
| **Timeout enforcement** | No per-node or per-execution timeout. Long-running LLM calls or tool invocations can hang forever. | High |
| **Safety guardrails** | No budget enforcement (budget_tokens/budget_usd fields are decorative). No rate limiting on agent-initiated executions. | High |
| **Scheduler** | No built-in cron/interval trigger. Agents cannot schedule recurring tasks or delayed executions. | Medium |
| **DSL switch/loop** | DSL compiler does not support `switch` or `loop` node types. Agents can only build linear/branching workflows via DSL. | Medium |
| **Semantic search** | No vector/embedding-based search over epics, tasks, or workflow outputs. Agents must use exact text matching. | Low |

## 6. Bootstrap Path

Minimum steps to get a self-improving agent loop working:

1. ~~**Apply global epics/tasks**~~ — done
2. ~~**Fix spawn failure stuck execution**~~ — done (ToolException on child error, parent propagation, 600s timeout + cleanup job)
3. ~~**Implement TOTP authentication**~~ — done (MFA service, API endpoints, frontend login/settings, agent TOTP, 27 tests)
4. **Wire cost tracking** in the orchestrator — populate `spent_tokens`/`spent_usd` after each LLM call
5. **Add budget enforcement** — check `budget_tokens`/`budget_usd` before executing a task, fail early if exceeded
6. **Build an orchestrator workflow** — a meta-agent that:
   - Reads open epics/tasks
   - Picks the highest-priority unblocked task
   - Spawns a worker workflow to execute it
   - Records results and updates task status
7. **Add a scheduler trigger** — so the orchestrator runs on a cron (e.g., every 5 minutes) to check for new work
8. **DSL switch/loop support** — so agents can build more sophisticated workflows programmatically

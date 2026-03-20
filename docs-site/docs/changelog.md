# Changelog

All notable changes to Pipelit will be documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.3.14] - 2026-03-20

### Fixed

- **Auto-reply for terminal agent nodes** — When an agent or deep_agent node is terminal (no downstream executable nodes) and the workflow has no explicit `reply_chat` node, the orchestrator now auto-promotes its output to `state["output"]` so `deliver()` sends the response back via the gateway. Fixes E2E chat round-trip for the `default-agent` workflow. ([#174](https://github.com/theuselessai/Pipelit/pull/174))

---

## [0.3.12] - 2026-03-19

### Added

- **`input_template` for node input scoping** — Agent and deep_agent nodes can declare `input_template` in `extra_config` to receive a specific slice of state as their input message (e.g. `{{ scribe.output }}`), instead of inheriting the full conversation history. Enables clean parallel fan-out patterns.
- **`reply_chat` terminal node** — New component type that sends a message back to the chat caller and ends the workflow. Reads message from `system_prompt` (Jinja-resolved) with `extra_config.message` fallback. Registered in frontend Output category.
- **Node input/output debug logging** — `execution_logs.input` column now stores resolved `system_prompt` and `input_template` values per node execution for full observability.
- **Frontend: `input_template` field** — Visible in agent/deep_agent node config panel with Jinja template support.
- **Frontend: `reply_chat` node type** — Available in Output category of node palette with message field.

### Fixed

- **Parallel state race condition** — `save_state` now uses Redis `WATCH`/`MULTI` for atomic read-merge-write of `node_outputs`, preventing parallel workers from overwriting each other's outputs.
- **`_input_override` state leak** — Cleared after each node completes so downstream nodes don't inherit stale overrides.
- **Merge node type validation** — Changed merge input type from `ARRAY` to `ANY` so it can accept outputs from agent/deep_agent nodes in fan-in patterns.

---

## [0.3.11] - 2026-03-19

### Fixed

- **SPA client-side routing** -- Routes like `/login`, `/workflows` now correctly serve `index.html` instead of returning 404. Static assets and API routes are unaffected.

---

## [0.3.10] - 2026-03-19

### Added

- **Frontend serving via env var** -- `FRONTEND_DIST_PATH` env var allows serving the React SPA from a path outside the default location, fixing frontend not served in Docker when volume mounts shadow the built dist ([#170](https://github.com/theuselessai/Pipelit/pull/170))
- **Frontend E2E test** -- Smoke test now verifies the frontend is served from the root URL (section 7) ([#170](https://github.com/theuselessai/Pipelit/pull/170))
- **DSL test fixtures** -- Six topology + Gherkin behavior spec pairs covering complete agent, branching, loop/filter, memory/subworkflow, deep agent meta, and error routing scenarios ([#170](https://github.com/theuselessai/Pipelit/pull/170))

---

## [0.3.9] - 2026-03-15

### Added

- **E2E smoke test infrastructure** -- Mock LLM server and 17-assertion smoke test script for CI validation ([#159](https://github.com/theuselessai/Pipelit/pull/159))
- **User management API** -- Full CRUD for user accounts with multi-key API system. Users can have multiple named API keys with optional expiration, soft-revocation, and usage tracking ([#155](https://github.com/theuselessai/Pipelit/pull/155), [#156](https://github.com/theuselessai/Pipelit/pull/156))
- **Chat API endpoints** -- Restored `POST /workflows/{slug}/chat/` and `DELETE /workflows/{slug}/chat/history` endpoints for direct workflow chat interaction ([#154](https://github.com/theuselessai/Pipelit/pull/154))
- **RBAC (Role-Based Access Control)** -- Two roles: `admin` and `normal`. Admin-only operations include user management, role assignment, and key management for other users. Last-admin protection prevents lockout ([#142](https://github.com/theuselessai/Pipelit/pull/142))
- **CLI setup commands** -- `python -m cli setup` replaces the web-based setup wizard for initial admin account creation. `python -m cli apply-fixture` bootstraps a working workflow with LLM credentials ([#144](https://github.com/theuselessai/Pipelit/pull/144), [#146](https://github.com/theuselessai/Pipelit/pull/146))
- **Message gateway integration** -- External messaging channels (Telegram, chat clients) are now handled by the [plit message gateway](https://github.com/theuselessai/plit). Inbound messages arrive at `POST /api/v1/inbound`, responses delivered via gateway send API ([#135](https://github.com/theuselessai/Pipelit/pull/135))
- **Gateway credential type** -- New `gateway` credential type for managing gateway adapter connections, replacing direct Telegram bot token credentials
- **Gateway-mediated triggers** -- Chat and Telegram triggers now receive messages via the gateway rather than direct webhook/polling. The gateway handles bot registration, webhook setup, and message routing
- **Web search tool** -- SearXNG-powered web search tool for agents

### Changed

- **Sandbox security hardened** -- Removed unsandboxed execution fallback. If no sandbox (bubblewrap or container) is available, shell execution is **refused** with a clear error message ([#140](https://github.com/theuselessai/Pipelit/pull/140))
- **Network access enabled by default** -- Sandbox workspaces now have network access enabled by default (`--share-net`), allowing agents to use `curl`, `git`, web search, and other network tools without manual configuration ([#150](https://github.com/theuselessai/Pipelit/pull/150))
- **Deep agent AI model linking** -- `ai_model` config now properly linked to `deep_agent` via `llm_model_config_id` ([#148](https://github.com/theuselessai/Pipelit/pull/148))
- **Migration hardening** -- Fixed SQLite unnamed unique constraint issue on fresh databases ([#157](https://github.com/theuselessai/Pipelit/pull/157)), hardened downgrades for non-numeric string IDs, added missing `add_column` in rename migration ([#147](https://github.com/theuselessai/Pipelit/pull/147))
- **Credential ownership checks** -- Added ownership verification and TOCTOU race fix for credential operations

### Removed

- **Setup wizard** -- Web-based `SetupPage` removed from frontend. Initial setup now handled via CLI commands ([#144](https://github.com/theuselessai/Pipelit/pull/144))
- **Direct Telegram integration** -- Telegram webhook handler, polling mode, and `TelegramCredential` model removed. Telegram messaging now handled by the message gateway
- **Telegram poller** -- Self-rescheduling RQ-based Telegram polling job removed
- **MCP server** -- Removed unused MCP server module
- **Workflow collaborators** -- Removed collaborator model (replaced by RBAC roles)

---

## [0.1.0] - 2026-02-23

### Added

- Deep Agent node type (`deep_agent`) -- advanced agent with built-in task planning (todos), filesystem tools, and inline subagent delegation via the `deepagents` library
- Agent middleware architecture -- shared `PipelitAgentMiddleware` for tool status WebSocket events and streaming across agent types
- LangGraph v1 migration -- `create_react_agent` replaced with `create_agent`
- Real-time chat streaming -- intermediate agent LLM responses streamed to the chat panel during execution
- Dynamic Anthropic model fetching from API
- Auto-generated node IDs (`{type}_{hex}`) and node rename support on the canvas
- Documentation site with MkDocs Material
- Full component reference for all 42+ node types
- API reference documentation
- Architecture documentation with Mermaid diagrams
- Getting started guide and tutorials
- Deployment guides for Docker, production, and reverse proxy setups

---

*For the full commit history, see the [GitHub repository](https://github.com/theuselessai/Pipelit/commits/master).*

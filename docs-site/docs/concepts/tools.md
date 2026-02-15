# Tools

Tools are sub-component nodes that give agents the ability to take actions in the world -- running shell commands, making HTTP requests, searching the web, and even modifying the platform itself. Each tool is implemented as a LangChain `@tool` function that the LLM can invoke through function calling.

## How Tools Connect to Agents

Tools are **sub-component nodes** that connect to agent nodes via the green diamond **tools handle** on the agent's bottom edge:

```
                    +------------------+
                    |     Agent        |
                    |                  |
                    +--[model][tools]--+
                         |       |
                    AI Model   run_command
                               web_search
                               calculator
```

The connection uses `edge_label="tool"` on the workflow edge. At build time, the agent queries all tool edges pointing to it, loads each tool node's component factory, and registers the resulting LangChain `@tool` functions for LLM function calling.

!!! info "Multiple Tools per Agent"
    An agent can have any number of tools connected. The LLM sees all of them in its function schema and decides which to call based on the conversation context.

## Real-Time Tool Status

When an agent invokes a tool during its reasoning loop, the tool node on the canvas shows live status badges via WebSocket:

1. **Running** (spinning circle) -- tool function is executing.
2. **Success** (checkmark) -- tool completed without errors.
3. **Failed** (X) -- tool raised an exception.

This is implemented by wrapping each tool function with a status publisher that broadcasts `node_status` events to the `workflow:{slug}` WebSocket channel before and after execution.

## Built-In Utility Tools

These five tools provide general-purpose capabilities for agents:

| Tool | Component Type | Description | Config (`extra_config`) |
|------|---------------|-------------|------------------------|
| **Run Command** | `run_command` | Execute shell commands via subprocess. Returns stdout, stderr, and exit code. | `timeout` (default: 300s) |
| **HTTP Request** | `http_request` | Make HTTP requests using httpx. Returns status code and response body. | `method` (default: GET), `headers`, `timeout` (default: 30s) |
| **Web Search** | `web_search` | Search the web via a SearXNG instance. Returns top 5 results with title, URL, and snippet. | `searxng_url` (required) |
| **Calculator** | `calculator` | Safely evaluate math expressions using Python's AST parser. Supports `+`, `-`, `*`, `/`, `//`, `%`, `**`. | -- |
| **Date & Time** | `datetime` | Get the current date and time. Returns formatted timestamp. | `timezone` (optional, default: UTC) |

### Run Command

Executes arbitrary shell commands in a subprocess with configurable timeout. Output is capped at 50,000 characters (truncated from the middle if exceeded). The subprocess runs with `stdin=DEVNULL` and `start_new_session=True` for isolation.

```
Agent: "List files in the project directory"
Tool call: run_command(command="ls -la /home/user/project")
Tool result: "total 48\ndrwxr-xr-x  6 user user 4096 ..."
```

!!! warning "Security Consideration"
    `run_command` executes shell commands with the same permissions as the Pipelit process. Only connect this tool to agents in trusted environments.

### HTTP Request

Makes HTTP requests with configurable default method, headers, and timeout. The agent can override the method and provide a request body per call. Response bodies are truncated to 4,000 characters.

### Web Search

Queries a [SearXNG](https://docs.searxng.org/) metasearch engine instance. Requires a running SearXNG deployment -- configure the URL in the node's `extra_config`. Returns the top 5 results formatted as title, URL, and content snippet.

### Calculator

Uses Python's `ast` module to safely parse and evaluate mathematical expressions. Only numeric constants and basic arithmetic operators are allowed -- no function calls, variable access, or imports.

### Date & Time

Returns the current timestamp formatted as `YYYY-MM-DD HH:MM:SS TZ`. Supports any timezone from Python's `zoneinfo` module (e.g., `America/New_York`, `Europe/London`). Defaults to UTC if no timezone is configured.

## Self-Awareness Tools

These tools enable agents to introspect, manage the platform, and orchestrate other workflows. They are the building blocks for **self-improving agents** that can modify their own configuration, create new workflows, and delegate work.

| Tool | Component Type | Description |
|------|---------------|-------------|
| **Create Agent User** | `create_agent_user` | Provision API credentials (username + API key) for the agent to authenticate with the platform API. Idempotent -- returns existing credentials if already created. |
| **Platform API** | `platform_api` | Make authenticated HTTP requests to the Pipelit REST API. Agents can call any endpoint -- CRUD workflows, nodes, edges, credentials, and more. |
| **Who Am I** | `whoami` | Get the agent's identity -- workflow slug, node ID, current system prompt, and instructions for self-modification via the API. |
| **Get TOTP Code** | `get_totp_code` | Retrieve the current TOTP code for the agent's user account, used for identity verification in multi-agent scenarios. |
| **Epic Tools** | `epic_tools` | Create, query, update, and search epics for organizing multi-step task delegation. |
| **Task Tools** | `task_tools` | Create, list, update, and cancel tasks within epics. Tasks link to workflow executions for tracking. |
| **Spawn & Await** | `spawn_and_await` | Spawn a child workflow execution and pause the agent until it completes. The child's output is returned to the agent's reasoning loop. |
| **Workflow Create** | `workflow_create` | Create entire workflows programmatically from a YAML DSL specification -- triggers, nodes, edges, and configurations in one call. |
| **Workflow Discover** | `workflow_discover` | Search existing workflows by requirements. Returns scored matches with gap analysis and reuse/fork/create recommendations. |
| **Scheduler Tools** | `scheduler_tools` | Create, pause, resume, stop, and list scheduled recurring jobs for any workflow. |
| **System Health** | `system_health` | Check platform infrastructure health -- Redis connectivity, RQ worker status, queue depths, stuck executions, failed executions, and scheduled job state. |

### Create Agent User + Platform API

These two tools work together to give an agent full API access:

1. The agent calls `create_agent_user` to get an API key.
2. The agent calls `platform_api` with that API key to interact with any REST endpoint.
3. Common first call: `platform_api(path="/openapi.json")` to discover available endpoints.

!!! tip "Self-Modification Pattern"
    An agent with `whoami` + `create_agent_user` + `platform_api` can read its own configuration, modify its system prompt, add or remove tool connections, and even restructure its own workflow -- all through the standard REST API.

### Spawn & Await

This tool enables **multi-agent orchestration**. When an agent calls `spawn_and_await`:

1. The tool calls LangGraph's `interrupt()` to checkpoint the agent mid-reasoning.
2. The orchestrator creates a child `WorkflowExecution` and enqueues it on RQ.
3. The parent agent's node enters a `waiting` state.
4. When the child execution completes, its output is injected into the parent's state.
5. The parent agent resumes from the checkpoint -- `interrupt()` returns the child's output as a JSON string.

This requires either conversation memory (SqliteSaver) or an ephemeral RedisSaver checkpointer to persist the agent's state during the wait.

### Epic Tools + Task Tools

These tools provide a project management layer for agents:

- **Epics** group related tasks with optional token/USD budgets.
- **Tasks** are individual work items within an epic, each linked to a workflow execution.
- Budget enforcement happens at the orchestrator level -- if an epic's budget is exceeded, the execution fails.

### System Health

Returns a comprehensive JSON health report including:

- Redis connectivity and ping latency
- RQ worker count and status
- Queue depths (pending jobs)
- Stuck executions (running for too long)
- Recent failed executions
- Scheduled job status

## Complete Tool Reference

| Tool | Category | Input | Output |
|------|----------|-------|--------|
| `run_command` | Utility | `command: str` | stdout/stderr string |
| `http_request` | Utility | `url: str`, `method: str`, `body: str` | HTTP status + response body |
| `web_search` | Utility | `query: str` | Formatted search results |
| `calculator` | Utility | `expression: str` | Numeric result string |
| `datetime` | Utility | -- | Formatted timestamp string |
| `create_agent_user` | Self-Awareness | `purpose: str` | JSON with username, api_key, api_base_url |
| `platform_api` | Self-Awareness | `method`, `path`, `body`, `api_key`, `base_url` | JSON API response |
| `whoami` | Self-Awareness | -- | JSON with identity and self-modification instructions |
| `get_totp_code` | Self-Awareness | `username: str` | JSON with username and TOTP code |
| `epic_tools` | Self-Awareness | varies per sub-tool | JSON result from epic operations |
| `task_tools` | Self-Awareness | varies per sub-tool | JSON result from task operations |
| `spawn_and_await` | Self-Awareness | `workflow_slug`, `input_text`, `task_id`, `input_data` | JSON child workflow output |
| `workflow_create` | Self-Awareness | `dsl: str`, `tags: str` | JSON with workflow_id, slug, counts |
| `workflow_discover` | Self-Awareness | `requirements: str`, `limit: int` | JSON with matches, scores, recommendations |
| `scheduler_tools` | Self-Awareness | varies per sub-tool | JSON result from schedule operations |
| `system_health` | Self-Awareness | -- | JSON health report |

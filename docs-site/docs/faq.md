# FAQ

## General

### What is Pipelit?

Pipelit is a self-hosted visual workflow automation platform for building LLM-powered agent pipelines. You design workflows on a drag-and-drop canvas, connecting triggers, agents, tools, and routing logic, then execute them with real-time status updates.

### Is Pipelit open source?

Yes. Pipelit is released under the MIT license.

### What LLM providers are supported?

Pipelit works with any provider supported by LangChain, including OpenAI, Anthropic, Google, Mistral, Groq, and local models via Ollama or vLLM. You configure providers through the Credentials page.

### Does Pipelit require an internet connection?

Only for LLM API calls to cloud providers. If you use local models (e.g., Ollama), Pipelit can run fully offline.

---

## Setup & Installation

### Why does Pipelit require Redis 8.0+?

Redis 8.0+ includes RediSearch natively, which Pipelit uses for fuzzy search in the memory system. Older Redis versions will fail with `unknown command 'FT._LIST'`. See the [Redis setup guide](deployment/redis.md) for installation instructions.

### Can I use PostgreSQL instead of SQLite?

Yes. Set `DATABASE_URL` in your `.env` file to a PostgreSQL connection string. SQLite is the default for development; PostgreSQL is recommended for production. See [Database deployment](deployment/database.md).

### What happens if I lose my `FIELD_ENCRYPTION_KEY`?

All stored credentials (API keys, tokens) become unrecoverable. Back up this key securely.

---

## Workflows

### Can a workflow have multiple triggers?

Yes. A single workflow can have multiple trigger nodes (e.g., a chat trigger and a Telegram trigger). Each trigger scopes its own execution — only nodes reachable downstream from the firing trigger are compiled and run.

### What happens to nodes not connected to a trigger?

Unconnected nodes are ignored during execution. The builder only compiles the subgraph reachable from the firing trigger via BFS traversal. This allows you to keep unused or in-progress nodes on the canvas without causing errors.

### How do I pass data between nodes?

Nodes communicate through typed ports. Connect an output port to an input port via edges on the canvas. You can also reference upstream outputs using Jinja2 expressions (`{{ nodeId.portName }}`) in system prompts and config fields.

---

## Agents

### What is conversation memory?

When enabled on an agent node, conversation memory persists the chat history across executions using a SQLite checkpointer. The same user talking to the same workflow continues their conversation. Toggle it in the agent's config panel.

### Can agents call multiple tools?

Yes. Connect as many tool nodes as you want to an agent's "tools" handle (green diamond). The agent can invoke any connected tool during its reasoning loop.

### How do I give an agent access to the platform API?

Connect the `Platform API`, `WhoAmI`, and other self-awareness tools to the agent. These let the agent make authenticated requests to the Pipelit REST API, inspect its own identity, and modify workflows.

---

## Execution

### Why is my execution stuck in "running"?

Executions that run longer than `ZOMBIE_EXECUTION_THRESHOLD_SECONDS` (default: 15 minutes) are considered stuck. Check the [Troubleshooting](troubleshooting.md) page for diagnosis steps. Common causes include LLM API timeouts, infinite tool loops, or RQ worker crashes.

### Can I cancel a running execution?

Yes, via the API (`POST /api/v1/executions/{id}/cancel/`) or the Executions page in the UI.

### How does cost tracking work?

Pipelit automatically counts input and output tokens per execution and calculates USD costs based on model pricing. You can set token or USD budgets on Epics — the orchestrator checks the budget before each node execution.

---

## Deployment

### Can I run Pipelit in Docker?

Yes. See the [Docker deployment guide](deployment/docker.md) for Dockerfile and docker-compose.yml examples.

### Do I need a separate frontend server in production?

No. Run `npm run build` in `platform/frontend/` once, and FastAPI serves the built SPA directly. No Vite dev server needed in production.

### How do I set up WebSocket proxying?

Your reverse proxy must forward WebSocket upgrade requests. See the [Reverse Proxy guide](deployment/reverse-proxy.md) for Nginx and Caddy configurations.

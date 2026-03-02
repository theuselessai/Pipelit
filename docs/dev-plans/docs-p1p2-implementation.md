# P1 + P2 Documentation Implementation Plan

## Summary

P0 has been completed and merged (commit b61542b). The most recent commit (cb7d67f) removed skills content (pr-workflow.md, writing-skills.md) from docs-site, moving them to a standalone repo. The skills/index.md now just points to the standalone repo.

This plan covers **P1 (4 items)** and **P2 (5 items)** from the master docs-site update plan.

---

## P1 — Important (4 items)

### 1. NEW: `docs-site/docs/api/health.md`

**Current state:** File does not exist.

**Source code reference:** `platform/main.py:147-180`

The health endpoint is defined as:

```python
@app.get("/health")
def health_check():
    """Health check endpoint — no auth required."""
```

It checks Redis connectivity (`r.ping()`) and database connectivity (`SELECT 1`), returning:

```json
{
    "status": "ok" | "degraded",
    "version": "<from VERSION file>",
    "redis": true | false,
    "database": true | false
}
```

- Returns `"ok"` when both Redis and DB are healthy
- Returns `"degraded"` when either check fails
- No authentication required
- Tests exist at `platform/tests/test_health.py`

**Content outline (follow style of `api/auth.md` and `api/websocket.md`):**

```markdown
# Health Check

Health check endpoint for monitoring and load balancer probes. No authentication required.

---

## GET /health

Returns the operational status of the Pipelit backend, including Redis and database connectivity.

**Authentication:** None required.

**Example request:**

    curl http://localhost:8000/health

**Response (200) — all healthy:**

    {
      "status": "ok",
      "version": "0.2.0",
      "redis": true,
      "database": true
    }

**Response (200) — degraded:**

    {
      "status": "degraded",
      "version": "0.2.0",
      "redis": false,
      "database": true
    }

### Response Fields

| Field      | Type    | Description |
|------------|---------|-------------|
| `status`   | string  | `"ok"` if all checks pass, `"degraded"` if any check fails |
| `version`  | string  | Pipelit version from the `VERSION` file |
| `redis`    | boolean | `true` if Redis responded to `PING` |
| `database` | boolean | `true` if database responded to `SELECT 1` |

### Status Values

| Status     | Meaning |
|------------|---------|
| `ok`       | All infrastructure checks passed |
| `degraded` | One or more checks failed — the API may still serve requests but some features (e.g., background jobs, pub/sub) will be impaired |

## Usage

### Load Balancer Health Checks

Configure your load balancer to poll `/health` periodically:

    # Nginx upstream health check (requires nginx-plus or lua module)
    # Or use a simple script:
    curl -sf http://localhost:8000/health | jq -e '.status == "ok"'

### Monitoring Integration

The endpoint works with any HTTP-based monitoring tool (Uptime Kuma, Prometheus blackbox exporter, etc.). Check for `status: "ok"` or inspect individual `redis`/`database` fields for granular alerts.

### systemd Watchdog

Add a health check to your systemd unit:

    ExecStartPost=/bin/sh -c 'sleep 3 && curl -sf http://localhost:8000/health'

!!! note "Not behind authentication"
    The health endpoint is intentionally unauthenticated so load balancers and monitoring tools can probe it without API keys. It does not expose any sensitive data.
```

---

### 2. NEW: `docs-site/docs/tutorials/pr-workflow-skill.md`

**Current state:** File does not exist.

**Context:** The pr-workflow skill was documented in P0 under `docs-site/docs/skills/pr-workflow.md` but that file was removed in commit cb7d67f (skills content moved to standalone repo). The tutorial should remain in docs-site since tutorials are about *using* Pipelit, not about the skills repo itself. The tutorial references the skill from the standalone repo rather than duplicating its SKILL.md content.

**Source material:** The original SKILL.md (retrieved from git history, commit 830a978) describes a 6-step PR lifecycle workflow with 3 approval gates.

The skills/index.md now points to the standalone repo at github.com/theuselessai/skills.

**Content outline (follow style of existing tutorials like `tutorials/chat-agent.md`):**

```markdown
# End-to-End PR Workflow with Skills

<span class="badge badge--tool">Advanced</span>

Walk through using the `pr-workflow` skill with Claude Code to manage the full lifecycle of a GitHub pull request — from CI checks through code review triage to merge.

**You will learn:** Skills, Claude Code `/` commands, pr-workflow approval gates, CI analysis, review triage, coverage fixing.

**Prerequisites:**
- Claude Code installed and configured
- `gh` CLI authenticated with push access
- A Pipelit deployment with Telegram configured (for status updates)
- The `pr-workflow` skill installed from the skills repository

## What is the pr-workflow skill?

Brief description: a structured Claude Code workflow with 3 approval gates for managing PRs end-to-end. Link to the skills repo and the skills concept page.

## Step 1: Install the Skill

Instructions to clone/install the skill from the standalone skills repository into `.claude/skills/`.

## Step 2: Invoke the Skill

Show the `/pr-workflow <PR#>` invocation in Claude Code.

## Step 3: CI Status Check

Explain what happens automatically — CI polling, status summary sent via Telegram.

## Step 4: CI Fix Plan (Approval Gate 1)

Explain the approval gate pattern: analysis → .md report → Telegram notification → wait for approval. Walk through a realistic example with a failing codecov check.

## Step 5: Review Triage (Approval Gate 2)

Explain how the skill triages reviewer comments — confirmed bugs vs false positives. Show example triage report format.

## Step 6: Coverage Plan (Approval Gate 3)

Explain how uncovered lines are identified and test plans are generated. Show example coverage plan.

## Step 7: Merge

Explain the final confirmation and squash merge step.

## Key Takeaways

- Skills automate multi-step engineering workflows
- Approval gates prevent autonomous changes without review
- The pattern (analyze → report → approve → act) can be adapted to other skills

## Next Steps

- Link to skills/index.md for the skills concept overview
- Link to the standalone skills repository for the full catalog
- Link to self-improving-agent tutorial for related autonomous patterns
```

---

### 3. UPDATE: `docs-site/docs/concepts/index.md`

**Current state:** Contains 12 concept cards (Workflows, Nodes & Edges, Triggers, Agents, Tools, Expressions, Execution, Memory, Epics & Tasks, Cost Tracking, Scheduler, Security). P0 added `sandbox.md` and `providers.md` to the concepts dir and to `mkdocs.yml` nav, but did **not** add cards for them on the concepts index page.

**Exact changes needed:**

Add two new cards after the Security card (before `</div>` closing tag at line 103):

```markdown
<div class="card" markdown>

### [Sandbox](sandbox.md)

OS-level isolation for agent shell commands. bwrap namespace sandboxing with Alpine rootfs, container-mode fallback, network control, and capability detection.

</div>

<div class="card" markdown>

### [Providers](providers.md)

Multi-LLM provider support through a unified credential system. Configure OpenAI, Anthropic, MiniMax, GLM, or any OpenAI-compatible API and select models per agent.

</div>
```

Also add a Skills card linking to the skills section:

```markdown
<div class="card" markdown>

### [Skills](../skills/index.md)

Structured Claude Code workflows that automate repeatable engineering tasks. Skills encode step sequences, approval gates, and tool invocations in prompt-based SKILL.md files.

</div>
```

**Location:** Insert after the Security card (line 101), before the closing `</div>` on line 103.

---

### 4. UPDATE: `docs-site/docs/deployment/production.md`

**Current state:** The Monitoring section (lines 186-193) lists 5 bullet points for monitoring but does not mention the `/health` endpoint.

**Exact changes needed:**

Add a health endpoint subsection to the Monitoring section. Insert after the "## Monitoring" header (line 186), before the existing bullet list:

```markdown
### Health Endpoint

Pipelit exposes a `/health` endpoint that checks Redis and database connectivity. No authentication is required.

```bash
curl http://localhost:8000/health
```

```json
{
  "status": "ok",
  "version": "0.2.0",
  "redis": true,
  "database": true
}
```

Use this for load balancer health probes and automated monitoring. See the [Health Check API reference](../api/health.md) for details.
```

Then update the bullet list to reference the health endpoint as the first item:

```markdown
- **Health endpoint** — `GET /health` returns `"ok"` or `"degraded"` with per-check breakdown (no auth required)
- **systemd service status** -- both `pipelit` and `pipelit-worker` should be `active (running)`
- **Redis connectivity** -- `redis-cli ping` should return `PONG`
- **Worker queue depth** -- `rq info` shows pending/active/failed job counts
- **Application logs** -- watch for unhandled exceptions via `journalctl`
- **Disk space** -- SQLite databases and Redis persistence files grow over time
```

---

## P2 — Polish (5 items)

### 5. UPDATE: `docs-site/docs/index.md`

**Current state:** Homepage has 9 feature cards. Missing: Skills and Multi-Provider LLM support.

**Exact changes needed:**

Add two new feature cards. Insert before the closing `</div>` tag (line 113):

```markdown
<div class="card" markdown>

### Multi-Provider LLM

Use OpenAI, Anthropic, MiniMax, GLM, or any OpenAI-compatible API. Configure credentials once, select models per agent node.

</div>

<div class="card" markdown>

### Skills

Structured Claude Code workflows for repeatable engineering tasks. Approval gates, CI analysis, review triage — automated with human oversight.

</div>
```

This brings the feature grid to 11 cards (still looks fine in a 3-column grid).

---

### 6. UPDATE: `docs-site/docs/concepts/security.md`

**Current state:** No mention of sandbox or code execution isolation. The page covers: authentication, credential encryption, TOTP MFA, agent identity verification, credential scope, agent users, and a security checklist.

**Exact changes needed:**

Add a new section after "Agent Users" (after line 58) and before "Security Checklist":

```markdown
## Sandboxed Code Execution

Agent shell commands run inside an OS-level sandbox that isolates each workspace from the host filesystem, environment variables, and network. The sandbox uses bubblewrap (`bwrap`) on Linux with an Alpine rootfs, or falls back to environment scrubbing when running inside a container (Docker, Codespaces, Kubernetes).

Key protections:

- **Filesystem isolation** — agents can only read/write their workspace directory and `/tmp`
- **Environment scrubbing** — host secrets in environment variables are not visible
- **Network isolation** — no network access by default (`--unshare-all`); opt-in per workspace
- **Process namespace** — agents cannot see host processes

See [Sandbox](sandbox.md) for the full architecture, detection logic, and configuration.
```

Also add a row to the Security Checklist table:

| `SANDBOX_MODE` | `auto` OK | Verify `bwrap` or container |

---

### 7. UPDATE: `docs-site/docs/faq.md`

**Current state:** Sections: General (4 entries), Setup & Installation (3), Workflows (3), Agents (3), Execution (3), Deployment (3). No mention of skills or multi-provider setup.

**Exact changes needed:**

Add a new "Skills" section after "Deployment" (before the file ends at line 100):

```markdown
---

## Skills

### What are skills?

Skills are structured Claude Code workflows that automate repeatable engineering tasks. Each skill is a `SKILL.md` file with YAML frontmatter defining when to invoke it and markdown body describing the steps. Skills are invoked via `/skill-name` in Claude Code.

### Where do I find available skills?

Skills are maintained in a standalone repository: [github.com/theuselessai/skills](https://github.com/theuselessai/skills). See the [Skills overview](contributing/skills/index.md) for concepts and usage.

### Can I write my own skills?

Yes. A skill is just a markdown file with YAML frontmatter. See the skills repository for examples and the authoring guide.
```

Add a new "Providers" section after "Skills":

```markdown
---

## Providers

### How do I add a new LLM provider?

Go to the **Credentials** page, click **Add Credential**, choose **LLM Provider**, and fill in the provider type, API key, and base URL. Pipelit supports Anthropic, OpenAI, MiniMax, GLM, and any OpenAI-compatible API. See [Providers](concepts/providers.md) for setup details.

### Can I use local models?

Yes. Any service that implements the OpenAI `/v1/chat/completions` endpoint works as an OpenAI-compatible provider. This includes Ollama (`http://localhost:11434/v1`), LM Studio, and vLLM. Set the API key to any non-empty string if the service doesn't require authentication.

### Can I use different models for different agents?

Yes. Each agent node connects to its own AI Model sub-component, which specifies both the credential and model. Different agents in the same workflow can use different providers and models.
```

---

### 8. REMOVE: `docs-site/docs/components/logic/aggregator.md`

**Current state:** File exists at `docs-site/docs/components/logic/aggregator.md` (54 lines). Documents the Aggregator component which was removed in v0.2.0.

**Actions needed:**

1. **Delete the file:** `docs-site/docs/components/logic/aggregator.md`

2. **Update `docs-site/docs/components/logic/index.md`:**
   - Line 7: Change "nine logic component types" to "eight logic component types"
   - Line 18: Remove the row `| [Aggregator](aggregator.md) | Collect and combine array items | Flexible aggregation |`
   - Lines 44-46 (Iteration section): Remove or update any reference to Aggregator. Currently: "The loop body runs once per item, and results are collected into an output array." — this is fine as-is, it describes Loop behavior without mentioning Aggregator.

3. **Update `mkdocs.yml`:** Remove the Aggregator entry (see mkdocs.yml section below). Note: Aggregator is NOT currently in the `mkdocs.yml` nav — it was never added during P0, and it wasn't in the original nav either. Let me re-check...

   **Confirmed:** Aggregator is NOT listed in the current `mkdocs.yml` nav (lines 153-161 list Switch, Code, Merge, Filter, Loop, Wait, Human Confirmation, Subworkflow — no Aggregator). The file exists on disk but was never added to nav. Only the `logic/index.md` references it.

---

### 9. UPDATE: `docs-site/mkdocs.yml`

**Current state:** Full nav structure at lines 77-224. P0 already added:
- `Sandbox: concepts/sandbox.md` (line 99)
- `Providers: concepts/providers.md` (line 100)
- `Webhook: components/triggers/webhook.md` (line 120)
- Skills section under Contributing (lines 191-192, currently just `skills/index.md`)

Commit cb7d67f removed `pr-workflow.md` and `writing-skills.md` nav entries.

**Changes needed for P1+P2:**

**Add to API Reference section** (after line 182, `WebSocket: api/websocket.md`):
```yaml
    - Health: api/health.md
```

**Add to Tutorials section** (after line 109, `YAML DSL: tutorials/yaml-dsl.md`):
```yaml
    - PR Workflow Skill: tutorials/pr-workflow-skill.md
```

**No Aggregator removal needed in nav** — it was never in the nav.

**Exact nav diff:**

```diff
   - Tutorials:
     - tutorials/index.md
     - Chat Agent: tutorials/chat-agent.md
     - Telegram Bot: tutorials/telegram-bot.md
     - Conditional Routing: tutorials/conditional-routing.md
     - Scheduled Workflow: tutorials/scheduled-workflow.md
     - Multi-Agent: tutorials/multi-agent.md
     - Self-Improving Agent: tutorials/self-improving-agent.md
     - YAML DSL: tutorials/yaml-dsl.md
+    - PR Workflow Skill: tutorials/pr-workflow-skill.md
```

```diff
   - API Reference:
     - api/index.md
     - Authentication: api/auth.md
     - Workflows: api/workflows.md
     - Nodes: api/nodes.md
     - Edges: api/edges.md
     - Executions: api/executions.md
     - Chat: api/chat.md
     - Credentials: api/credentials.md
     - Schedules: api/schedules.md
     - Memory: api/memory-api.md
     - Epics: api/epics.md
     - Tasks: api/tasks.md
     - Users: api/users.md
     - WebSocket: api/websocket.md
+    - Health: api/health.md
```

---

## Implementation Order

1. **P1-1:** Create `api/health.md` (standalone, no dependencies)
2. **P1-4:** Update `deployment/production.md` (adds link to health.md)
3. **P1-2:** Create `tutorials/pr-workflow-skill.md` (standalone, references skills/index.md)
4. **P1-3:** Update `concepts/index.md` (add Providers, Sandbox, Skills cards)
5. **P2-5:** Update `index.md` (homepage feature cards)
6. **P2-6:** Update `concepts/security.md` (add sandbox section)
7. **P2-7:** Update `faq.md` (add skills + providers FAQ sections)
8. **P2-8:** Remove `components/logic/aggregator.md` + update `logic/index.md`
9. **P2-9:** Update `mkdocs.yml` (add Health to API, PR Workflow Skill to Tutorials)

## Files Changed Summary

| # | File | Action | Priority |
|---|------|--------|----------|
| 1 | `docs-site/docs/api/health.md` | CREATE | P1 |
| 2 | `docs-site/docs/tutorials/pr-workflow-skill.md` | CREATE | P1 |
| 3 | `docs-site/docs/concepts/index.md` | UPDATE | P1 |
| 4 | `docs-site/docs/deployment/production.md` | UPDATE | P1 |
| 5 | `docs-site/docs/index.md` | UPDATE | P2 |
| 6 | `docs-site/docs/concepts/security.md` | UPDATE | P2 |
| 7 | `docs-site/docs/faq.md` | UPDATE | P2 |
| 8 | `docs-site/docs/components/logic/aggregator.md` | DELETE | P2 |
| 9 | `docs-site/docs/components/logic/index.md` | UPDATE | P2 |
| 10 | `docs-site/mkdocs.yml` | UPDATE | P2 |

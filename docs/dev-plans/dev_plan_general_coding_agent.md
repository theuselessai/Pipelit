# General Coding Agent — Development Plan

**Date:** 2026-02-19
**Status:** Draft

## Overview

A Pipelit workflow that wraps Claude Code CLI (`claude`) as a tool-calling coding agent. The agent operates in discrete modes (investigate, execute, commit, coverage, review), each with scoped tool permissions enforced via `--allowedTools`. State is managed through Pipelit's memory system, and the agent communicates with users through any chat trigger (Telegram, web chat, webhook).

The dispatcher is an LLM agent node that reads user messages, determines the appropriate mode, constructs the corresponding `claude -p` command with the correct tool permissions, executes it via `run_command`, stores state in memory, and replies to the user.

---

## Prerequisites

| Dependency | Purpose | Notes |
|---|---|---|
| **Claude CLI** (`claude`) | Coding agent backend | Must be installed and authenticated on the host. `claude -p` for non-interactive mode. |
| **SearXNG** | Web search for investigation | Self-hosted instance. URL configured in `web_search` node's `extra_config.searxng_url`. Optional — omit the web_search tool node if not needed. |
| **Chat trigger** | User interaction | Any Pipelit trigger: `trigger_chat` (web UI), `trigger_telegram`, `trigger_webhook`. The workflow is trigger-agnostic — swap the trigger node without changing anything else. |
| **Git + GitHub CLI** (`gh`) | Version control and PRs | Must be installed and authenticated. Used in COMMIT_AND_PR and REVIEW_TRIAGE modes. |
| **LLM credential** | Dispatcher agent's model | An `ai_model` node connected to the dispatcher agent. Any supported provider. |

---

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│ Chat Trigger │────▶│  Dispatcher  │────▶│   Reply     │
│ (any type)   │     │  (agent)     │     │ (via trigger)│
└─────────────┘     └──────┬───────┘     └─────────────┘
                           │
                    ┌──────┴───────┐
                    │   Tools:     │
                    │ • run_command │
                    │ • memory_read │
                    │ • memory_write│
                    │ • web_search  │
                    └──────────────┘
```

The dispatcher agent is a single `agent` node with four tool sub-components. It receives user messages via `{{ trigger.text }}`, decides which mode to run, constructs the appropriate `claude -p` invocation, executes it through `run_command`, persists state to memory, and returns a reply.

---

## Execution Flow

```
① INVESTIGATE (always first, autonomous)    → Reply: findings + plan
② User confirms plan                        → ③ EXECUTE (autonomous)
④ EXECUTE done                              → Reply: "Changes done. Tests passing. Commit?"
⑤ User confirms commit                      → ⑥ COMMIT_AND_PR (autonomous)
⑦ PR created                                → Reply: "PR #N created. Running coverage..."
⑧ COVERAGE_LOOP (autonomous)                → Reply: "Coverage at X%. Running review triage..."
⑨ REVIEW_TRIAGE (autonomous)                → Reply: "All checks passing. Ready for review."
```

The dispatcher decides which mode to enter based on conversational context and memory state. The user can also explicitly request a mode (e.g., "just investigate this, don't fix it").

---

## Mode Definitions

### INVESTIGATE

**Purpose:** Understand the problem, explore the codebase, reproduce bugs, form a plan.

**Template:**
```bash
claude -p \
  --output-format json \
  --max-turns 20 \
  --allowedTools "Bash(find *),Bash(grep *),Bash(cat *),Bash(ls *),Bash(git log *),Bash(git diff *),Bash(git grep *),Bash(python3 /tmp/*),Bash(curl localhost:8080/*),Bash(gh pr view *),Bash(gh pr diff *),Bash(gh issue *),Bash(gh run *),Read,Write(/tmp/*)" \
  --system-prompt "$(cat docs/agents/coding_agent_system_prompt.md)" \
  --cwd <repo_path> \
  "<task_description>"
```

**Outputs:** Findings summary + proposed plan. The dispatcher relays this to the user and waits for confirmation.

**Key constraints:**
- Read-only access to the repository (writes only to /tmp/)
- No test execution, no file modification
- Can inspect GitHub PRs, issues, and CI runs

### EXECUTE

**Purpose:** Implement the approved plan — write code, fix bugs, add features, run tests.

**Template:**
```bash
claude -p \
  --output-format json \
  --max-turns 30 \
  --allowedTools "Bash(find *),Bash(grep *),Bash(cat *),Bash(ls *),Bash(git log *),Bash(git diff *),Bash(git grep *),Bash(python3 /tmp/*),Bash(python -m pytest *),Bash(npm *),Read,Write,Edit" \
  --system-prompt "$(cat docs/agents/coding_agent_system_prompt.md)" \
  --cwd <repo_path> \
  --resume <session_id> \
  "EXECUTE: <plan_summary>"
```

**Outputs:** Summary of changes + test results. The dispatcher reports back to the user.

**Key constraints:**
- Full file read/write/edit access
- Can run tests and build commands
- No git commits, no pushes, no PRs

### COMMIT_AND_PR

**Purpose:** Create a feature branch, commit all changes, push, and open a pull request.

**Template:**
```bash
claude -p \
  --output-format json \
  --max-turns 10 \
  --allowedTools "Bash(git checkout *),Bash(git branch *),Bash(git add *),Bash(git commit *),Bash(git push *),Bash(gh pr create *),Read" \
  --system-prompt "$(cat docs/agents/coding_agent_system_prompt.md)" \
  --cwd <repo_path> \
  --resume <session_id> \
  "COMMIT_AND_PR: Create a feature branch named '<branch_name>', commit all changes with a descriptive message, push to origin, and create a PR. Return the PR number and URL."
```

**Outputs:** PR number and URL. The dispatcher stores these in memory and reports to the user.

**Key constraints:**
- Git operations only — no file editing
- Read access for reviewing what to commit
- Single PR creation per invocation

### COVERAGE_LOOP

**Purpose:** Improve test coverage. Iterate: write tests → run coverage → check delta → repeat.

**Template:**
```bash
claude -p \
  --output-format json \
  --max-turns 30 \
  --allowedTools "Bash(python -m pytest *),Bash(npm *),Read,Write(tests/**),Write(src/**/*.test.*),Edit" \
  --system-prompt "$(cat docs/agents/coding_agent_system_prompt.md)" \
  --cwd <repo_path> \
  --resume <session_id> \
  "COVERAGE_LOOP: Write tests to improve coverage for the changes in PR #<pr_number>. Current baseline: <baseline>%. Target: <target>%. Only modify test files (tests/**, src/**/*.test.*) and source files for testability (not behavior). Run coverage after each batch of tests."
```

**Outputs:** Coverage report summary. The dispatcher compares against baseline and decides whether to loop again or move on.

**Key constraints:**
- Can only write to test files and edit source for testability
- Cannot change application behavior
- Cannot commit or push (that happens in REVIEW_TRIAGE)

### REVIEW_TRIAGE

**Purpose:** Address PR review feedback — read comments, fix issues, run tests, push updates.

**Template:**
```bash
claude -p \
  --output-format json \
  --max-turns 20 \
  --allowedTools "Bash(gh pr view *),Bash(gh pr diff *),Bash(gh pr comment *),Bash(gh pr merge *),Bash(gh issue *),Bash(gh run *),Bash(python -m pytest *),Bash(git add *),Bash(git commit *),Bash(git push *),Read,Write,Edit" \
  --system-prompt "$(cat docs/agents/coding_agent_system_prompt.md)" \
  --cwd <repo_path> \
  --resume <session_id> \
  "REVIEW_TRIAGE: Address review feedback on PR #<pr_number>. Read all comments, fix the issues, run tests, and push updates. Summarize what was changed."
```

**Outputs:** Summary of fixes + updated test results.

**Key constraints:**
- Full read/write/edit access
- Can commit and push updates
- Can comment on PRs
- Should not merge without explicit user approval

---

## Tool Permissions Matrix

| Tool | Investigate | Execute | Commit&PR | Coverage | Review |
|------|:-----------:|:-------:|:---------:|:--------:|:------:|
| `Bash(find/grep/cat/ls *)` | yes | yes | — | — | — |
| `Bash(git log/diff/grep *)` | yes | yes | — | — | — |
| `Bash(python3 /tmp/*)` | yes | yes | — | — | — |
| `Bash(curl localhost:8080/*)` | yes | — | — | — | — |
| `Bash(python -m pytest *)` | — | yes | — | yes | yes |
| `Bash(npm *)` | — | yes | — | yes | — |
| `Bash(git checkout/branch *)` | — | — | yes | — | — |
| `Bash(git add/commit/push *)` | — | — | yes | — | yes |
| `Bash(gh pr create *)` | — | — | yes | — | — |
| `Bash(gh pr view/diff/comment/merge *)` | yes | — | — | — | yes |
| `Bash(gh issue/run *)` | yes | — | — | — | yes |
| `Read` | yes | yes | yes | yes | yes |
| `Write(/tmp/*)` | yes | — | — | — | — |
| `Write` (unrestricted) | — | yes | — | — | yes |
| `Write(tests/**),Write(src/**/*.test.*)` | — | — | — | yes | — |
| `Edit` | — | yes | — | yes | yes |

---

## Session Management

### How `claude -p --output-format json` works

When invoked with `--output-format json`, `claude -p` returns a JSON object containing the session ID and result:

```json
{
  "session_id": "abc123-def456-...",
  "result": "... the agent's text response ...",
  "cost_usd": 0.042,
  "duration_ms": 15000,
  "num_turns": 5
}
```

### Session ID extraction

The dispatcher must parse the JSON output from `run_command` to extract `session_id`. This is stored in memory for subsequent `--resume` calls.

**Extraction logic (in dispatcher system prompt):**
1. Parse the `run_command` output as JSON
2. Extract `result.session_id` (or `session_id` at top level — check both)
3. Store in memory under `coding_agent::session_id::<task_hash>`
4. Use in subsequent mode invocations: `--resume <session_id>`

### `--resume` behavior

- `--resume <session_id>` continues an existing Claude session, preserving full conversation history and context
- **Tool permissions are per-invocation, not per-session.** Using `--resume` with different `--allowedTools` is supported and works correctly — the new invocation uses only the tools specified in that invocation's `--allowedTools` flag
- This is critical for the mode transition pattern: INVESTIGATE creates a session, EXECUTE resumes it with different tools, COMMIT_AND_PR resumes again with git-only tools, etc.

### Session lifecycle

```
INVESTIGATE  →  creates session_id  →  stored in memory
EXECUTE      →  --resume session_id →  same context, different tools
COMMIT_AND_PR → --resume session_id →  same context, git-only tools
COVERAGE_LOOP → --resume session_id →  same context, test-only tools
REVIEW_TRIAGE → --resume session_id →  same context, full review tools
```

All modes after INVESTIGATE reuse the same session, so Claude retains full context of the investigation findings, the implementation plan, and all prior work.

---

## Memory Key Convention

All keys use the `coding_agent::` prefix to namespace them within Pipelit's global memory. The `<task_hash>` is a short hash of the original task description (e.g., first 8 chars of SHA-256) to keep keys unique per task.

| Key | Value | Purpose |
|---|---|---|
| `coding_agent::state::<task_hash>` | Current mode + metadata (JSON) | Track where the agent is in the flow |
| `coding_agent::session_id::<task_hash>` | Claude session ID (string) | Resume sessions across mode transitions |
| `coding_agent::pr::<task_hash>` | PR number + URL (JSON) | Reference for coverage/review modes |
| `coding_agent::coverage_baseline::<task_hash>` | Coverage percentage (float) | Compare coverage before/after |
| `coding_agent::task::<task_hash>` | Original task description (string) | Recovery — re-read the task if context is lost |
| `coding_agent::loop_stuck::<pr_number>` | Iteration count + last delta (JSON) | Escape hatch for coverage loops that stop improving |

**Memory system notes:**
- Pipelit memory uses ILIKE text search (not vector/semantic search). Use the `coding_agent::` prefix convention to make keys discoverable via search.
- `get_fact()` does exact key match. `search_facts()` does ILIKE with normalized separators (spaces, underscores, hyphens treated as equivalent).
- All memory is stored at global scope (`agent_id="global"`).

---

## Error Handling

### `claude -p` failure modes

| Failure | Detection | Recovery |
|---|---|---|
| **Timeout** (command exceeds `run_command` timeout) | `run_command` returns timeout message | Reply to user: "The coding session timed out after X seconds. The work done so far is preserved in the session. I can resume where it left off." |
| **Non-zero exit code** | `run_command` output contains exit code | Parse error output, report to user, suggest retry or manual intervention |
| **Malformed JSON output** | JSON parse fails on `run_command` result | Reply to user with raw output. Store nothing in memory. Ask user how to proceed. |
| **Empty output** | `run_command` returns empty or whitespace | Reply: "Claude returned no output. This may indicate a crash or auth issue. Check that `claude` CLI is working." |
| **Session not found** (`--resume` with invalid ID) | Error message in output | Drop the session_id from memory, start fresh with a new INVESTIGATE |

### Dispatcher error handling rules

1. **Never silently fail.** If any step produces an error, report it to the user immediately.
2. **Don't retry blindly.** If a command fails, don't re-run the exact same command. Analyze the error first.
3. **Preserve partial work.** If EXECUTE partially completes before timeout, the session is preserved. Resume with `--resume` instead of starting over.
4. **Fallback reply.** If the dispatcher cannot parse Claude's output at all, reply with the raw `run_command` output so the user can see what happened.

---

## Workflow YAML

This defines the Pipelit workflow graph — the dispatcher agent, its tools, and connections.

```yaml
name: General Coding Agent
slug: general-coding-agent
description: >
  Claude Code-powered coding agent with mode-based tool scoping.
  Supports investigate, execute, commit, coverage, and review modes.

nodes:
  - id: trigger_chat_001
    type: trigger_chat
    position: [0, 200]

  - id: agent_dispatcher
    type: agent
    position: [300, 200]
    config:
      system_prompt: |
        You are a coding agent dispatcher running on the Pipelit platform.

        ## Your Role
        You receive user messages and orchestrate coding tasks by running Claude Code CLI
        in the appropriate mode. You decide which mode to use, construct the command,
        execute it via run_command, store state in memory, and reply to the user.

        ## Available Modes
        - INVESTIGATE: Explore and plan (read-only, always first)
        - EXECUTE: Implement the plan (read/write, after user confirms)
        - COMMIT_AND_PR: Branch, commit, push, create PR (after execute)
        - COVERAGE_LOOP: Write tests, improve coverage (after PR)
        - REVIEW_TRIAGE: Fix review feedback, push updates (after coverage or on review comments)

        ## Decision Logic

        1. **New task (no state in memory):** Run INVESTIGATE.
        2. **User confirms plan:** Run EXECUTE with --resume.
        3. **Execute complete, user says "commit" or "yes":** Run COMMIT_AND_PR with --resume.
        4. **PR created:** Run COVERAGE_LOOP with --resume.
        5. **Coverage done or user says "skip coverage":** Run REVIEW_TRIAGE with --resume.
        6. **User pastes review feedback or says "check reviews":** Run REVIEW_TRIAGE with --resume.

        ## Command Templates

        See the system prompt file for mode definitions.
        See memory keys for session_id, PR info, coverage baseline, and task state.

        ### Template Variables
        - <repo_path>: The repository working directory (ask user or use cwd)
        - <session_id>: Retrieved from memory key `coding_agent::session_id::<task_hash>`
        - <task_hash>: First 8 chars of SHA-256 of the original task description
        - <pr_number>: Retrieved from memory key `coding_agent::pr::<task_hash>`
        - <baseline>: Retrieved from memory key `coding_agent::coverage_baseline::<task_hash>`
        - <branch_name>: Generated from the task description (e.g., fix/login-timeout)

        ## Self-Verification Checklist
        Before executing ANY claude -p command:
        - [ ] Is the mode correct for the current conversation state?
        - [ ] Does the --allowedTools list match the mode's tool permissions exactly?
        - [ ] Am I using --resume with the correct session_id (if not INVESTIGATE)?
        - [ ] Is the --cwd pointing to the right repository?
        - [ ] Did I store/retrieve the correct memory keys?

        ## Memory Keys (all prefixed with coding_agent::)
        - coding_agent::state::<task_hash> — current mode + metadata
        - coding_agent::session_id::<task_hash> — claude session ID for --resume
        - coding_agent::pr::<task_hash> — PR number + URL
        - coding_agent::coverage_baseline::<task_hash> — pre-change coverage %
        - coding_agent::task::<task_hash> — original task description
        - coding_agent::loop_stuck::<pr_number> — coverage loop escape hatch

        ## Error Handling
        - If run_command returns a timeout: tell the user, offer to resume
        - If JSON parsing fails: show the raw output to the user
        - If session_id is missing for --resume: start fresh with INVESTIGATE
        - Never retry the same failing command without changing something

        ## Important
        - The system prompt file is at: docs/agents/coding_agent_system_prompt.md
        - All claude -p commands use: --output-format json
        - Parse the JSON output to extract session_id and result
        - Always report back to the user after each mode completes
      extra_config:
        conversation_memory: true

  - id: model_dispatcher
    type: ai_model
    position: [300, 450]
    config:
      model_name: claude-sonnet-4-6

  - id: tool_run_command
    type: run_command
    position: [550, 100]
    config:
      extra_config:
        timeout: 3600

  - id: tool_memory_read
    type: memory_read
    position: [550, 250]
    config:
      extra_config:
        memory_type: facts

  - id: tool_memory_write
    type: memory_write
    position: [550, 400]
    config:
      extra_config:
        overwrite: true

  - id: tool_web_search
    type: web_search
    position: [550, 550]
    config:
      extra_config:
        searxng_url: "http://localhost:8080"

edges:
  # Trigger → Agent (data flow)
  - source: trigger_chat_001
    target: agent_dispatcher
    label: ""

  # Model → Agent (LLM connection)
  - source: model_dispatcher
    target: agent_dispatcher
    label: llm

  # Tools → Agent (tool connections)
  - source: tool_run_command
    target: agent_dispatcher
    label: tool

  - source: tool_memory_read
    target: agent_dispatcher
    label: tool

  - source: tool_memory_write
    target: agent_dispatcher
    label: tool

  - source: tool_web_search
    target: agent_dispatcher
    label: tool
```

### Trigger Flexibility

The YAML uses `trigger_chat` as the default trigger. To use a different trigger:

- **Telegram:** Change `trigger_chat_001` type to `trigger_telegram` and configure the Telegram credential
- **Webhook:** Change to `trigger_webhook` for HTTP-triggered invocations
- **Scheduler:** Add a `trigger_schedule` for periodic autonomous runs

No other nodes or edges need modification. The `{{ trigger.text }}` expression and response delivery work identically across all trigger types — Pipelit's orchestrator and delivery service handle the routing.

---

## Configuration Notes

### `run_command` Timeout

The `run_command` node is configured with `timeout: 3600` (1 hour). This is necessary because:
- Claude Code sessions can be long-running, especially in EXECUTE and COVERAGE_LOOP modes
- The default `run_command` timeout is 300 seconds (5 minutes), which is insufficient
- The timeout is read from `extra_config.timeout` in `platform/components/run_command.py`

If 1 hour is still insufficient for large codebases, increase the timeout value. Be aware that the RQ worker also has its own job timeout — ensure it's set higher than the `run_command` timeout.

### Dispatcher Model

The YAML uses `claude-sonnet-4-6` for the dispatcher agent. The dispatcher's job is relatively simple (mode selection, command construction, memory management), so a fast model is sufficient. The heavy lifting is done by the Claude Code CLI sessions invoked via `run_command`.

### Web Search (Optional)

The `web_search` tool requires a running SearXNG instance. If you don't have one, remove the `tool_web_search` node and its edge from the YAML. The agent will still function — it just won't be able to search the web during investigation.

---

## Implementation Checklist

- [ ] Create the system prompt file at `docs/agents/coding_agent_system_prompt.md`
- [ ] Deploy the workflow YAML via Pipelit DSL compiler or manual canvas setup
- [ ] Configure the `ai_model` node with a valid LLM credential
- [ ] Verify `claude` CLI is installed and authenticated on the host
- [ ] Set `run_command` timeout to 3600 in node config
- [ ] (Optional) Set up SearXNG and configure the URL
- [ ] (Optional) Configure `trigger_telegram` instead of `trigger_chat` if using Telegram
- [ ] Test the full flow: send a task → INVESTIGATE → confirm → EXECUTE → commit → coverage → review

---

## Future Enhancements

1. **Automatic mode transitions:** Instead of waiting for user confirmation between INVESTIGATE and EXECUTE, allow a "full auto" mode where the agent runs all steps autonomously.
2. **Budget enforcement:** Integrate with Pipelit's Epic/Task budget system to cap per-task spending.
3. **Parallel coverage:** Run coverage analysis on multiple test files in parallel using Pipelit's fan-out topology.
4. **PR merge automation:** After REVIEW_TRIAGE passes all checks, auto-merge if configured.
5. **Multi-repo support:** Store repo paths in memory and support tasks across multiple repositories.

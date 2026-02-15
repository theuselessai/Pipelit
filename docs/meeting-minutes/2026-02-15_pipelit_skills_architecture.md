# Pipelit Architecture Discussion — Meeting Minutes

**Date:** 2026-02-15 (Sunday)
**Participants:** Yao, Claude
**Duration:** Extended session
**Status:** Exploratory architecture discussion

-----

## 1. Starting Point: How Anthropic's Skills Work

Discussion began with an examination of how Claude's Skill system works internally.

**Key findings:**

- Skills are pre-written guidance files (SKILL.md) stored in `/mnt/skills/`, containing best practices for specific file creation tasks (docx, pptx, xlsx, pdf, etc.)
- Claude reads the relevant SKILL.md **before** executing any task — "先读后做"
- Skills are composable — multiple skills can be combined for a single task
- Skills are read-only, mounted on the file system, version-controlled
- The `skill-creator` skill is self-bootstrapping — you can use it to create and eval new skills

**Skill boundaries identified:**

- Read-only at runtime (Claude cannot modify skills)
- Limited by context window (large skills get truncated)
- No cross-session persistence
- Cannot override Claude's core behavior — they are "操作指南", not system prompt overrides
- Bound by the environment's tool/network constraints

-----

## 2. Integrating Skills into Pipelit

Three approaches discussed for bringing skills into Pipelit's existing architecture:

|Approach                                           |Effort |Description                                                                                                                        |
|---------------------------------------------------|-------|-----------------------------------------------------------------------------------------------------------------------------------|
|**Option 1: Agent config injection**               |Minimal|Add `skill_files` field to agent node config. Concatenate SKILL.md content into system prompt at execution time. ~20 lines of code.|
|**Option 2: Skill as workflow template + metadata**|Medium |Three-layer structure: SKILL.md (prompt) + workflow_template.json (pre-configured graph) + assets/. Recommended long-term model.   |
|**Option 3: Skill as first-class node type**       |Large  |New `skill` node that encapsulates a sub-workflow. Closest to OpenClaw's skill architecture.                                       |

**Decision:** Start with Option 1, design data model for Option 2. Pre-reserve a `Skill` model in the database for future iteration toward the Agent Skills Market vision.

-----

## 3. The Localtime Problem and Its Connection to Skills

Referenced the Valentine's Day debugging session where the orchestrator failed to determine local time — returning UTC and asking the user for their timezone instead of using tools to resolve it.

**Root cause analysis:**

- The problem-solving protocol in the system prompt had a trigger condition that was too narrow ("when any tool call fails")
- The model never attempted a tool call — it answered in UTC and considered the response complete
- Multiple prompt iterations failed to reliably trigger the correct behavior

**Key insight:** This wasn't a timezone problem — it was a **behavioral pattern** problem. The fix shouldn't be a timezone-specific instruction; it should be a generalized heuristic about self-sufficiency.

-----

## 4. Skills vs Memory — Relationship Clarified

|Dimension         |Memory                               |Skill                                    |
|------------------|-------------------------------------|-----------------------------------------|
|**What it stores**|Facts, data ("user timezone is ACDT")|Behavior patterns ("check before asking")|
|**Lifecycle**     |Runtime, per-user, mutable           |Development-time, cross-user, versioned  |
|**Storage**       |Database (key-value)                 |File system (markdown)                   |
|**Stability**     |Changes frequently                   |Changes rarely                           |
|**Scope**         |One scenario                         |Generalizes across scenarios             |

**Critical relationship:** Without memory, skills have methods but no data. Without skills, memory has data but the model doesn't know to check it. Both are needed, but both are ultimately **text injected into the context window**.

-----

## 5. Granularity Principle — "宁缺毋滥"

**Yao's insight:** Problem-solving should be a skill, not timezone resolution. The correct granularity for skills is **behavioral patterns**, not knowledge fragments.

**Practical recommendation:**

1. Strip the orchestrator system prompt down to ~10 lines
1. Use one heuristic instead of a multi-layer protocol: *"Never reply with incomplete information if a tool call could complete it."*
1. Test in real scenarios; add one-sentence heuristics only when a specific failure is observed
1. Only package into a formal skill file when 5-6 validated heuristics have accumulated

**Core principle:** Heuristics tell the model **how to judge**. Protocols tell the model **what to do**. Heuristics are reliable in LLMs; protocols are not — LLMs are not state machines.

-----

## 6. Memory-to-Skill Sedimentation

Discussed the pattern of memories "沉淀" (sedimenting) into skills over time.

**Example:** Four separate memory entries about different scenarios all encoding the same pattern ("check tools before asking user") → Extracted into one generalized skill heuristic.

**Important:** This sedimentation process should **not** be automated (for now). Reasons:

- Auto-extraction requires the model to identify cross-cutting patterns and generalize — a hard reasoning task
- A wrong skill systematically pollutes all future behavior (much worse than a wrong memory which only affects one scenario)
- Follow the software engineering principle: "write it three times before abstracting into a function"

-----

## 7. Five-Role Cognitive Architecture

### The "Brain" Metaphor

|Role        |Human Analogy    |Function                             |Runtime                |Context Needs                                                   |
|------------|-----------------|-------------------------------------|-----------------------|----------------------------------------------------------------|
|**Operator**|Prefrontal cortex|Execute tasks, make decisions        |Real-time              |Minimal: current task + relevant skills + relevant memories     |
|**Reviewer**|Hippocampus      |Consolidate experience, find patterns|Periodic (daily/weekly)|Broad: recent memories, execution logs, failure patterns        |
|**Scout**   |Dopamine system  |Explore unknowns proactively         |Idle time              |Deep: full documents, API specs, one direction at a time        |
|**Doctor**  |Immune system    |Diagnose and heal the platform       |Anomaly-triggered      |System-specific: architecture diagrams, runbooks, health metrics|
|**Auditor** |Conscience       |Observe and enforce rules            |Real-time stream       |Lightest: rule set + current execution log                      |

### Role Details

**Operator** — The only user-facing role. Capabilities:

- Direct execution (simple tasks, minimal tokens)
- Invoke workflow (known processes, zero improvise)
- Spawn subagent (complex unknowns, parallel exploration)
- Request identify_human (needs human judgment)

**Reviewer** — Memory's garbage collector. Responsibilities:

- **增 (Add):** Extract skills from repeated improvise patterns
- **删 (Delete):** Clean outdated, redundant, already-sedimented memories
- **改 (Merge):** Resolve contradictory entries (e.g., two timezone values → keep newer)
- **查 (Audit):** Detect memory quality issues (e.g., prompt injection contamination)
- Frequency: proportional to memory growth rate

**Scout** — Proactive exploration. Runs when task queue is empty. Examples: check dependency updates, scan API documentation changes, monitor competitor developments.

**Doctor** — Self-healing. Distinguished from other roles by its **system-specific skills**:

```
skills/
└── pipelit-internals/
    ├── SKILL.md              # Architecture overview, component relationships
    ├── architecture.md       # Data flow diagrams, dependency graphs
    ├── failure-patterns.md   # Known failure modes and their indicators
    └── runbooks.md           # Specific remediation steps
```

This is also the **killer demo** — a system that can read its own architecture, diagnose its own problems, and submit PRs to fix its own bugs.

**Auditor** — The only role that can potentially run without LLM (pure rule engine). Watches execution stream for:

- Policy violations (e.g., skipped identify_human on high-risk operations)
- Cost anomalies (token consumption spikes)
- Behavioral patterns that should be escalated to Reviewer for skill extraction
- Security anomalies (unexpected external URL access, suspicious memory writes)

-----

## 8. Context Window as the Central Constraint

### The Core Tension

> Agent 越自主，context 消耗越大。但 context 是有限且昂贵的。

Every abstraction layer in Pipelit serves the same purpose — **reducing the amount of improvisation the agent needs to do within a single context window**:

```
Pre-computation:  High ◄──────────────────────────► Low
                  Workflow → Task → Memory → Skill → Improvise
Context cost:     Near zero                          Very expensive
Flexibility:      Zero                               Maximum
```

### Skills and Memory as Compression Formats

- **Skill** = compressed behavioral pattern ("when X, do Y before Z")
- **Memory** = compressed fact ("timezone = ACDT")
- **Both** exist to keep Operator's context window filled with **high-density, pre-processed information** rather than raw data

### The Five Roles as a Compression Pipeline

Reviewer and Scout are essentially **context compression agents** for Operator:

- Reviewer compresses repeated improvise patterns → skills
- Scout compresses deep research → memory entries
- Doctor compresses system knowledge → domain-specific skills
- Operator only sees the compressed outputs, never the raw material

-----

## 9. Recursive Self-Invocation (Operator Spawning Subagents)

### Inspiration

Claude Code's subagent model: main agent spawns copies of itself for parallel exploration, each with its own independent context window. Subagents return compressed conclusions, not raw data.

### Current Limitation

Pipelit supports workflow → sub-workflow calls, but **not recursive self-invocation** (a workflow calling itself).

### Proposed Solution

Support self-invocation with hard architectural constraints:

```python
max_recursion_depth: int = 2    # Hard limit, not LLM-decided
current_depth: int = 0          # Passed through execution state
```

- Depth limit replaces the need for the LLM to judge "is this simple enough to solve directly"
- At max depth, the agent is forced to solve within current context — no further spawning

### Visualization Challenge

- **Design time (Canvas):** Simple — a workflow node pointing to itself, with a `max_depth` config field
- **Runtime (Execution):** Needs a tree view, not a graph view — this belongs in the TUI's Agents mode or a dedicated execution trace view, not on the React Flow canvas

**Decision:** Defer frontend visualization; focus on the execution engine support first.

-----

## 10. OpenClaw Comparison

### What OpenClaw Gets Right

- **Feedback loop is near-zero:** Message → execute → result. No canvas, no configuration, no node dragging.
- This is why it went viral in 19 days — the distance from intent to outcome is minimal.

### OpenClaw's Real Limitations

- **Security nightmare:** Exposed instances found on public internet; persistent memory means one prompt injection has lasting effects; any webpage can contain instructions the agent will execute
- **Operationally fragile:** Rate limit errors misreported as context overflow; exponential backoff documented but broken (Issue #5159); single model limit triggers full provider cooldown (Issue #5744)
- **Single-agent ceiling:** One agent + many skills, no workflow orchestration, no conditional routing, no parallel execution. Complex multi-step logic relies entirely on ReAct loop improvisation
- **Memory is unstructured Markdown files:** No structured queries, no permission isolation, no versioning, no garbage collection

### Pipelit's Differentiation

- Pipelit already has four layers of pre-computation (workflow, task, memory, skill) that reduce the need for expensive improvisation
- OpenClaw burns tokens because it has almost only the improvise layer
- Pipelit's value proposition is not "another agent framework" but **a system that systematically reduces agent improvisation needs**

-----

## 11. Orchestrator System Prompt Design — Industry Patterns

Surveyed three approaches from the ecosystem:

**LangGraph Minimal Supervisor:** ~2 sentences, uses structured output for routing. Simple but insufficient for complex scenarios.

**LangGraph Decentralized:** Each agent has the same generic prompt, decides independently whether to pass work along. Flexible but uncontrollable.

**OpenCode Structured Orchestrator:** Most complete — layered system prompt with identity, capability map, routing logic, chaining protocols, clarification rules, response format. Pure router that never executes.

### Pipelit's Approach

Pipelit's Operator is fundamentally different from all three — it's not a pure router, it's a meta-agent that also executes, manages tasks, reads/writes memory, and dynamically creates workflows.

**Proposed prompt structure:**

```
orchestrator_system_prompt =
    identity              # Who you are, core mission (short, fixed)
    + phases              # Phase 0 health check, Phase 1 task execution (fixed flow)
    + capability_map      # Dynamic: currently available tools + workflows
    + skills[]            # Dynamic: behavioral pattern skills loaded as needed
```

-----

## 12. Key Decisions & Next Steps

### Decided

- [ ] Strip orchestrator system prompt to ~10 lines
- [ ] Fix memory_read/write bug (the Valentine's Day root cause)
- [ ] Skills are **behavioral patterns**, not knowledge fragments
- [ ] Reviewer sedimentation process stays manual for now
- [ ] Recursive self-invocation: support with hard depth limit (max 2)
- [ ] Doctor gets its own pipelit-internals skill set
- [ ] Auditor runs as rule engine first, LLM fallback second

### Deferred

- [ ] Formal skill file system (wait for 5-6 validated heuristics to accumulate)
- [ ] Reviewer and Scout implementation (need real memory data first)
- [ ] Recursive call frontend visualization
- [ ] Automated memory-to-skill sedimentation

### Open Questions

- How to visualize multiple workflow execution instances on frontend?
- What naming convention for the five roles? (Operator/Reviewer/Scout/Doctor/Auditor vs alternatives)
- What's the right Reviewer frequency given current memory growth rate?
- Should Doctor's skills be community-contributed (toward the Skills Market)?

-----

*Document generated from conversation on 2026-02-15. Context: Pipelit v0.x architecture exploration phase.*

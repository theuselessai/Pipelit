# Meeting Summary: Skill to Workflow Distillation

**Date:** March 6, 2026  
**Participants:** Yao, Claude (Deep Agent)  
**Topic:** Improving Deep Agent fidelity through skill distillation and Meta Agent architecture

---

## Context

Current Deep Agent implementation is highly flexible but suffers from unpredictable behavior. Agent freely explores using skills (tools), leading to inconsistent results even with the same input. Need a way to improve determinism while preserving agent's exploration capability.

---

## Problem Statement

**Current State:**
- Deep Agent uses skills (run_command, code_execute, web_search, etc.)
- Agent decides freely: which tools to call, execution order, when to stop
- Same task → different execution paths → unpredictable results
- Low **fidelity** (behavioral consistency, Westworld reference)

**Challenges:**
1. Difficult to debug and reproduce issues
2. Cannot guarantee consistency
3. User trust issues due to unpredictability
4. No visibility into what agent will do

---

## Solution: Skills → Workflows

### Core Idea

Gradually distill skills into deterministic workflows:

```
Phase 1: Deep Agent + Skills (free exploration)
    ↓ Observe which skills are frequently used
Phase 2: Distill common skills → Workflows (pattern crystallization)
    ↓
Phase 3: Agent calls Workflows + remaining Skills (hybrid mode)
    ↓
Phase 4: Gradually distill more skills
    ↓
Final: Most behaviors become deterministic Workflows
```

### Benefits

1. **High Fidelity** — Same workflow = same execution path (consistent behavior)
2. **Visibility** — Each skill is a flowchart on canvas
3. **Controllability** — Users can add control points (TOTP, human confirmation)
4. **Reusability** — Workflows can be called by multiple agents
5. **Gradual Evolution** — Skills remain available, nothing breaks

---

## Architecture: Meta Agent + Main Agent

### Dual Agent System

```
┌─────────────────────────────────────────┐
│           Meta Agent (Observer)          │
│  - Monitor Main Agent behavior           │
│  - Identify repeated patterns            │
│  - Distill into Workflows                │
│  - Suggest control points                │
│  - Higher permissions (platform_api)     │
└─────────────┬───────────────────────────┘
              │ Observes + Manages
              ↓
┌─────────────────────────────────────────┐
│          Main Agent (Executor)           │
│  - Uses Skills for free exploration      │
│  - Calls distilled Workflows             │
│  - Produces execution logs               │
└─────────────────────────────────────────┘
```

### Meta Agent Capabilities

**Tools (via platform_api):**
- `GET /api/v1/executions/` — Observe behavior logs
- `GET /api/v1/workflows/` — View existing workflows
- `POST /api/v1/workflows/` — Create new workflows
- `PATCH /workflows/{slug}/nodes/{id}/` — Modify nodes
- `compile_dsl()` — YAML DSL → Workflow
- `skill_to_workflow` — Distill skill descriptions

**Interaction Modes:**
1. **Reactive** — User talks to Meta Agent
   - "What did the agent do yesterday?"
   - "Distill web_research skill into workflow"
   - "Add TOTP to this dangerous workflow"
   
2. **Proactive** — Scheduled task (daily/weekly)
   - Analyze execution logs
   - Identify high-frequency patterns
   - Suggest distillation candidates
   - User approves or ignores

### Meta Agent = Deep Agent Architecture

**Same Deep Agent implementation, different tools:**

```python
# Main Agent tools
tools = [
    run_command,
    code_execute,
    web_search,
    calculator,
    # ... execution tools
]

# Meta Agent tools
tools = [
    platform_api,      # REST API access
    create_agent_user, # Create API keys
    workflow_create,   # YAML DSL → workflow
    skill_to_workflow, # Distill skills
    # ... management tools
]
```

---

## `skill_to_workflow` Implementation

### The Philosophical Question

```
skill_to_workflow
  → Transforms skill into workflow
  → Itself can be a skill or workflow
  → If workflow, can it distill itself?
```

**Pragmatic Answer:**

For determinism and stability, `skill_to_workflow` should be a **Workflow**:

```
Workflow: skill_to_workflow
  1. code: Read skill.md
  2. agent: Analyze intent + Generate YAML DSL
  3. code: Validate YAML format
  4. [human_confirmation]: User review (optional)
  5. platform_api: Create workflow
```

### Skill Types

**1. Atomic Skill (single tool)**
```
web_search → Workflow: single node
```

**2. Composite Skill (tool combination)**
```
web_research:
  - search
  - extract
  - summarize
  → Workflow: multi-node flow
```

### Safety Control Points

Users can add control points to distilled workflows:

```
Workflow: file_cleanup
  - code: Scan old files
  - code: Generate deletion list
  - TOTP verification ← User added
  - code: Execute deletion
  - human_confirmation ← User added
  - code: Clean database
```

**Control Node Types:**
- `totp_verification` — Time-based OTP verification
- `human_confirmation` — Manual approval

---

## Relationship to Existing Roadmaps

### Launch Roadmap (v0.2.0 → v0.4.0)

- **v0.2.0 (Mar 7)**: `human_confirmation` node already exists ✓
- **v0.3.0**: Message gateway, Docker artifacts
- **v0.4.0**: Multi-tenant SaaS

**This feature could be:**
- v0.3.x enhancement (skill_to_workflow tool)
- v0.4.x feature (Meta Agent automation)

### Self-Evolving Agent Roadmap

This discussion directly implements:

- **Phase 1: Memory** — Meta Agent reads execution logs
- **Phase 2: Self-Awareness** — Main Agent knows its workflows
- **Phase 3: Protection** — Users/system add control points
- **Phase 4: Pattern Saving** — Meta Agent distills skills
- **Phase 5: Guided Learning** — Meta Agent asks when uncertain

**Key Insight:** 
Skill distillation is the "crystallization" mechanism mentioned in the roadmap — successful patterns become reusable blocks.

---

## Implementation Path

### Phase 1: Manual Distillation (1-2 weeks)

1. **`skill_to_workflow` tool**
   - Input: skill name/description
   - Output: YAML DSL
   - Call `compile_dsl()` to create workflow

2. **Basic workflow template**
   - Read skill.md
   - LLM generate DSL
   - Validate + create

3. **User control**
   - Review DSL before creation
   - Edit on canvas
   - Add control points

### Phase 2: Meta Agent Reactive Mode (2-3 weeks)

1. **Meta Agent setup**
   - Deep agent with platform_api
   - System prompt: administrator role
   - Can observe logs, create workflows

2. **Interactive commands**
   - "Show me agent's recent behavior"
   - "Distill this skill"
   - "Add safety check"

### Phase 3: Meta Agent Proactive Mode (3-4 weeks)

1. **Scheduled analysis**
   - Daily/weekly job
   - Pattern recognition (frequency + success rate)
   - Suggest distillation candidates

2. **Approval workflow**
   - Meta suggests
   - User reviews
   - Approve or ignore

### Phase 4: Safety Enhancements (1-2 weeks)

1. **`totp_verification` node type**
2. **Audit logging for Meta Agent**
3. **Permission boundaries**
4. **Rollback mechanism**

---

## Key Insights

1. **Same Architecture, Different Roles** — Meta and Main agents use the same Deep Agent implementation, just different tools
2. **Gradual Evolution** — Skills don't disappear, they crystallize over time
3. **User in Control** — Users can see, edit, and constrain agent behavior
4. **Determinism from Workflow** — `skill_to_workflow` itself must be a workflow for predictability
5. **Recursive Beauty** — Meta Agent manages Main Agent using the same platform it manages
6. **Platform API is the Key** — Existing `platform_api` tool already gives Meta Agent full management capability

---

## Next Steps

1. **Decide timeline** — v0.3.x or v0.4.x?
2. **Design `skill_to_workflow.yaml`** — First workflow template
3. **Define Meta Agent permissions** — What can/cannot modify
4. **Create `totp_verification` node** — Safety control component
5. **Update roadmap** — Add this as a track or phase

---

## Open Questions

1. Should Meta Agent be able to modify running workflows, or only create new ones?
2. What's the rollback strategy if Meta Agent makes a bad decision?
3. How to handle skill versioning when distilling?
4. Should there be a Meta-Meta Agent for auditing Meta Agent?

---

## Files Referenced

- `docs/roadmap/launch_roadmap_v0.2_to_v0.4.md`
- `docs/architecture/self_aware_self_evolving_agent_platform_roadmap.md`
- `docs/architecture/workflow_dsl_spec.md`
- `platform/services/dsl_compiler.py`
- `platform/components/platform_api.py`

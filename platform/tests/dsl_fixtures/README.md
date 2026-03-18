# DSL Test Fixtures

Minimal **topology-only** test set with paired Gherkin behavior specs.

## Prompt Chain Flow

```
┌─────────────────────────────────────────────────────────────┐
│  Step1: Architect Output                                     │
│      topology.yaml + behavior.feature                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Step2: Cross-Examination                                    │
│      - Validate topology vs behavior                         │
│      - Check all node types exist                            │
│      - Identify content requirements                         │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
┌─────────────────────────┐     ┌─────────────────────────────┐
│  All nodes exist        │     │  Missing integration        │
│          ↓              │     │          ↓                  │
│  Step3: Populate yaml   │     │  Route to ERROR NODE        │
│      - Generate prompts │     │      - Log missing type     │
│      - Generate code    │     │      - Create ticket        │
│      - Output: final.yaml│    │      - Human intervention   │
└─────────────────────────┘     └─────────────────────────────┘
                                        │
                                        ▼
                              (Future: #169 Custom Node Creation)
```

## Structure

```
dsl_fixtures/
├── 01_complete_agent/
│   └── Step1/
│       ├── topology.yaml       ← DSL (nodes, edges, routing)
│       └── behavior.feature    ← Gherkin (what it should do)
├── 02_branching/
│   └── Step1/
├── 03_loop_filter/
│   └── Step1/
├── 04_memory_subworkflow/
│   └── Step1/
├── 05_deep_agent_meta/
│   └── Step1/
├── 06_error_routing/
│   └── Step1/
└── README.md
```

## Step Outputs

| Step | Input | Output | Purpose |
|------|-------|--------|---------|
| **Step1** | User intent | `topology.yaml` + `behavior.feature` | Architect produces structure + spec |
| **Step2** | Step1 | `validation.md` | Cross-examine topology vs behavior |
| **Step3** | Step1 + Step2 | `populated.yaml` | Fill content fields from behavior spec |

## Key Principles

### 1. DSL = Topology Only
- Node types and IDs
- Edge connections
- Routing rules (switch conditions)  
- `discover: true` for model (uses user's credentials)
- **No prompts, no code snippets**

### 2. Gherkin = Behavior Spec
- What each node should DO
- Expected inputs/outputs
- Cross-verifies the topology

### 3. Content Generated from Gherkin
Builder uses behavior.feature to generate:
- `agent.prompt` — from scenario descriptions
- `code.snippet` — from expected behavior
- `human.message` — from user interaction scenarios

## Content Field Mapping

| Step Type | Content Field | Generated From |
|-----------|---------------|----------------|
| `agent` | `prompt` | Gherkin scenarios |
| `code` | `snippet` | Expected behavior |
| `human` | `message` | User prompts in scenarios |
| `transform` | `template` | Output format scenarios |
| `http` | `url`, `body` | API call scenarios |

## Missing Integration Handling

When Step2 detects a missing node type:

1. **Current**: Route to error node
   - Log the missing `component_type`
   - Create GitHub issue automatically
   - Require human intervention

2. **Future** (see #169): Custom Node Creation Workflow
   - Generate node_spec.yaml
   - Generate node_behavior.feature
   - Generate 3 implementation files
   - Uses existing `ToolCredential` for credentials

## Coverage

| # | Scenario | Triggers | Nodes | Edges |
|---|----------|----------|-------|-------|
| 1 | complete_agent | manual | agent, code | direct, llm, tool |
| 2 | branching | chat | switch, wait, human | conditional |
| 3 | loop_filter | manual | loop, agent | loop_body, loop_return |
| 4 | memory_subworkflow | none | workflow, code | direct |
| 5 | deep_agent_meta | telegram | agent + meta tools | tool |
| 6 | error_routing | manual | http, switch, transform | conditional |

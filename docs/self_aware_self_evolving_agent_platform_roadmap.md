Self-Aware, Self-Evolving Agent Platform
Vision Summary
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  A "Self-Evolving Lego" system where:                       │
│                                                             │
│  • Agent assembles workflows from nodes at runtime          │
│  • Human watches construction on visual canvas              │
│  • Agent learns from outcomes, remembers patterns           │
│  • Agent can modify itself (with guardrails)                │
│  • Agent asks human when uncertain                          │
│  • Successful patterns crystallize into reusable blocks     │
│  • Complexity emerges organically over time                 │
│                                                             │
└─────────────────────────────────────────────────────────────┘
Core Capabilities
CapabilityDescriptionSelf-AwarenessAgent knows its own config, structure, capabilities, historySelf-EvaluationAgent can assess what's working and what isn'tSelf-ModificationAgent can change its own workflows and configGuided LearningAgent asks human when uncertain, learns from answersMemoryAgent remembers episodes, facts, and proceduresProtectionGuardrails prevent agent from breaking itself

What You Have
✓ trigger_telegram      - Receive messages
✓ simple_agent          - LLM reasoning
✓ ai_model              - Model configuration
✓ Visual canvas         - See workflows
✓ WebSocket             - Real-time updates
✓ Workflows trigger workflows
What You Need (Prioritized)
Phase 1: Foundation (Weeks 1-3)
Goal: Agent can remember and execute code
PriorityNode/ComponentPurposeP0memory_readRetrieve stored knowledgeP0memory_writeStore learned knowledgeP0code_executeRun code agent writesP0Memory tablesEpisodes, Facts, Procedures
Outcome: Agent can learn and persist knowledge across executions.

Phase 2: Self-Awareness (Weeks 4-5)
Goal: Agent can see itself
PriorityNode/ComponentPurposeP0workflow_inspectSee own structureP0AgentSelfModelStructured self-knowledgeP1Execution loggingRecord what happenedP1Success/failure trackingKnow what works
Outcome: Agent can answer "What am I? What can I do? What's my history?"

Phase 3: Protection (Weeks 6-7)
Goal: Agent cannot break itself
PriorityComponentPurposeP0InvariantsHardcoded limits agent cannot see/changeP0Permission matrixWhat agent can/cannot modifyP0Circuit breakersAuto-stop on repeated failuresP1Rate limitsPrevent runaway executionP1Cost trackingBudget enforcementP1Audit logImmutable record of all actions
Outcome: Agent operates safely within defined boundaries.

Phase 4: Self-Modification (Weeks 8-10)
Goal: Agent can change itself (safely)
PriorityNode/ComponentPurposeP0workflow_modifyAdd/remove/rewire nodesP0Approval systemHuman approves risky changesP1Config adjustmentAgent tunes own temperature, etc.P1Pattern savingSave successful workflows
Outcome: Agent can propose and apply changes to itself.

Phase 5: Guided Learning (Weeks 11-13)
Goal: Agent asks when stuck, learns from answers
PriorityComponentPurposeP0Confidence scoringKnow when uncertainP0Human guidance requestAsk questions with optionsP0Learning persistenceSave human teachingsP1Conversation-based teachingMulti-turn teaching flowP1Preference extractionLearn from corrections
Outcome: Agent improves through human interaction.

Phase 6: Live Visibility (Weeks 14-16)
Goal: Human sees everything in real-time
PriorityComponentPurposeP0Execution streamingWatch nodes execute liveP0Canvas status colorsSee running/success/failedP1Pause/resumeIntervene mid-executionP1Edit mid-flightChange nodes during executionP2Agent proposals UISee what agent wants to change
Outcome: Full transparency into agent behavior.

Phase 7: Emergence (Weeks 17+)
Goal: Complexity grows organically
PriorityComponentPurposeP1Self-reflection workflowPeriodic self-evaluationP1Pattern compositionCombine patterns into larger onesP2Habit formationFrequently-used patterns become automaticP2Priority emergenceLearn task importance from usageP2Memory consolidationExtract facts from episodes
Outcome: Agent evolves toward human-like executive function.

Architecture Summary
┌─────────────────────────────────────────────────────────────┐
│                     PROTECTION LAYER                        │
│  (Invariants, Permissions, Circuit Breakers, Audit)         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                 AGENT SELF-MODEL                     │   │
│  │  • Config (model, temperature, limits)              │   │
│  │  • Structure (nodes, edges, sub-agents)             │   │
│  │  • Capabilities (tools available)                   │   │
│  │  • Memory (facts, procedures, episodes)             │   │
│  │  • History (successes, failures, corrections)       │   │
│  └─────────────────────────────────────────────────────┘   │
│                           │                                 │
│                           ▼                                 │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                 EVOLUTION TOOLS                      │   │
│  │  • workflow_inspect    • memory_read/write          │   │
│  │  • workflow_modify     • code_execute               │   │
│  │  • request_guidance    • self_evaluate              │   │
│  └─────────────────────────────────────────────────────┘   │
│                           │                                 │
│                           ▼                                 │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                 EXECUTION ENGINE                     │   │
│  │  • Safe executor (all checks)                       │   │
│  │  • Live streaming to canvas                         │   │
│  │  • Approval workflows                               │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│                      MEMORY LAYER                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │  Episodes   │  │    Facts    │  │ Procedures  │        │
│  │  (raw logs) │  │ (knowledge) │  │  (skills)   │        │
│  └─────────────┘  └─────────────┘  └─────────────┘        │
└─────────────────────────────────────────────────────────────┘

Data Model Summary
Memory (3 tables)
TablePurposeGrowth RateMemoryEpisodeRaw execution logsFast (every run)MemoryFactExtracted knowledgeSlow (consolidated)MemoryProcedureReusable patternsSlowest (learned)
Protection (4 tables)
TablePurposeWho Can ModifyAuditLogImmutable event recordNo one (append-only)CircuitBreakerFailure trackingSystem onlyRateLimiterRequest limitsAdmin onlyCostTrackerSpending limitsAdmin only
Approvals (1 table)
TablePurposePendingApprovalAgent requests awaiting human decision

Node Dependency Graph
HAVE NOW
    │
    ├── trigger_telegram
    ├── simple_agent  
    └── ai_model
           │
           │ Phase 1 (Foundation)
           ▼
    ┌──────────────────┐
    │ memory_read      │
    │ memory_write     │
    │ code_execute     │
    └──────────────────┘
           │
           │ Phase 2 (Self-Awareness)
           ▼
    ┌──────────────────┐
    │ workflow_inspect │
    └──────────────────┘
           │
           │ Phase 4 (Self-Modification)
           ▼
    ┌──────────────────┐
    │ workflow_modify  │
    └──────────────────┘
           │
           │ BOOTSTRAP ACHIEVED
           │ Agent can now request what it needs
           ▼
    ┌──────────────────┐
    │ http_request     │ ← Agent asks for this
    │ file_read/write  │ ← Agent asks for this
    │ search           │ ← Agent asks for this
    │ ...              │ ← Agent asks for this
    └──────────────────┘

The Bootstrap Moment
After Phase 4, the agent reaches bootstrap capability:
Agent: "I need to fetch weather data but I don't have HTTP capability"
       ↓
Agent: workflow_inspect() → sees no http_request node
       ↓
Agent: workflow_modify("add_node", {type: "http_request"})
       ↓
System: "Requires approval"
       ↓
Human: "Approved"
       ↓
Agent: Now has http_request capability
       ↓
Agent: memory_write("I can now make HTTP requests")
From this point, the agent can request and grow its own capabilities. You build what it asks for, or it writes code to compensate.

Evaluation Signals (How Agent Knows "Good")
LayerSignalWhenImmediateSuccess/failure, errorsDuring executionSessionHuman rating, correctionsEnd of interactionImplicitReuse, interventionsOver timeOutcomeExternal success signalsDays later
No single signal is enough. Combine them:
pythonscore = (
    success_rate * 0.3 +
    (1 - intervention_rate) * 0.2 +
    human_rating * 0.3 +
    reuse_count * 0.2
)
```

---

## Minimum Viable Self-Evolution
```
┌─────────────────────────────────────────┐
│         SELF-ITERATION LOOP             │
├─────────────────────────────────────────┤
│                                         │
│  1. OBSERVE                             │
│     └─ Log execution (automatic)        │
│                                         │
│  2. EVALUATE                            │
│     └─ Score outcomes (automatic)       │
│                                         │
│  3. MODIFY                              │
│     └─ Save pattern / request change    │
│                                         │
│         ↓                               │
│     Loop forever                        │
│                                         │
└────────────────────────────────────────┘
```

---

## 16-Week Roadmap

| Week | Phase | Deliverable |
|------|-------|-------------|
| 1-2 | Foundation | Memory tables + read/write nodes |
| 3 | Foundation | code_execute node (sandboxed) |
| 4-5 | Self-Awareness | workflow_inspect + AgentSelfModel |
| 6 | Protection | Invariants + Permission matrix |
| 7 | Protection | Circuit breakers + Rate limits |
| 8-9 | Self-Modification | workflow_modify + Approval flow |
| 10 | Self-Modification | Pattern saving |
| 11-12 | Guided Learning | Confidence scoring + Human guidance |
| 13 | Guided Learning | Learning persistence |
| 14-15 | Live Visibility | Execution streaming + Canvas status |
| 16 | Live Visibility | Pause/resume + Edit mid-flight |
| 17+ | Emergence | Self-reflection + Pattern composition |

---

## First Sprint (Weeks 1-2)

Start here:
```
1. Create memory tables:
   - MemoryEpisode
   - MemoryFact  
   - MemoryProcedure

2. Create memory_read node:
   - Key lookup
   - Query search
   - Returns found/not found

3. Create memory_write node:
   - Store facts
   - Update existing
   - Track source

4. Wire into simple_agent as tools:
   - Agent can call memory_read
   - Agent can call memory_write

5. Auto-log episodes:
   - After each execution
   - Record inputs, outputs, success
End of Week 2: Agent remembers things across conversations.

Success Criteria
MilestoneCriteriaMemory worksAgent recalls facts from previous sessionsSelf-awareAgent accurately describes its own structureProtectedAgent cannot delete its own protectionSelf-modifyingAgent successfully adds a new node (with approval)LearningAgent asks question, human answers, agent remembersVisibleHuman watches execution in real-time on canvasEvolvingAgent proposes improvement based on failure pattern

This is your map. Start with memory (Phase 1), because without memory there is no learning. Everything else builds on that foundation.

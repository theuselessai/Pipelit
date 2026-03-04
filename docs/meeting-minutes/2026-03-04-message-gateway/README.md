# Meeting: Message Gateway & Model Switching Design (2026-03-04)

**Participants:** Claude (Deep Agent)  
**Topic:** Understanding OpenCode's message gateway design and reusability in Pipelit  
**Outcome:** Comprehensive analysis of message gateway architecture with code reusability assessment

## Overview

This meeting explored how to implement a message gateway in Pipelit to handle:
- Multiple input sources (Telegram, Email, Slack)
- Multiple output models (Claude, GLM, MiniMax)
- Seamless mid-conversation model switching without data loss

## Key Findings

- **70% of code already exists** in Pipelit (services/llm.py, services/context.py, services/state.py)
- **30% needs to be built** (~600 lines of new code)
- **1-2 week implementation** timeline with clear 5-phase roadmap
- LangChain's `configurable_alternatives` pattern solves runtime model switching
- "Store everything, adapt on read" principle prevents data loss across model switches

## Documents

1. **[01-meeting-summary.md](01-meeting-summary.md)** — Overview of problem, solution architecture, LangChain support, and implementation roadmap
2. **[02-code-reusability-matrix.md](02-code-reusability-matrix.md)** — Detailed module-by-module analysis with code examples and 5-phase implementation plan
3. **[03-gateway-architecture.md](03-gateway-architecture.md)** — Technical architecture design including message flow, state transitions, configuration, and performance

## Next Steps

1. Review architecture with team
2. Decide on Phase 1 implementation timing
3. Allocate resources for InputAdapter and ModelRouter development
4. Begin integration with Pipelit workflow execution

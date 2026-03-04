# Meeting Summary: Message Gateway & Model Switching

**Date:** March 4, 2026  
**Participants:** Yao, Claude (Deep Agent)  
**Topic:** Understanding OpenCode's message gateway design and reusability in Pipelit

---

## Context

You discovered that OpenCode made a smart architectural decision around model switching mid-conversation. Goal: understand why and how to implement a message gateway in Pipelit.

---

## Problem Statement

**Multiple challenges:**
1. Multiple input sources: Telegram, Email, Slack
2. Multiple output models: Claude, GLM, MiniMax
3. Mid-conversation model switching causes: signature mismatches, checkpoint incompatibility
4. Skills send intermediary messages via CLI (curl/bash) — no standardization

---

## Solution: Message Gateway

A **message gateway** normalizes messages from any input source, stores them in a canonical format, and routes them to any output model — enabling seamless model switching without data loss.

### 4-Layer Architecture

1. **InputAdapters** → normalize Telegram/Email/Slack to LangChain messages
2. **Canonical Message Store** → hold everything in normalized format
3. **ModelRouter** → use LangChain's configurable_alternatives for runtime switching
4. **OutputAdapters** → route responses back to original transport

---

## LangChain Native Support

LangChain already provides all the building blocks:
- `BaseChatModel` interface — all providers implement the same API
- `Runnable` protocol — universal `invoke()` method
- `configurable_alternatives` pattern — runtime model switching
- Message types (HumanMessage, AIMessage) — normalized format

**Key caveats:**
- Message history not automatically transferred — you manage it explicitly
- Tool schemas/prompts may need per-model adjustment
- Token limits differ — truncation logic needs updating

---

## Code Reusability in Pipelit

### Highly Reusable (95%) ✅

1. **services/llm.py**
   - `create_llm_from_db()` → Instantiate BaseChatModel from DB
   - `_sanitize_message_content()` → **Critical:** Strips empty text blocks (GLM compatibility)
   - Use as-is, no changes needed

2. **services/context.py**
   - `get_context_window()` → Model name → context window lookup
   - `trim_messages_for_model()` → Trim to fit context, perfect for "store all, trim on read"
   - Use as-is, no changes needed

3. **services/state.py**
   - `WorkflowState(MessagesState)` → Extends LangGraph's canonical format
   - `serialize/deserialize_state()` → Redis storage helpers
   - Ideal for canonical message store

### Mostly Reusable (70%) ⚠️

4. **resolve_llm_for_node()** pattern
   - Logic is solid; just change input source (node config → session config)
   
5. **SanitizedChatOpenAI** wrapper
   - Strips empty blocks before API calls
   - Reusable with same pattern

### Needs to Be Built (30%) ❌

1. **InputAdapter interface** (~200 lines)
   - TelegramAdapter, EmailAdapter, SlackAdapter
   - Convert raw input → HumanMessage with metadata

2. **configurable_alternatives routing** (~150 lines)
   - ModelRouter class with decision logic
   - Based on: source, conversation length, explicit override

3. **Gateway dispatcher** (~250 lines)
   - Orchestrates: input → store → routing → output
   - Session lifecycle management

**Total new code: ~600 lines** (1-2 week implementation)

---

## Key Insights

1. **70% of code already exists** — focus on assembly
2. **Separation of concerns** — gateway doesn't need to know workflow logic
3. **Sanitization is critical** — empty blocks accumulate across provider switches
4. **Store everything, adapt on read** — never lose data on model switch
5. **Message gateway is about stability** — removes brittleness from model switching

---

## Implementation Roadmap

- **Phase 1:** Foundation (reuse existing code)
- **Phase 2:** Input/output adapters
- **Phase 3:** Model router with configurable_alternatives
- **Phase 4:** Gateway dispatcher
- **Phase 5:** Testing & integration

---

## Next Steps

1. Review summary with team
2. Decide: Phase 1 timing
3. Allocate resources for adapter development
4. Plan integration with Pipelit workflow

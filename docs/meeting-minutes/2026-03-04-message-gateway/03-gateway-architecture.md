# Message Gateway Architecture

## Quick Overview

The message gateway solves mid-conversation model switching with 4 components:

1. **Input Adapters** — Normalize Telegram/Email/Slack → LangChain HumanMessage
2. **Canonical Store** — Hold all messages in normalized format (Redis-backed)
3. **Model Router** — Use LangChain's `configurable_alternatives` to pick model
4. **Output Adapters** — Convert AIMessage back to original transport

---

## Core Principle: Store Everything, Adapt on Read

- **Write:** Append all messages to canonical store (never lose data)
- **Read:** Trim to fit model's context window BEFORE invocation
- **Result:** Seamless model switching without data loss

---

## Message Flow

```
Input (Telegram update)
    ↓
TelegramAdapter.to_langchain_message()
    ↓
HumanMessage(
    content="user text",
    additional_kwargs={"source": "telegram", "chat_id": 123}
)
    ↓
GatewaySession.messages.append()
    ↓
redis set session:{id} (serialized)
    ↓
ModelRouter.route() → "glm" (decision logic)
    ↓
trim_messages_for_model(messages, "glm-4")
    ↓
_sanitize_message_content() (strip empty blocks)
    ↓
llm.with_config(configurable={"llm": "glm"}).invoke(messages)
    ↓
AIMessage (response)
    ↓
Output adapter → Send back to Telegram
    ↓
Persist AIMessage to session
```

---

## State Transitions

```
User sends message
    ↓
GatewaySession created/loaded
    ↓
Message appended to session.messages
    ↓
Model router decides which model to use
    ↓
LLM invoked (with model switching)
    ↓
Response appended to session
    ↓
Session persisted to Redis
```

---

## Configuration Example

**Routing logic (simple if/else):**
```python
def route(message: HumanMessage, session) -> str:
    source = message.additional_kwargs.get("source")
    
    if session.explicit_model:  # User override
        return session.explicit_model
    
    if source == "email":
        return "claude"  # Long context needed
    
    if source == "telegram" and len(session.messages) < 3:
        return "glm"  # Fast & cheap for short
    
    return "claude"  # Default
```

**Model switching (LangChain pattern):**
```python
llm = ChatAnthropic().configurable_alternatives(
    ConfigurableField(id="llm"),
    default_key="claude",
    glm=ChatOpenAI(model="glm-4"),
    minimax=ChatOpenAI(model="minimax-01"),
)

# Switch at runtime
response = llm.with_config(
    configurable={"llm": "glm"}
).invoke(messages)
```

---

## Performance

| Operation | Latency |
|-----------|---------|
| Input adapter | ~5ms |
| Session lookup | ~10ms |
| Message trimming | ~50ms |
| Sanitization | ~5ms |
| Model routing | ~2ms |
| LLM invocation | ~2000ms |
| Output adapter | ~5ms |
| **Total (non-LLM)** | **~77ms** |
| **Total (with LLM)** | **~2077ms** |

---

## Error Handling

**Empty text blocks (GLM compatibility):**
```
Accumulate in conversation memory across provider switches
→ _sanitize_message_content() strips them before API calls
```

**Context window overflow:**
```
Message list too large
→ trim_messages_for_model() keeps recent messages
→ Always preserves system message
```

**Provider unavailable:**
```
Model invocation fails
→ Try fallback model (Claude → GLM → MiniMax)
```

**Concurrent sessions:**
```
Multiple users in same session
→ Redis locks on session:{id}
```

---

## Key Reusable Code

**From services/llm.py:**
- `create_llm_from_db()` — Instantiate any model
- `_sanitize_message_content()` — Strip empty blocks
- **Use as-is, no changes**

**From services/context.py:**
- `get_context_window()` — Model → context size
- `trim_messages_for_model()` — Trim to fit
- **Use as-is, no changes**

**From services/state.py:**
- `WorkflowState(MessagesState)` — Extend for session
- `serialize/deserialize_state()` — Redis storage
- **Use as-is, extend slightly**

---

## New Code Needed (~600 lines)

**InputAdapters (~200 lines):**
- TelegramAdapter, EmailAdapter, SlackAdapter
- Convert raw input → HumanMessage with metadata

**ModelRouter (~150 lines):**
- Build configurable_alternatives chain
- Implement routing decision logic

**Gateway Dispatcher (~250 lines):**
- Orchestrate input → store → routing → output
- Session lifecycle management

---

## Files to Create

```
services/gateways/
├── __init__.py
├── adapters.py         # InputAdapter + OutputAdapter implementations
├── router.py           # ModelRouter class
└── gateway.py          # PipelitGateway dispatcher
```

---

## Integration Points

**With existing Pipelit:**
1. Use credential system (LLMProviderCredential)
2. Use conversation memory checkpointers
3. Route through intermediary-delivery skill
4. Integrate with workflow execution

---

## Monitoring

**Track these metrics:**
- Messages processed per model
- Model switch frequency
- Message trim frequency
- Sanitization corrections
- Error rates per provider

**Log with context:**
- session_id
- source (telegram/email/slack)
- model_selected
- latency_ms
- trim_applied

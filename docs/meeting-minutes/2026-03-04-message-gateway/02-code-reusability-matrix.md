# Code Reusability Matrix: Message Gateway Implementation

## Summary

| Module | Reusability | Status | Lines | Effort |
|--------|------------|--------|-------|--------|
| services/llm.py | 95% | ✅ Reuse as-is | 200 | Trivial |
| services/context.py | 95% | ✅ Reuse as-is | 100 | Trivial |
| services/state.py | 90% | ✅ Extend slightly | 150 | Easy |
| InputAdapters | 0% | ❌ Build new | 200 | Easy |
| ModelRouter | 20% | ⚠️ Build with framework | 150 | Medium |
| Gateway Dispatcher | 10% | ❌ Build new | 250 | Medium |
| **Total** | **70%** | | **1050** | **1-2 weeks** |

---

## Detailed Analysis

### 1. services/llm.py (95% Reusable)

**Current use:** Instantiate LLM from DB credential

**Gateway use:** Create LLM instance in ModelRouter

**Reusable functions:**
- `create_llm_from_db(credential, model_name, **kwargs)` — **Use as-is**
- `_sanitize_message_content(messages)` — **Use as-is** (critical for GLM)
- `_make_sanitized_chat_openai()` — **Use as-is**

**Provider support:**
- ✅ openai, anthropic, glm, openai_compatible
- ❓ minimax (verify if openai_compatible covers it)

**Changes needed:** None

---

### 2. services/context.py (95% Reusable)

**Current use:** Trim messages before agent execution

**Gateway use:** Trim on read from canonical store

**Reusable functions:**
- `get_context_window(model_name)` — **Use as-is**
- `trim_messages_for_model(messages, model_name, **kwargs)` — **Use as-is**

**Models covered:**
- ✅ Claude (all versions: 200K)
- ✅ GPT-4 (4K → 128K)
- ✅ o1/o3 (128K → 200K)
- ❓ GLM models (need to add)
- ❓ MiniMax models (need to add)

**Changes needed:**
1. Add GLM models to `MODEL_CONTEXT_WINDOWS`
2. Add MiniMax models to `MODEL_CONTEXT_WINDOWS`

---

### 3. services/state.py (90% Reusable)

**Current use:** LangGraph state for workflow execution

**Gateway use:** Extend for session state management

**Reusable components:**
- `WorkflowState(MessagesState)` — Extend with gateway fields
- `add_messages(left, right)` — **Use as-is**
- `serialize_state()` / `deserialize_state()` — **Use as-is**

**New fields for GatewaySession:**
```python
class GatewaySession(MessagesState):
    session_id: str                  # Unique identifier
    source: str                      # Input source
    thread_id: str                   # Multi-conversation tracking
    explicit_model: str | None       # User override
    model_used: str                  # Which model last responded
    produced_by: dict[str, str]      # Message ID → model
```

**Changes needed:**
1. Create `GatewaySession` extending `WorkflowState`
2. Add session-specific fields

---

### 4. InputAdapters (New Code: ~200 lines)

**File:** `services/gateways/adapters.py`

**New code:**
```python
from abc import ABC, abstractmethod
from langchain_core.messages import HumanMessage, AIMessage

class InputAdapter(ABC):
    @abstractmethod
    def to_langchain_message(self, raw_input) -> HumanMessage:
        pass

class TelegramAdapter(InputAdapter):
    def to_langchain_message(self, update) -> HumanMessage:
        return HumanMessage(
            content=update.message.text,
            additional_kwargs={
                "source": "telegram",
                "chat_id": update.message.chat_id,
                "user_id": update.message.from_user.id,
            }
        )

class EmailAdapter(InputAdapter):
    def to_langchain_message(self, email) -> HumanMessage:
        return HumanMessage(
            content=f"Subject: {email.subject}\n\n{email.body}",
            additional_kwargs={
                "source": "email",
                "from": email.sender,
                "thread_id": email.thread_id,
            }
        )

class SlackAdapter(InputAdapter):
    def to_langchain_message(self, message) -> HumanMessage:
        return HumanMessage(
            content=message.text,
            additional_kwargs={
                "source": "slack",
                "channel": message.channel,
                "user": message.user,
                "ts": message.ts,
            }
        )

class SkillMessageAdapter:
    @staticmethod
    def status_update(text: str) -> AIMessage:
        return AIMessage(
            content=text,
            additional_kwargs={"type": "status_update"}
        )
    
    @staticmethod
    def approval_gate(text: str) -> AIMessage:
        return AIMessage(
            content=text,
            additional_kwargs={"type": "approval_gate"}
        )
```

**Effort:** Easy — straightforward data transformation

---

### 5. ModelRouter (Mostly New: ~150 lines)

**File:** `services/gateways/router.py`

**Reuses (20%):**
- `create_llm_from_db()` from services/llm.py
- `get_context_window()` from services/context.py
- `trim_messages_for_model()` from services/context.py

**New code (80%):**
```python
from langchain_core.runnables import ConfigurableField
from services.llm import create_llm_from_db
from services.context import trim_messages_for_model

class ModelRouter:
    def __init__(self, db_session):
        self.db = db_session
        self.llm = self._build_configurable_llm()
    
    def _build_configurable_llm(self):
        """Build LLM with configurable_alternatives."""
        # Get credentials
        claude_cred = self.db.query(...).first()
        glm_cred = self.db.query(...).first()
        minimax_cred = self.db.query(...).first()
        
        # Create base + alternatives
        llm = create_llm_from_db(claude_cred, "claude-opus-4")
        return llm.configurable_alternatives(
            ConfigurableField(id="llm"),
            default_key="claude",
            glm=create_llm_from_db(glm_cred, "glm-4"),
            minimax=create_llm_from_db(minimax_cred, "minimax-01"),
        )
    
    def route(self, message: HumanMessage, session) -> str:
        """Decide which model to use."""
        source = message.additional_kwargs.get("source")
        
        # Rule 1: User override
        if session.explicit_model:
            return session.explicit_model
        
        # Rule 2: Source-based
        if source == "email":
            return "claude"  # Long context
        if source == "telegram" and len(session.messages) < 3:
            return "glm"  # Fast & cheap
        
        return "claude"  # Default
    
    def invoke(self, message: HumanMessage, session) -> AIMessage:
        """Route to model and invoke."""
        model_key = self.route(message, session)
        messages = trim_messages_for_model(
            session.messages + [message],
            model_name=self._model_key_to_name(model_key),
        )
        return self.llm.with_config(
            configurable={"llm": model_key}
        ).invoke(messages)
```

**Effort:** Medium — LangChain's configurable_alternatives is key

---

### 6. Gateway Dispatcher (Mostly New: ~250 lines)

**File:** `services/gateways/gateway.py`

**Reuses (10%):**
- Patterns from existing code
- Session serialization from services/state.py

**New code (90%):**
```python
class PipelitGateway:
    def __init__(self, db_session):
        self.db = db_session
        self.sessions: dict[str, GatewaySession] = {}
        self.adapters = {
            "telegram": TelegramAdapter(),
            "email": EmailAdapter(),
            "slack": SlackAdapter(),
        }
        self.router = ModelRouter(db_session)
    
    def handle(self, source: str, raw_input, session_id: str) -> AIMessage:
        """Process input through gateway."""
        # 1. Normalize input
        message = self.adapters[source].to_langchain_message(raw_input)
        
        # 2. Get or create session
        session = self.sessions.setdefault(
            session_id, GatewaySession(session_id=session_id)
        )
        session.messages.append(message)
        
        # 3. Route to model
        response = self.router.invoke(message, session)
        session.messages.append(response)
        
        # 4. Persist
        self._persist_session(session)
        
        return response
    
    def _persist_session(self, session: GatewaySession):
        """Save to Redis."""
        from services.state import serialize_state
        serialized = serialize_state(session)
        self.redis.set(f"gateway:session:{session.session_id}", serialized)
```

**Effort:** Medium — orchestration logic, session management

---

## Implementation Plan

### Phase 1: Foundation (Day 1)
- [ ] Review existing code in services/llm.py, context.py, state.py
- [ ] Add GLM/MiniMax to context window mappings
- [ ] Plan GatewaySession extension

### Phase 2: Adapters (Day 2-3)
- [ ] Create InputAdapter ABC
- [ ] Implement Telegram, Email, Slack adapters
- [ ] Unit tests per adapter

### Phase 3: Router (Day 4-5)
- [ ] Build ModelRouter with configurable_alternatives
- [ ] Define routing rules
- [ ] Test model switching

### Phase 4: Gateway (Day 5-6)
- [ ] Implement PipelitGateway
- [ ] Integration tests (end-to-end)

### Phase 5: Deployment (Day 7)
- [ ] Integrate with Pipelit workflows
- [ ] Performance testing
- [ ] Documentation

---

## Files to Review

Before implementation, review:
1. `/workspace/pipelit/platform/services/llm.py`
2. `/workspace/pipelit/platform/services/context.py`
3. `/workspace/pipelit/platform/services/state.py`
4. `/workspace/pipelit/platform/models/credential.py`
5. `/workspace/pipelit/platform/handlers/telegram.py`

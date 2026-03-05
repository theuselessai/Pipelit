# Development Plan: Pipelit Message Gateway (Phase 2.2, v0.3.0)

**Status:** Planning  
**Created:** 2026-03-04  
**Timeline:** 3-4 weeks  
**Scope:** Multiple input channels + multi-model routing  

## Executive Summary

Implement a **message gateway** for Pipelit to handle:
- **Multiple input sources** (Telegram, Email, Slack)
- **Multiple output models** (Claude, GLM, MiniMax)
- **Mid-conversation model switching** without data loss
- **Session management** across platforms

### Key Metrics
- **Code reusability:** 70% (existing services/llm.py, state.py, context.py)
- **New code:** ~600 lines
- **Implementation timeline:** 3-4 weeks
- **Blockers:** 2 critical items
- **Effort:** 3-4 person-weeks

---

## PART 1: BLOCKERS (1-2 Days)

### Blocker 1: Add GLM/MiniMax to MODEL_CONTEXT_WINDOWS (5 min)

**Problem:** `services/llm.py` only lists Claude models  
**Solution:** Add GLM-4 and MiniMax entries  
**Files:** `/workspace/pipelit/platform/services/llm.py`

```python
MODEL_CONTEXT_WINDOWS = {
    "claude-3-5-sonnet": 200000,
    "glm-4": 128000,
    "minimax-pro": 200000,
}
```

**Testing:** Unit test for all models  
**Timeline:** 5 minutes  
**Success:** All models return valid context windows

---

### Blocker 2: Validate configurable_alternatives Pattern (4-6 hours)

**Problem:** Pattern untested in Pipelit with state serialization  
**Solution:** Create prototype that switches between Claude + GLM  
**Test:** Round-trip invoke → switch → invoke, verify history intact

**Timeline:** 4-6 hours  
**Success Criteria:**
- Round-trip context switch works with real models
- Message history preserved across switches
- Token limits correctly applied per model

---

## PART 2: IMPLEMENTATION (2-3 Weeks)

### Phase 2A: InputAdapters (~200 lines, 2-3 days)

Create unified input abstraction for all channels.

**File Structure:**
```
platform/adapters/
├── input_adapter.py         (60 lines - ABC)
├── telegram_adapter.py      (80 lines)
├── email_adapter.py         (80 lines)
└── slack_adapter.py         (80 lines)
```

**Key Classes:**
- `IncomingMessage` - Unified message format
- `InputAdapter` - Abstract base class
- Concrete implementations for each channel

**Timeline:** 2-3 days  
**Success:** All 3 adapters implement interface, produce unified format

---

### Phase 2B: ModelRouter (~150 lines, 2-3 days)

Implement runtime model switching with configurable_alternatives.

**File Structure:**
```
platform/routers/
├── model_router.py       (130 lines)
└── model_configs.py      (40 lines)
```

**Key Methods:**
- `async invoke(messages, selected_model)` - Route to model
- `async switch_model(conversation_id, new_model, state)` - Mid-conversation switch

**Timeline:** 2-3 days  
**Success:** All 3 models configurable, switching preserves history

---

### Phase 2C: PipelitGateway (~250 lines, 3-4 days)

Main orchestrator coordinating adapters + router + delivery.

**File Structure:**
```
platform/gateway/
├── gateway.py               (250 lines)
├── session_manager.py      (100 lines)
└── message_queue.py        (80 lines)
```

**Key Classes:**
- `SessionManager` - Per-conversation state (Redis)
- `MessageQueue` - Async processing (RQ)
- `PipelitGateway` - Main orchestrator

**Message Flow:**
1. InputAdapter polls → new message
2. Load/create session
3. Invoke ModelRouter
4. Save session
5. Deliver response back to channel

**Timeline:** 3-4 days  
**Success:** Polls all adapters, sessions persist, model switching works

---

## PART 3: INTEGRATION & TESTING (1 Week)

### Phase 3A: Unit Tests
- 85%+ code coverage across all components
- Mock API responses for each adapter
- Test error handling

### Phase 3B: Integration Tests
- E2E Telegram flow
- Model switching with history preservation
- Multi-channel concurrent handling
- Session persistence

### Phase 3C: Documentation
- API guide
- Setup & configuration
- Deployment guide
- Custom adapter tutorial

---

## TIMELINE

### Week 1
- Day 1: Blocker 1 (5 min) + Blocker 2 (1 day)
- Days 2-3: InputAdapters
- Days 4-5: ModelRouter

### Week 2
- Days 1-3: PipelitGateway
- Days 4-5: Unit tests

### Week 3
- Days 1-2: Integration tests
- Days 3-4: Documentation
- Day 5: Review & polish

**Total:** 3-4 weeks (1 developer)

---

## SUCCESS CRITERIA

### Technical
- [ ] All 3 models available via router
- [ ] Mid-conversation switching preserves history
- [ ] Session TTL works (1-hour auto-cleanup)
- [ ] 3 adapters working (Telegram, Email, Slack)
- [ ] 10+ concurrent conversations handled
- [ ] 85%+ test coverage

### Functional
- [ ] Messages from Telegram, Email, Slack
- [ ] Model switching without losing context
- [ ] History accessible via API
- [ ] Response latency < 3 seconds (P95)
- [ ] Zero data loss on model switch

### Production
- [ ] Documentation complete
- [ ] Deployment guide written
- [ ] All edge cases handled
- [ ] Logging & monitoring in place
- [ ] Ready for beta

---

## RISKS & MITIGATIONS

| Risk | Impact | Mitigation |
|------|--------|-----------|
| configurable_alternatives loses context | High | Blocker 2 validates; fallback: explicit serialization |
| GLM/MiniMax rate limits | Medium | Exponential backoff + queue mgmt |
| Session TTL expires mid-conv | Low | Extend on each message |
| Message duplication | Medium | Idempotent IDs + dedup set |
| Adapter API changes | Low | Abstract interface + version pin |
| Concurrent race conditions | Medium | Redis locks + transactions |

---

## CODE REUSABILITY (70%)

### Fully Reuse
- `services/llm.py` - LLM client factory (just add 5 lines)
- `services/state.py` - State serialization
- `services/context.py` - Context extraction
- `services/delivery.py` - Base delivery patterns

### Extract & Generalize
- `handlers/telegram.py` - Move logic to TelegramInputAdapter

### New Code (30%)
- InputAdapter abstraction + 3 implementations (240 lines)
- ModelRouter (130 lines)
- PipelitGateway (250 lines)
- SessionManager (100 lines)
- MessageQueue (80 lines)
- Tests (1000+ lines)

---

## Next Steps

1. **Today:** Review plan, fix Blocker 1
2. **Tomorrow:** Complete Blocker 2 validation
3. **This Week:** Start Phase 2A (InputAdapters)

---

**Status:** Ready for Implementation  
**Last Updated:** 2026-03-04

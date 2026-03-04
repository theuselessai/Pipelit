# Dev Plan: Wire human_confirmation Node in Builder

**Status:** Planned for Phase 1.2 (v0.2.0)
**Effort:** 1-2 days
**Priority:** Critical for Phase 1 completion
**Architect:** Deep Agent

---

## Problem Statement

The `human_confirmation` component exists but is not wired into the workflow builder. When users connect a `human_confirmation` node to downstream nodes, the builder doesn't automatically set the `interrupt_before` flag on those downstream nodes.

**Current State:**
- ❌ Component code exists (`platform/components/human_confirmation.py`)
- ❌ Builder doesn't detect human_confirmation connections
- ❌ interrupt_before flag is not auto-set on downstream nodes
- ❌ Edge deletion doesn't remove interrupt_before flag

**Desired State:**
- ✅ Detect when human_confirmation is connected to a downstream node
- ✅ Auto-set interrupt_before=True on the downstream node
- ✅ Auto-remove interrupt_before when the edge is deleted
- ✅ LangGraph interrupts execution before downstream node
- ✅ Orchestrator can resume/cancel workflow based on user input

---

## Solution Architecture

### Implementation Approach

1. **Add edge hooks to `platform/services/builder.py`:**
   - `on_edge_created()` — detects human_confirmation, sets interrupt_before
   - `on_edge_deleted()` — cleans up interrupt_before if no other sources
   - `has_human_confirmation_source()` — checks for multiple incoming sources

2. **Hook into `platform/api/nodes.py`:**
   - Call `on_edge_created()` after edge is saved
   - Call `on_edge_deleted()` before edge is deleted

3. **Verify `platform/services/orchestrator.py`:**
   - Confirm LangGraph honors interrupt_before
   - Confirm orchestrator sends prompt and handles resume/cancel
   - Add resume handling if missing

### Files to Modify

| File | Changes | Effort |
|------|---------|--------|
| `platform/services/builder.py` | Add 3 methods (~50 lines) | 2 hrs |
| `platform/api/nodes.py` | Add hook calls in 2 endpoints (~10 lines) | 1 hr |
| `platform/services/orchestrator.py` | Verify/add resume logic (~20-50 lines) | 2-3 hrs |
| `tests/test_builder_human_confirmation.py` | Unit tests (~100 lines) | 2 hrs |
| `tests/test_orchestrator_human_confirmation.py` | Integration test (~150 lines) | 2 hrs |

---

## Implementation Steps

### Step 1: Analyze Existing Code (1-2 hours)

**Read these files to understand:**
1. `platform/components/human_confirmation.py` — How it works
2. `platform/services/builder.py` — Workflow graph building
3. `platform/api/nodes.py` — Edge CRUD endpoints
4. `platform/schemas/workflow.py` — Edge and Node models
5. `platform/services/orchestrator.py` — Interrupt handling at runtime

**Key questions:**
- How are edges stored and queried?
- How does interrupt_before work in LangGraph?
- When/how does orchestrator resume paused workflows?
- Are there existing edge hooks we can follow?

### Step 2: Implement Builder Edge Logic (4 hours)

**In `platform/services/builder.py`:**

```python
def on_edge_created(self, workflow_id: str, edge) -> None:
    """Auto-wire human_confirmation downstream nodes."""
    source_node = self.get_node(workflow_id, edge.source_id)
    target_node = self.get_node(workflow_id, edge.target_id)
    
    if source_node.node_type == "human_confirmation":
        target_node.interrupt_before = True
        self.save_node(workflow_id, target_node)

def on_edge_deleted(self, workflow_id: str, edge) -> None:
    """Clean up interrupt_before when edge deleted."""
    target_node = self.get_node(workflow_id, edge.target_id)
    
    # Only remove if no other human_confirmation sources
    if not self.has_human_confirmation_source(workflow_id, edge.target_id):
        target_node.interrupt_before = False
        self.save_node(workflow_id, target_node)

def has_human_confirmation_source(self, workflow_id: str, node_id: str) -> bool:
    """Check if node has any human_confirmation incoming edges."""
    edges = self.db.query(Edge).filter(
        Edge.workflow_id == workflow_id,
        Edge.target_id == node_id
    ).all()
    
    for edge in edges:
        source = self.get_node(workflow_id, edge.source_id)
        if source.node_type == "human_confirmation":
            return True
    return False
```

### Step 3: Hook into API Endpoints (2-3 hours)

**In `platform/api/nodes.py`, modify POST and DELETE:**

```python
@router.post("/workflows/{workflow_id}/edges")
def create_edge(workflow_id: str, edge_create: EdgeCreate, db: Session):
    # Create and save edge
    edge = Edge(**edge_create.dict(), workflow_id=workflow_id)
    db.add(edge)
    db.commit()
    
    # Wire human_confirmation
    builder = WorkflowBuilder(db)
    builder.on_edge_created(workflow_id, edge)
    
    return edge

@router.delete("/workflows/{workflow_id}/edges/{edge_id}")
def delete_edge(workflow_id: str, edge_id: str, db: Session):
    edge = db.query(Edge).filter(Edge.id == edge_id).first()
    
    # Wire cleanup before delete
    builder = WorkflowBuilder(db)
    builder.on_edge_deleted(workflow_id, edge)
    
    # Delete
    db.delete(edge)
    db.commit()
    
    return {"deleted": True}
```

### Step 4: Verify Orchestrator (2 hours)

**In `platform/services/orchestrator.py`:**
- Confirm: When node has `interrupt_before=True`, does execution pause?
- Confirm: Does orchestrator send human_confirmation prompt to user?
- Confirm: Does orchestrator resume with user's choice?

**If resume logic is missing, add:**
```python
def resume_execution(self, workflow_id: str, user_choice: str):
    """Resume workflow after human confirmation."""
    workflow = self.get_workflow(workflow_id)
    
    # Find human_confirmation node that's paused
    hc_node = self.find_paused_human_confirmation(workflow)
    
    # Set resume input based on user choice
    resume_input = {
        "_resume_input": "confirmed" if user_choice == "approve" else "cancelled"
    }
    
    # Resume graph execution
    self.graph.invoke(resume_input)
```

### Step 5: Write Tests (4 hours)

**Unit tests** (`tests/test_builder_human_confirmation.py`):
```python
def test_edge_creation_sets_interrupt_before():
    """Verify interrupt_before is set on downstream node."""
    # Create workflow with hc → code edge
    # Assert code node has interrupt_before=True

def test_edge_deletion_unsets_interrupt_before():
    """Verify interrupt_before is unset when edge deleted."""
    # Delete edge
    # Assert code node has interrupt_before=False

def test_multiple_sources_keeps_interrupt_before():
    """Don't unset if another source feeds the node."""
    # Create: hc1 → code, hc2 → code
    # Delete hc1 edge
    # Assert code still has interrupt_before=True (from hc2)
```

**Integration test** (`tests/test_orchestrator_human_confirmation.py`):
```python
def test_workflow_pauses_and_resumes():
    """Full workflow: execute → pause → resume."""
    # Run workflow with [agent] → [hc] → [code]
    # Verify execution pauses after hc
    # Send approval
    # Verify code node executes
```

---

## Timeline

- **Day 1:** Steps 1-3 (analyze + implement builder + API hooks) — 6-8 hours
- **Day 2:** Step 4 (verify orchestrator) — 2-3 hours
- **Day 2:** Step 5 (tests) — 4 hours

**Total: 1-2 days**

---

## Success Criteria

- [ ] Edge creation auto-sets interrupt_before
- [ ] Edge deletion auto-removes interrupt_before (if no other sources)
- [ ] Multiple human_confirmation sources handled correctly
- [ ] Orchestrator pauses at human_confirmation
- [ ] Orchestrator resumes on user choice
- [ ] All tests pass
- [ ] No regressions

---

## Notes

- This is the final item for Phase 1.2 node cleanup
- After this PR, Phase 1 (v0.2.0) is complete and ready for testing
- human_confirmation enables approval workflows (critical feature)
- Design is simple: auto-set one flag, rest is runtime

# Diagnostic: Zombie Executions & Execution Lifecycle Gaps

**Date:** 2025-02-13
**Trigger:** 3 stuck executions found on Workflow #1 (slug: `orchestrator`), all permanently in `running` status.

## 1. Incident Summary

| Execution ID | Started | Failure Mode | Root Cause |
|---|---|---|---|
| `e4c3c292` | 23:52 UTC | Zero logs, zero output | Silent crash / process kill before LLM call |
| `e5c64137` | 01:43 UTC | 1 log, 404 on model | Misconfigured model name (`claude-o...` not found) |
| `8a66e119` | 02:08 UTC | 1 log, 601s timeout | RQ job killed at 600s deadline |

All three executions remained in `running` status despite the underlying RQ jobs being dead. The platform has no mechanism to detect or recover from this state.

## 2. Root Causes Identified

### Critical — Direct Zombie Causes

#### C1. RQ Job Timeout Has No Status Callback
- **File:** `services/orchestrator.py:33`
- **Problem:** `Queue("workflows", default_timeout=600)` means RQ terminates the worker process after 600s. When the process is killed, `execute_node_job()` never completes — no exception handler runs, no status update, no inflight decrement.
- **Impact:** Execution stays `running` forever. This caused execution `8a66e119`.

#### C2. Inflight Counter Not Decremented on Early Returns
- **File:** `services/orchestrator.py:252-260`
- **Problem:** Two early-return paths exit without calling `r.decr(_inflight_key(...))`:
  1. Line 253-254: execution status is not `running` → `return`
  2. Line 258-260: node not found in topology → `return`
- **Impact:** Inflight counter stays elevated → `_finalize()` never called → execution never completes.

#### C3. Inflight Counter Not Decremented in Outer Exception Handler
- **File:** `services/orchestrator.py:556-586`
- **Problem:** The catch-all exception handler attempts `execution.status = "failed"` and `db.commit()`, but:
  1. Never calls `r.decr(_inflight_key(execution_id))`
  2. The `db.commit()` is wrapped in `except Exception: pass` (line 571) — if commit fails, status change is silently lost
- **Impact:** Even when the handler runs, the inflight counter drifts and the status may not persist.

#### C4. `_finalize()` Has No Exception Protection
- **File:** `services/orchestrator.py:924-973`
- **Problem:** No try/except wrapping. If `output_delivery.deliver()`, `_complete_episode()`, or `db.commit()` throws, the exception propagates uncaught. Status may be set in memory but never committed.
- **Impact:** Execution that finished all nodes can still end up stuck in `running`.

#### C5. LLM Credential Null Dereference
- **File:** `services/llm.py:79-80, 99-100`
- **Problem:** `base_cred.llm_credential` accessed without null check. If the credential was deleted after workflow creation, this crashes with `AttributeError` instead of a proper error message.
- **Impact:** Unhandled crash in factory → caught by outer handler (C3) which may not persist status. This caused execution `e5c64137`.

### High — Silent Failures & Missing Recovery

#### H1. No Zombie Execution Recovery on Startup
- **File:** `main.py:27-42`
- **Problem:** Startup lifespan only calls `recover_scheduled_jobs()`. No recovery for executions stuck in `running` from a previous server crash.
- **Impact:** Zombie executions persist across restarts.

#### H2. Task Wrappers Have Zero Error Handling
- **File:** `tasks/__init__.py:11-23`
- **Problem:** Bare pass-through functions (`execute_workflow_job`, `execute_node_job`). If the underlying function raises an unhandled exception, RQ marks the job failed but execution DB status stays unchanged.

#### H3. Components Return Error Strings as Success
- **Files:** 30+ component files (`http_request.py`, `web_search.py`, `run_command.py`, `memory_write.py`, etc.)
- **Problem:** Components catch exceptions and return `f"Error: {e}"` instead of raising or returning `NodeResult.failed()`. The orchestrator wraps these into `node_outputs` as normal output.
- **Impact:** Downstream nodes process error strings as legitimate data. Nodes show as "success" when they actually failed.

#### H4. Cancel API Doesn't Stop Running RQ Jobs
- **File:** `api/executions.py:97-101`
- **Problem:** Sets `execution.status = "cancelled"` but doesn't: dequeue/stop RQ jobs, decrement inflight, or clean Redis keys.
- **Impact:** Cancelled executions have ghost jobs still running in RQ.

#### H5. `_publish_event()` Can Crash RQ Jobs
- **File:** `services/orchestrator.py:94-104`
- **Problem:** No try/except around `json.dumps()` or `r.publish()`. If Redis is momentarily unreachable, the entire node execution job crashes.
- **Impact:** A transient Redis blip during broadcast crashes the node execution.

### Medium — Robustness Gaps

#### M1. No Execution Status Transition Validation
- Status set via direct string assignment (`execution.status = "failed"`). No guard against invalid transitions.

#### M2. Child Execution Timeout Race Condition
- Both the cleanup job and normal child completion can call `_resume_from_child()` simultaneously.

#### M3. Redis/DB Transactional Inconsistency
- Inflight counter incremented in Redis before RQ job enqueued. If `enqueue()` fails, counter is elevated with no job.

#### M4. Batch Delete Doesn't Clean Redis
- `batch_delete_executions()` deletes DB records but orphans Redis keys.

## 3. Test Coverage Gaps

| Area | Coverage | Notes |
|---|---|---|
| Node failure → execution failed | ~95% | Well-tested, minor edge cases |
| Execution finalization | ~90% | Happy path covered, no race condition tests |
| **Execution-level timeout** | **0%** | No test for RQ job killed after 600s |
| **Zombie execution recovery** | **0%** | No recovery logic exists |
| **RQ worker crash handling** | **0%** | No test for worker process death |
| **Budget enforcement** | **0%** | `_check_budget()` exists, untested |
| **Confirmation task expiry** | **0%** | PendingTask expiry untested |
| **Child execution timeout** | **0%** | Deadline stored, cleanup untested |

## 4. Fix Plan

### Phase 1: Stop the Bleeding (Inflight Counter & Finalize Safety)

**Goal:** Eliminate the most common zombie execution paths.

#### Fix 1.1 — Decrement inflight on all early returns in `execute_node_job()`
- **File:** `services/orchestrator.py`
- Add `r.decr(_inflight_key(execution_id))` before every early `return` in `execute_node_job()`
- After decrement, check `if remaining <= 0: _finalize(execution_id, db)`
- **Affected lines:** 253-254, 258-260, 262-265 (interrupt_before)

#### Fix 1.2 — Decrement inflight in outer exception handler
- **File:** `services/orchestrator.py:556-586`
- Add `r.decr(_inflight_key(execution_id))` in the exception handler
- Remove the silent `except Exception: pass` on line 571 — replace with proper logging

#### Fix 1.3 — Wrap `_finalize()` in try/except
- **File:** `services/orchestrator.py:924-973`
- Wrap the body in try/except
- On exception: set `execution.status = "failed"`, `execution.error_message`, commit, log
- Always call `_cleanup_redis()` in a finally block

#### Fix 1.4 — Null check in LLM resolution
- **File:** `services/llm.py:79-80, 99-100`
- Add `if not base_cred:` guard with `raise ValueError(f"Credential {cc.llm_credential_id} not found")`
- Same for `llm_credential` relationship

### Phase 2: Zombie Recovery (Startup & Periodic Cleanup)

**Goal:** Detect and recover zombie executions automatically.

#### Fix 2.1 — Startup recovery for orphaned running executions
- **File:** `main.py` (lifespan) + new `services/execution_recovery.py`
- On startup, query all executions with `status = "running"` and `updated_at < now() - threshold`
- Mark them as `failed` with `error_message = "Recovered: execution orphaned by server restart"`
- Clean up their Redis keys
- Threshold: configurable, default 30 minutes

#### Fix 2.2 — Periodic watchdog job
- New RQ periodic job (enqueued on startup, re-enqueues itself)
- Scans for executions stuck in `running` for > N minutes with no active RQ jobs
- Marks them as `failed` and cleans Redis
- Interval: every 5 minutes

### Phase 3: Error Handling Hardening

**Goal:** Prevent future zombie creation from edge cases.

#### Fix 3.1 — Wrap `_publish_event()` in try/except
- **File:** `services/orchestrator.py:94-104`
- Broadcast failures should log a warning, not crash the RQ job

#### Fix 3.2 — Add RQ job failure callback
- **File:** `tasks/__init__.py`
- Register `on_failure` callback on enqueued jobs
- Callback marks execution as `failed` and cleans up Redis

#### Fix 3.3 — Cancel API cleanup
- **File:** `api/executions.py`
- On cancel: clean Redis keys, reset inflight counter
- Consider using RQ's `cancel_job()` for pending jobs

#### Fix 3.4 — Component error standardization (separate effort)
- Audit all components returning error strings
- Replace with `NodeResult.failed()` or raised exceptions
- This is a broader refactor — track as separate issue

### Phase 4: Tests

**Goal:** Cover the gaps that let these issues ship.

- Test: RQ job timeout → execution marked failed (mock worker kill)
- Test: Inflight counter consistency across all return paths
- Test: `_finalize()` exception → execution still marked failed
- Test: Startup recovery marks old running executions as failed
- Test: Null credential → proper ValueError (not AttributeError)
- Test: `_publish_event()` failure doesn't crash node execution

## 5. Implementation Order

| Priority | Fix | Effort | Risk |
|---|---|---|---|
| 1 | Fix 1.1 (inflight early returns) | Small | Low — additive |
| 2 | Fix 1.2 (inflight exception handler) | Small | Low — additive |
| 3 | Fix 1.3 (finalize try/except) | Small | Low — wrapping existing code |
| 4 | Fix 1.4 (LLM null check) | Small | Low — guard clause |
| 5 | Fix 3.1 (publish_event safety) | Small | Low — try/except wrapper |
| 6 | Fix 2.1 (startup recovery) | Medium | Low — new code, no modifications |
| 7 | Fix 3.2 (RQ failure callback) | Medium | Medium — RQ integration |
| 8 | Fix 2.2 (watchdog job) | Medium | Low — new code |
| 9 | Fix 3.3 (cancel cleanup) | Medium | Medium — behavioral change |
| 10 | Fix 3.4 (component errors) | Large | Medium — broad refactor |
| 11 | Phase 4 tests | Medium | None |

Fixes 1-5 are small, low-risk, and address the direct zombie causes. They should be done first in a single PR.

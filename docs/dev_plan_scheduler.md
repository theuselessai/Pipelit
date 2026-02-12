# Plan: Scheduled Jobs via Self-Rescheduling

> **Supersedes:** Previous plan based on `rq-scheduler` (separate process).
> **Updated:** 2026-02-13

## Overview

Add scheduled/recurring job execution using RQ's built-in `enqueue_in()` with a self-rescheduling pattern. No new dependencies, no new processes — just FastAPI + RQ worker as today.

**Key insight:** RQ 2.6.1 (already installed) supports `enqueue_in()` and `enqueue_at()`. Combined with a self-rescheduling wrapper that carries state, this gives us interval-based recurring execution with retry/timeout logic — no `rq-scheduler` needed.

## Architecture

```
┌─────────────────┐         ┌─────────────┐         ┌────────────┐
│  FastAPI API     │ ──────▶ │ RQ Queue    │ ──────▶ │ RQ Worker  │
│  (create job)    │ enqueue │ (Redis)     │  execute│ (--with-scheduler) │
└─────────────────┘         └─────────────┘         └─────┬──────┘
                                    ▲                      │
                                    │    self-requeue      │
                                    └──────────────────────┘
                                                           │
                                    ┌─────────────────┐    │ read/update
                                    │  ScheduledJob   │◄───┘
                                    │  (SQLite)       │
                                    └─────────────────┘
```

No third process. The RQ worker must run with `--with-scheduler` flag to process `enqueue_in()` jobs (this may already be the case — check).

---

## Execution Model: Repeat + Retry State Machine

**Parameters per job:**
- `R` — total repeats (0 = infinite)
- `i` — interval between successful runs (seconds)
- `mr` — max retries per repeat on failure
- `tot` — timeout per execution (seconds)

**State per run:**
- `n` — current repeat number (0-indexed)
- `rc` — retry count within current repeat

**State machine:**

```
                    ┌─────────────────────────────────────┐
                    │                                     │
                    ▼                                     │
              ┌──────────┐                                │
         ┌───►│   RUN    │ (timeout: tot)                 │
         │    └────┬─────┘                                │
         │         │                                      │
         │    ┌────┴────┐                                 │
         │    ▼         ▼                                 │
      ┌──────────┐ ┌──────────┐                           │
      │ SUCCESS  │ │  FAIL    │                           │
      └────┬─────┘ └────┬─────┘                           │
           │            │                                 │
           │            ▼                                 │
           │      rc = rc + 1                             │
           │      rc > mr?                                │
           │       │      │                               │
           │      YES     NO                              │
           │       │      │                               │
           │       ▼      ▼                               │
           │    ┌──────┐  wait backoff(rc)                │
           │    │ DEAD │  └──────► RUN (same n, rc)       │
           │    └──────┘                                  │
           │                                              │
           ▼                                              │
     rc = 0 (reset)                                       │
     n = n + 1                                            │
     n >= R? (skip if R=0)                                │
      │      │                                            │
     YES     NO                                           │
      │      │                                            │
      ▼      └── wait i seconds ──────────────────────────┘
   ┌──────┐
   │ DONE │
   └──────┘
```

**Transition equation:**

```
next(n, rc, result) =
    if result == SUCCESS:
        if R > 0 and n + 1 >= R  → DONE
        else                     → enqueue_in(i, run(n+1, 0))        # next repeat, retry reset

    if result == FAIL or TIMEOUT:
        if rc + 1 > mr           → DEAD
        else                     → enqueue_in(backoff(rc+1), run(n, rc+1))  # same repeat, retry++
```

**Backoff function** (exponential, capped at 10× interval):

```
backoff(rc) = min(i × 2^(rc-1), i × 10)
```

Example with `i=300s, mr=3`:
- retry 1: 300s
- retry 2: 600s
- retry 3: 1200s (cap would be 3000s)

**Worst-case executions per cycle:** `R × (mr + 1)`

**Key property:** Success at any point in the retry loop resets `rc=0` and breaks back into the normal repeat cycle. The retry budget is per-repeat, not global.

---

## Phase 1: Database Model & Schema

### 1.1 Create `platform/models/scheduled_job.py`

```python
class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")

    # Links
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"))
    trigger_node_id: Mapped[str | None] = mapped_column(String, nullable=True)  # node_id of trigger_schedule
    user_profile_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id", ondelete="CASCADE"))

    # Schedule config
    interval_seconds: Mapped[int] = mapped_column(Integer)          # i — seconds between runs
    total_repeats: Mapped[int] = mapped_column(Integer, default=0)  # R — 0 = infinite
    max_retries: Mapped[int] = mapped_column(Integer, default=3)    # mr — per-repeat
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=600)  # tot — per-execution

    # Payload passed to trigger
    trigger_payload: Mapped[dict | None] = mapped_column(JSON)

    # State
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | paused | stopped | dead | done
    current_repeat: Mapped[int] = mapped_column(Integer, default=0)    # n
    current_retry: Mapped[int] = mapped_column(Integer, default=0)     # rc

    # Tracking
    last_run_at: Mapped[datetime | None]
    next_run_at: Mapped[datetime | None]
    run_count: Mapped[int] = mapped_column(default=0)       # total successful runs
    error_count: Mapped[int] = mapped_column(default=0)     # total failed runs
    last_error: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
```

### 1.2 Update `platform/models/__init__.py`
- Add `from models.scheduled_job import ScheduledJob`

### 1.3 Create Alembic migration

### 1.4 Create `platform/schemas/schedule.py`
- `ScheduledJobCreate`, `ScheduledJobOut`, `ScheduledJobUpdate` Pydantic schemas

---

## Phase 2: Scheduler Service (Self-Rescheduling Wrapper)

### 2.1 Create `platform/services/scheduler.py`

```python
def execute_scheduled_job(job_id: str, current_repeat: int = 0, current_retry: int = 0) -> None:
    """Self-rescheduling wrapper. Called by RQ worker.

    Reads ScheduledJob from DB, dispatches workflow execution,
    handles success/failure, and enqueues the next run.

    Timeout is enforced by RQ's job_timeout parameter on enqueue,
    not within this function. If the job exceeds timeout, RQ kills
    it and it enters the FAIL path on the next retry.
    """
    db = SessionLocal()
    try:
        # Re-check status under fresh read to narrow race window with pause/stop.
        # SQLite doesn't support SELECT FOR UPDATE, but the TOCTOU gap is small
        # and worst case is one extra execution of a paused job.
        job = db.get(ScheduledJob, job_id)
        if not job or job.status != "active":
            return  # paused, stopped, or deleted — don't reschedule

        try:
            result = _dispatch_scheduled_trigger(job, db)
            # SUCCESS path
            job.run_count += 1
            job.current_retry = 0
            job.last_run_at = utcnow()
            job.last_error = ""
            next_n = current_repeat + 1

            if job.total_repeats > 0 and next_n >= job.total_repeats:
                job.status = "done"
            else:
                # Schedule next repeat
                job.current_repeat = next_n
                _enqueue_next(job, next_n, 0, job.interval_seconds)

        except Exception as e:
            # FAIL path (includes RQ timeout → WorkerLostError)
            next_rc = current_retry + 1
            job.error_count += 1
            job.last_error = str(e)

            if next_rc > job.max_retries:
                job.status = "dead"  # retries exhausted
            else:
                # Schedule retry with backoff
                job.current_retry = next_rc
                backoff = _backoff(job.interval_seconds, next_rc)
                _enqueue_next(job, current_repeat, next_rc, backoff)

        db.commit()
    finally:
        db.close()


def _backoff(interval: int, retry_count: int) -> int:
    """Exponential backoff capped at 10× interval."""
    return min(interval * (2 ** (retry_count - 1)), interval * 10)


def _enqueue_next(job: ScheduledJob, n: int, rc: int, delay_seconds: int) -> None:
    """Enqueue the next run of the scheduled job.

    Uses RQ's job_timeout to enforce the per-execution timeout (tot).
    If the job exceeds this, RQ terminates the worker process and
    marks the job as failed.
    """
    from tasks import _queue
    q = _queue()
    q.enqueue_in(
        timedelta(seconds=delay_seconds),
        execute_scheduled_job,
        job.id, n, rc,
        job_timeout=job.timeout_seconds,
    )
    job.next_run_at = utcnow() + timedelta(seconds=delay_seconds)


def _dispatch_scheduled_trigger(job: ScheduledJob, db) -> dict:
    """Fire the workflow trigger. Returns dispatch result.

    Note: dispatch_event is fire-and-forget — it creates a
    WorkflowExecution record and enqueues it on RQ. The actual
    workflow runs asynchronously. Timeout enforcement on the
    wrapper (execute_scheduled_job) covers the dispatch + any
    synchronous setup, while execution-level timeouts are a
    separate concern handled by the orchestrator.
    """
    from handlers import dispatch_event
    user = db.get(UserProfile, job.user_profile_id)
    if not user:
        raise ValueError(f"User {job.user_profile_id} not found for scheduled job {job.id}")
    event_data = {
        "scheduled_job_id": job.id,
        "scheduled_job_name": job.name,
        "repeat_number": job.current_repeat,
        "payload": job.trigger_payload or {},
    }
    return dispatch_event(
        "schedule", event_data, user, db,
        workflow_id=job.workflow_id,
        trigger_node_id=job.trigger_node_id,
    )


def start_scheduled_job(job: ScheduledJob) -> None:
    """Kick off the first run of a scheduled job (called on create/resume).

    Caller must commit the DB session after calling this — the function
    updates job.next_run_at but does not commit.
    """
    _enqueue_next(job, job.current_repeat, job.current_retry, job.interval_seconds)


def pause_scheduled_job(job: ScheduledJob) -> None:
    """Pause — set status to paused. The wrapper checks status before running.

    Caller must commit the DB session after calling this.
    """
    job.status = "paused"


def resume_scheduled_job(job: ScheduledJob) -> None:
    """Resume — set status back to active and enqueue next run.

    Caller must commit the DB session after calling this.
    """
    job.status = "active"
    start_scheduled_job(job)
```

### 2.2 Startup recovery

On FastAPI startup, re-enqueue any active jobs whose `next_run_at` is in the past (missed while the worker was down):

```python
# In main.py @app.on_event("startup") or lifespan:
def recover_scheduled_jobs():
    """Re-enqueue active jobs missed during downtime.

    Filters by next_run_at < now. Note: next_run_at is set by
    _enqueue_next() on every enqueue, including the initial creation.
    Jobs with next_run_at=NULL (should not happen) are excluded by
    the SQL comparison (NULL < datetime is always false).
    """
    db = SessionLocal()
    try:
        stale = db.query(ScheduledJob).filter(
            ScheduledJob.status == "active",
            ScheduledJob.next_run_at < utcnow(),
        ).all()
        for job in stale:
            start_scheduled_job(job)
        db.commit()
    finally:
        db.close()
```

---

## Phase 3: Trigger Integration

### 3.1 Update `platform/triggers/resolver.py`

The resolver already maps `"schedule"` → `"trigger_schedule"` (line 16). Add `_match_schedule()`:

```python
def _match_schedule(self, config: dict, event_data: dict) -> bool:
    """Match by scheduled_job_id or name pattern."""
    job_id = event_data.get("scheduled_job_id")
    filter_id = (config or {}).get("scheduled_job_id")
    if filter_id:
        return job_id == filter_id
    return True  # no filter = match all schedule events
```

---

## Phase 4: API Endpoints

### 4.1 Create `platform/api/schedules.py`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/schedules/` | GET | List jobs (filter by status, workflow_id) |
| `/schedules/` | POST | Create job → enqueues first run |
| `/schedules/{id}/` | GET | Get job detail |
| `/schedules/{id}/` | PATCH | Update job config |
| `/schedules/{id}/` | DELETE | Delete job |
| `/schedules/{id}/pause/` | POST | Pause (stops rescheduling) |
| `/schedules/{id}/resume/` | POST | Resume (re-enqueues) |
| `/schedules/batch-delete/` | POST | Batch delete |

### 4.2 Register router in `platform/main.py`

---

## Phase 5: Agent Tool Component

### 5.1 Create `platform/components/scheduler_tools.py`

Single consolidated component (like `epic_tools`, `task_tools`) exposing 5 tools:

| Tool | Description |
|------|-------------|
| `create_schedule` | Create a scheduled job for a workflow |
| `pause_schedule` | Pause a running schedule |
| `resume_schedule` | Resume a paused schedule |
| `stop_schedule` | Delete a schedule permanently |
| `list_schedules` | List scheduled jobs with optional filters |

### 5.2 Registration

- `platform/components/__init__.py` — add import
- `platform/schemas/node_type_defs.py` — register `scheduler_tools` node type
- `platform/models/node.py` — add `_SchedulerToolsConfig` polymorphic identity + `COMPONENT_TYPE_MAP` entry

---

## Phase 6: Frontend Updates

### 6.1 `platform/frontend/src/types/models.ts`
- Add `scheduler_tools` to `ComponentType` union
- Add `ScheduledJob` interface

### 6.2 `NodePalette.tsx`
- Add `scheduler_tools` under "Tools" category with clock icon

### 6.3 `WorkflowCanvas.tsx`
- Add to `COMPONENT_COLORS` (amber `#f59e0b`)
- Add to `COMPONENT_ICONS` (`fa-clock`)
- Add to `isTool` array

---

## Files Summary

| File | Action |
|------|--------|
| `platform/models/scheduled_job.py` | Create |
| `platform/models/__init__.py` | Update import |
| `platform/schemas/schedule.py` | Create |
| `platform/services/scheduler.py` | Create |
| `platform/api/schedules.py` | Create |
| `platform/main.py` | Register router, add startup recovery |
| `platform/triggers/resolver.py` | Add `_match_schedule` |
| `platform/tasks/__init__.py` | (only if wrapper needs RQ job registration) |
| `platform/components/scheduler_tools.py` | Create |
| `platform/components/__init__.py` | Add import |
| `platform/schemas/node_type_defs.py` | Register spec |
| `platform/models/node.py` | Add STI class |
| `platform/alembic/versions/xxx_scheduled_jobs.py` | Create migration |
| `platform/frontend/src/types/models.ts` | Update types |
| `platform/frontend/src/features/.../NodePalette.tsx` | Add icon |
| `platform/frontend/src/features/.../WorkflowCanvas.tsx` | Add colors/icons |

**No new dependencies.** Uses `rq>=1.16` (already installed at 2.6.1).

---

## Verification

1. **Unit tests** (`platform/tests/test_scheduler.py`):
   - Test state machine transitions (success → next repeat, fail → retry, exhaust → dead)
   - Test backoff calculation
   - Test pause/resume (wrapper exits early on paused status)
   - Test infinite repeat (R=0 never reaches DONE)
   - Test startup recovery of stale jobs

2. **API tests**:
   - CRUD lifecycle
   - Pause/resume state transitions
   - Validation (interval > 0, max_retries >= 0)

3. **Integration test**:
   - Create workflow with `trigger_schedule`
   - Create scheduled job via API
   - Verify workflow executes after interval
   - Pause, verify no more executions
   - Resume, verify execution resumes

4. **Manual test**:
   ```bash
   # Terminal 1: Redis
   redis-server

   # Terminal 2: RQ Worker (with scheduler flag for enqueue_in)
   rq worker --with-scheduler workflows

   # Terminal 3: FastAPI
   uvicorn platform.main:app --reload
   ```
   - `POST /api/v1/schedules/` with `interval_seconds=30`
   - Watch logs for recurring execution every 30s
   - `POST /api/v1/schedules/{id}/pause/` — verify it stops
   - `POST /api/v1/schedules/{id}/resume/` — verify it restarts

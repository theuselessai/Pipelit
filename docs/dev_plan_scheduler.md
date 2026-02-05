# Plan: RQ Scheduler for Periodic Tasks

## Overview

Add `rq-scheduler` support for periodic/scheduled tasks. This enables:
- Cron and interval-based job scheduling
- Agent tools to create/pause/resume/stop scheduled jobs
- Database persistence for pause/resume (rq-scheduler has no native pause)
- Integration with existing trigger system via `trigger_schedule`

## Architecture

```
┌─────────────────┐         ┌─────────────┐         ┌────────────┐
│  rqscheduler    │ ──────▶ │ RQ Queue    │ ──────▶ │ RQ Worker  │
│  (process)      │  enqueue│ (Redis)     │  execute│ (process)  │
└─────────────────┘         └─────────────┘         └────────────┘
        │                                                  │
        │ sync on startup                                  │
        ▼                                                  ▼
┌─────────────────┐                              ┌─────────────────┐
│  ScheduledJob   │                              │  dispatch_event │
│  (SQLite)       │                              │  → workflow     │
└─────────────────┘                              └─────────────────┘
```

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
    trigger_node_id: Mapped[int | None] = mapped_column(ForeignKey("workflow_nodes.id", ondelete="SET NULL"))
    user_profile_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id", ondelete="CASCADE"))

    # Schedule (one of these)
    schedule_type: Mapped[str] = mapped_column(String(20))  # "cron" | "interval"
    cron_expression: Mapped[str | None] = mapped_column(String(100))
    interval_seconds: Mapped[int | None] = mapped_column(Integer)

    # Payload passed to trigger
    trigger_payload: Mapped[dict | None] = mapped_column(JSON)

    # State (for pause/resume)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | paused | stopped
    rq_job_id: Mapped[str | None] = mapped_column(String(100))

    # Tracking
    last_run_at: Mapped[datetime | None]
    next_run_at: Mapped[datetime | None]
    run_count: Mapped[int] = mapped_column(default=0)
    error_count: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
```

### 1.2 Update `platform/models/__init__.py`
- Add `from models.scheduled_job import ScheduledJob`

### 1.3 Create Alembic migration
- Remember: `PRAGMA foreign_keys = OFF` for batch operations (SQLite + CASCADE DELETE safety)

### 1.4 Create `platform/schemas/schedule.py`
- `ScheduledJobIn`, `ScheduledJobOut`, `ScheduledJobUpdate` Pydantic schemas

---

## Phase 2: Scheduler Service

### 2.1 Create `platform/services/scheduler.py`

```python
class SchedulerService:
    def __init__(self):
        self.conn = Redis.from_url(settings.REDIS_URL)
        self.scheduler = Scheduler(connection=self.conn)

    def schedule_job(self, job: ScheduledJob) -> str:
        """Register job with rq-scheduler. Returns rq_job_id."""

    def cancel_job(self, rq_job_id: str):
        """Remove from rq-scheduler."""

    def sync_jobs_on_startup(self, db: Session):
        """Re-register all active jobs from DB on startup."""

# Singleton getter
_scheduler_service = None
def get_scheduler_service() -> SchedulerService: ...
```

### 2.2 Create `platform/scheduler_main.py`

Entry point to run scheduler as separate process:
```bash
python -m platform.scheduler_main
```

Startup flow:
1. Load active jobs from DB
2. Register each with rq-scheduler
3. Run scheduler loop

### 2.3 Add task to `platform/tasks/__init__.py`

```python
def execute_scheduled_trigger(scheduled_job_id: str) -> None:
    """Called by rq-scheduler when job fires."""
    # Update job tracking (last_run_at, run_count)
    # Call dispatch_event("schedule", event_data, user_profile, db)
```

---

## Phase 3: Trigger Integration

### 3.1 Update `platform/triggers/resolver.py`

Add `_match_schedule()` method:
```python
def _match_schedule(self, config: dict, event_data: dict) -> bool:
    """Match by scheduled_job_id or name pattern."""
```

The resolver already maps `"schedule"` → `"trigger_schedule"`.

---

## Phase 4: API Endpoints

### 4.1 Create `platform/api/schedules.py`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/schedules/` | GET | List jobs (filter by status) |
| `/schedules/` | POST | Create job |
| `/schedules/{id}/` | GET | Get job |
| `/schedules/{id}/` | PATCH | Update job |
| `/schedules/{id}/` | DELETE | Delete job |
| `/schedules/{id}/pause/` | POST | Pause job |
| `/schedules/{id}/resume/` | POST | Resume job |

### 4.2 Register router in `platform/main.py`

---

## Phase 5: Agent Tool Components

### 5.1 Create `platform/components/scheduler_tools.py`

5 tools for agent job management:

| Tool | Description |
|------|-------------|
| `schedule_create` | Create a scheduled job |
| `schedule_pause` | Pause a job (cancel in rq, set status=paused) |
| `schedule_resume` | Resume a job (re-register in rq, set status=active) |
| `schedule_stop` | Delete a job permanently |
| `schedule_list` | List jobs with optional filters |

Each follows the `@register("component_type")` pattern.

### 5.2 Update `platform/components/__init__.py`
- Add `from components import scheduler_tools`

### 5.3 Update `platform/schemas/node.py`
Add to `ComponentTypeStr`:
```python
"schedule_create", "schedule_pause", "schedule_resume", "schedule_stop", "schedule_list"
```

### 5.4 Update `platform/schemas/node_type_defs.py`
Register node type specs for each tool.

### 5.5 Update `platform/models/node.py`
Add polymorphic identity classes:
```python
class _ScheduleCreateConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "schedule_create"}
# ... etc for each tool
```

Add to `COMPONENT_TYPE_TO_CONFIG` mapping.

---

## Phase 6: Frontend Updates

### 6.1 Update `platform/frontend/src/types/models.ts`
- Add tool types to `ComponentType` union
- Add `ScheduledJob` interface

### 6.2 Update `platform/frontend/src/features/workflows/components/NodePalette.tsx`
- Add icons and "Scheduler" category for tools

### 6.3 Update `platform/frontend/src/features/workflows/components/WorkflowCanvas.tsx`
- Add to `COMPONENT_COLORS` (use amber/orange for scheduler tools)
- Add to `COMPONENT_ICONS`
- Add to `isTool` array

---

## Files Summary

| File | Action |
|------|--------|
| `platform/models/scheduled_job.py` | Create |
| `platform/models/__init__.py` | Update import |
| `platform/schemas/schedule.py` | Create |
| `platform/services/scheduler.py` | Create |
| `platform/scheduler_main.py` | Create |
| `platform/tasks/__init__.py` | Add task |
| `platform/triggers/resolver.py` | Add `_match_schedule` |
| `platform/api/schedules.py` | Create |
| `platform/main.py` | Register router |
| `platform/components/scheduler_tools.py` | Create |
| `platform/components/__init__.py` | Add import |
| `platform/schemas/node.py` | Update Literal |
| `platform/schemas/node_type_defs.py` | Register specs |
| `platform/models/node.py` | Add STI classes |
| `platform/alembic/versions/xxx_scheduled_jobs.py` | Create migration |
| `platform/frontend/src/types/models.ts` | Update types |
| `platform/frontend/src/features/.../NodePalette.tsx` | Add icons |
| `platform/frontend/src/features/.../WorkflowCanvas.tsx` | Add colors/icons |
| `requirements.txt` | Add `rq-scheduler` |

---

## Verification

1. **Unit tests**: Create `platform/tests/test_scheduler.py`
   - Test job CRUD via API
   - Test pause/resume state transitions
   - Test tool invocations

2. **Integration test**:
   - Create a workflow with `trigger_schedule`
   - Create scheduled job via API
   - Verify job fires and workflow executes
   - Test pause/resume cycle

3. **Manual test**:
   ```bash
   # Terminal 1: Redis
   redis-server

   # Terminal 2: RQ Worker
   rq worker workflows

   # Terminal 3: RQ Scheduler
   python -m platform.scheduler_main

   # Terminal 4: FastAPI
   uvicorn platform.main:app --reload
   ```
   - Create job via API: `POST /api/v1/schedules/`
   - Watch logs for scheduled execution
   - Test pause/resume via API

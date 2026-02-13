"""System health component — LangChain tool for checking platform infrastructure health."""

from __future__ import annotations

import json
import logging

from langchain_core.tools import tool

from components import register

logger = logging.getLogger(__name__)


@register("system_health")
def system_health_factory(node):
    """Return a list with a single system health check tool."""

    @tool
    def check_system_health() -> str:
        """Check platform infrastructure health including Redis, RQ workers,
        queue depths, stuck executions, failed executions, and scheduled jobs.

        Returns:
            JSON with timestamp, summary (healthy/degraded/critical), per-check
            details, and a list of issues found.
        """
        from datetime import datetime, timedelta, timezone

        import redis as redis_lib
        from rq import Queue, Worker

        from sqlalchemy import func

        from config import settings
        from database import SessionLocal
        from models.execution import WorkflowExecution
        from models.scheduled_job import ScheduledJob

        now = datetime.now(timezone.utc)
        checks = {}
        issues = []

        # --- Redis ---
        try:
            conn = redis_lib.from_url(settings.REDIS_URL)
            conn.ping()
            mem_info = conn.info("memory")
            checks["redis"] = {
                "status": "ok",
                "used_memory_human": mem_info.get("used_memory_human", "unknown"),
                "used_memory_peak_human": mem_info.get("used_memory_peak_human", "unknown"),
                "connected_clients": conn.info("clients").get("connected_clients", "unknown"),
            }
        except Exception as e:
            checks["redis"] = {"status": "error", "error": str(e)}
            issues.append({"severity": "critical", "check": "redis", "detail": f"Redis unreachable: {e}"})
            # Cannot check workers/queues without Redis
            checks["workers"] = {"status": "unknown", "error": "Redis unavailable"}
            checks["queues"] = {"status": "unknown", "error": "Redis unavailable"}
            conn = None

        # --- RQ Workers ---
        if conn is not None:
            try:
                # rq requires decode_responses=False
                rq_conn = redis_lib.from_url(settings.REDIS_URL, decode_responses=False)
                workers = Worker.all(connection=rq_conn)
                worker_count = len(workers)
                worker_details = [
                    {
                        "name": w.name,
                        "state": w.get_state(),
                        "queues": [q.name for q in w.queues],
                    }
                    for w in workers
                ]
                checks["workers"] = {
                    "status": "ok" if worker_count > 0 else "error",
                    "count": worker_count,
                    "workers": worker_details,
                }
                if worker_count == 0:
                    issues.append({"severity": "critical", "check": "workers", "detail": "No RQ workers running"})
            except Exception as e:
                checks["workers"] = {"status": "error", "error": str(e)}
                issues.append({"severity": "critical", "check": "workers", "detail": f"Failed to query workers: {e}"})

            # --- Queue Depths ---
            try:
                rq_conn = redis_lib.from_url(settings.REDIS_URL, decode_responses=False)
                queue_info = {}
                for queue_name in ("workflows", "default"):
                    q = Queue(queue_name, connection=rq_conn)
                    queue_info[queue_name] = len(q)
                checks["queues"] = {"status": "ok", **queue_info}
            except Exception as e:
                checks["queues"] = {"status": "error", "error": str(e)}

        # --- Stuck Executions ---
        db = SessionLocal()
        try:
            threshold = now - timedelta(minutes=15)
            stuck = (
                db.query(WorkflowExecution)
                .filter(
                    WorkflowExecution.status == "running",
                    WorkflowExecution.started_at < threshold,
                )
                .all()
            )
            stuck_list = [
                {
                    "execution_id": ex.execution_id,
                    "workflow_id": ex.workflow_id,
                    "started_at": ex.started_at.isoformat() if ex.started_at else None,
                }
                for ex in stuck
            ]
            checks["stuck_executions"] = {
                "status": "error" if stuck_list else "ok",
                "count": len(stuck_list),
                "executions": stuck_list,
            }
            if stuck_list:
                issues.append({
                    "severity": "critical",
                    "check": "stuck_executions",
                    "detail": f"{len(stuck_list)} execution(s) running longer than 15 minutes",
                })

            # --- Recent Failed Executions (last 24h) ---
            cutoff_24h = now - timedelta(hours=24)
            failed = (
                db.query(
                    WorkflowExecution.error_message,
                    func.count(WorkflowExecution.execution_id).label("count"),
                )
                .filter(
                    WorkflowExecution.status == "failed",
                    WorkflowExecution.completed_at > cutoff_24h,
                )
                .group_by(WorkflowExecution.error_message)
                .all()
            )
            total_failed = sum(row.count for row in failed)
            failed_groups = [
                {"error": row.error_message or "(no message)", "count": row.count}
                for row in failed
            ]
            checks["failed_executions"] = {
                "status": "warn" if total_failed > 5 else "ok",
                "total_24h": total_failed,
                "by_error": failed_groups,
            }
            if total_failed > 5:
                issues.append({
                    "severity": "warn",
                    "check": "failed_executions",
                    "detail": f"{total_failed} failed execution(s) in the last 24 hours",
                })

            # --- Dead / Erroring Scheduled Jobs ---
            problem_jobs = (
                db.query(ScheduledJob)
                .filter(
                    (ScheduledJob.status == "dead") | (ScheduledJob.error_count > 0)
                )
                .all()
            )
            job_list = [
                {
                    "id": j.id,
                    "name": j.name,
                    "status": j.status,
                    "error_count": j.error_count,
                    "last_error": j.last_error[:200] if j.last_error else "",
                }
                for j in problem_jobs
            ]
            dead_count = sum(1 for j in problem_jobs if j.status == "dead")
            checks["scheduled_jobs"] = {
                "status": "warn" if job_list else "ok",
                "dead_count": dead_count,
                "erroring_count": len(job_list),
                "jobs": job_list,
            }
            if dead_count > 0:
                issues.append({
                    "severity": "warn",
                    "check": "scheduled_jobs",
                    "detail": f"{dead_count} dead scheduled job(s)",
                })

        except Exception as e:
            logger.exception("Error querying database for health checks")
            for key in ("stuck_executions", "failed_executions", "scheduled_jobs"):
                if key not in checks:
                    checks[key] = {"status": "error", "error": str(e)}
        finally:
            db.close()

        # --- Summary ---
        redis_down = checks.get("redis", {}).get("status") != "ok"
        no_workers = checks.get("workers", {}).get("count", 0) == 0
        has_stuck = checks.get("stuck_executions", {}).get("count", 0) > 0

        if redis_down or no_workers or has_stuck:
            summary = "critical"
        elif (
            checks.get("failed_executions", {}).get("total_24h", 0) > 5
            or checks.get("scheduled_jobs", {}).get("dead_count", 0) > 0
        ):
            summary = "degraded"
        else:
            summary = "healthy"

        result = {
            "timestamp": now.isoformat(),
            "summary": summary,
            "checks": checks,
            "issues": issues,
        }

        return json.dumps(result, default=str)

    return [check_system_health]

import uuid

from django.db import models


class WorkflowExecution(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        INTERRUPTED = "interrupted", "Interrupted"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    execution_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow = models.ForeignKey(
        "workflows.Workflow",
        on_delete=models.CASCADE,
        related_name="executions",
    )
    trigger_node = models.ForeignKey(
        "workflows.WorkflowNode",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="triggered_executions",
    )
    parent_execution = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="child_executions",
    )
    parent_node_id = models.CharField(max_length=255, blank=True, default="")
    user_profile = models.ForeignKey(
        "users.UserProfile",
        on_delete=models.CASCADE,
        related_name="executions",
    )
    thread_id = models.CharField(max_length=255)
    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.PENDING,
    )
    trigger_payload = models.JSONField(null=True, blank=True)
    final_output = models.JSONField(null=True, blank=True)
    retry_count = models.IntegerField(default=0)
    max_retries = models.IntegerField(default=3)
    error_message = models.TextField(blank=True, default="")
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"Execution {self.execution_id} ({self.status})"


class ExecutionLog(models.Model):
    class Status(models.TextChoices):
        STARTED = "started", "Started"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"

    execution = models.ForeignKey(
        WorkflowExecution,
        on_delete=models.CASCADE,
        related_name="logs",
    )
    node_id = models.CharField(max_length=255)
    status = models.CharField(max_length=15, choices=Status.choices)
    input = models.JSONField(null=True, blank=True)
    output = models.JSONField(null=True, blank=True)
    error = models.TextField(blank=True, default="")
    duration_ms = models.IntegerField(default=0)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["timestamp"]

    def __str__(self):
        return f"{self.node_id} ({self.status}) @ {self.timestamp}"


class PendingTask(models.Model):
    task_id = models.CharField(max_length=8, primary_key=True)
    execution = models.ForeignKey(
        WorkflowExecution,
        on_delete=models.CASCADE,
        related_name="pending_tasks",
    )
    user_profile = models.ForeignKey(
        "users.UserProfile",
        on_delete=models.CASCADE,
        related_name="pending_tasks",
    )
    telegram_chat_id = models.BigIntegerField()
    node_id = models.CharField(max_length=255)
    prompt = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    def __str__(self):
        return f"PendingTask {self.task_id} ({self.node_id})"

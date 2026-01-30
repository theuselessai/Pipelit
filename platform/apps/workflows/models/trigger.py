from django.db import models


class WorkflowTrigger(models.Model):
    class TriggerType(models.TextChoices):
        TELEGRAM_MESSAGE = "telegram_message", "Telegram Message"
        TELEGRAM_CHAT = "telegram_chat", "Telegram Chat"
        SCHEDULE = "schedule", "Schedule"
        WEBHOOK = "webhook", "Webhook"
        MANUAL = "manual", "Manual"
        WORKFLOW = "workflow", "Workflow"
        ERROR = "error", "Error"

    credential = models.ForeignKey(
        "credentials.BaseCredentials",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="triggers",
    )
    workflow = models.ForeignKey(
        "workflows.Workflow",
        on_delete=models.CASCADE,
        related_name="triggers",
    )
    trigger_type = models.CharField(max_length=20, choices=TriggerType.choices)
    config = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True)
    priority = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["priority"]

    def __str__(self):
        return f"{self.trigger_type} -> {self.workflow}"

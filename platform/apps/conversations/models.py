from django.db import models


class Conversation(models.Model):
    user_profile = models.ForeignKey(
        "users.UserProfile",
        on_delete=models.CASCADE,
        related_name="conversations",
    )
    thread_id = models.CharField(max_length=255)
    workflow = models.ForeignKey(
        "workflows.Workflow",
        on_delete=models.CASCADE,
        related_name="conversations",
    )
    execution = models.ForeignKey(
        "workflows.WorkflowExecution",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="conversations",
    )
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Conversation {self.thread_id} ({self.user_profile})"

from django.db import models


class WorkflowManager(models.Manager):
    """Default manager that excludes soft-deleted workflows."""

    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class WorkflowAllManager(models.Manager):
    """Manager that includes soft-deleted workflows."""
    pass


class Workflow(models.Model):
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    description = models.TextField(blank=True, default="")
    owner = models.ForeignKey(
        "users.UserProfile",
        on_delete=models.CASCADE,
        related_name="owned_workflows",
    )
    repository = models.OneToOneField(
        "workflows.GitRepository",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workflow",
    )
    is_active = models.BooleanField(default=True)
    is_public = models.BooleanField(default=False)
    is_template = models.BooleanField(default=False)
    is_callable = models.BooleanField(default=False)
    is_default = models.BooleanField(default=False)
    forked_from = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="forks",
    )
    error_handler_workflow = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="error_handled_by",
    )
    input_schema = models.JSONField(null=True, blank=True)
    output_schema = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = WorkflowManager()
    all_objects = WorkflowAllManager()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name

    def soft_delete(self):
        from django.utils import timezone
        self.deleted_at = timezone.now()
        self.save(update_fields=["deleted_at"])


class WorkflowCollaborator(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        EDITOR = "editor", "Editor"
        VIEWER = "viewer", "Viewer"

    workflow = models.ForeignKey(
        Workflow,
        on_delete=models.CASCADE,
        related_name="collaborators",
    )
    user_profile = models.ForeignKey(
        "users.UserProfile",
        on_delete=models.CASCADE,
        related_name="collaborations",
    )
    role = models.CharField(max_length=10, choices=Role.choices)
    invited_by = models.ForeignKey(
        "users.UserProfile",
        on_delete=models.SET_NULL,
        null=True,
        related_name="sent_invitations",
    )
    invited_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [("workflow", "user_profile")]

    def __str__(self):
        return f"{self.user_profile} - {self.workflow} ({self.role})"

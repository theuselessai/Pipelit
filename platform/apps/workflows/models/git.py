from django.db import models


class GitRepository(models.Model):
    class GitProvider(models.TextChoices):
        GITHUB = "github", "GitHub"
        GITLAB = "gitlab", "GitLab"
        BITBUCKET = "bitbucket", "Bitbucket"

    name = models.CharField(max_length=255)
    credential = models.ForeignKey(
        "credentials.GitCredential",
        on_delete=models.SET_NULL,
        null=True,
        related_name="repositories",
    )
    provider = models.CharField(max_length=20, choices=GitProvider.choices)
    remote_url = models.URLField(max_length=500)
    default_branch = models.CharField(max_length=100, default="main")
    local_path = models.CharField(max_length=500)
    last_commit_hash = models.CharField(max_length=40, blank=True, default="")
    last_synced_at = models.DateTimeField(null=True, blank=True)
    auto_sync_enabled = models.BooleanField(default=False)
    webhook_url = models.URLField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "git repositories"

    def __str__(self):
        return self.name


class GitCommit(models.Model):
    repository = models.ForeignKey(
        GitRepository,
        on_delete=models.CASCADE,
        related_name="commits",
    )
    commit_hash = models.CharField(max_length=40, unique=True)
    message = models.TextField()
    author = models.ForeignKey(
        "users.UserProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="git_commits",
    )
    files_changed = models.JSONField(default=list)
    additions = models.IntegerField(default=0)
    deletions = models.IntegerField(default=0)
    committed_at = models.DateTimeField()
    synced_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-committed_at"]

    def __str__(self):
        return f"{self.commit_hash[:8]} - {self.message[:50]}"


class GitSyncTask(models.Model):
    class Direction(models.TextChoices):
        PUSH = "push", "Push"
        PULL = "pull", "Pull"
        BOTH = "both", "Both"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    repository = models.ForeignKey(
        GitRepository,
        on_delete=models.CASCADE,
        related_name="sync_tasks",
    )
    direction = models.CharField(max_length=10, choices=Direction.choices)
    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.PENDING,
    )
    commit_message = models.TextField(blank=True, default="")
    commit_hash = models.CharField(max_length=40, blank=True, default="")
    files_changed = models.JSONField(default=list)
    error_log = models.TextField(blank=True, default="")
    retry_count = models.IntegerField(default=0)
    max_retries = models.IntegerField(default=3)
    triggered_by = models.ForeignKey(
        "users.UserProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="triggered_sync_tasks",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.direction} {self.repository.name} ({self.status})"

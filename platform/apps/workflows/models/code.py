from django.db import models


class CodeBlock(models.Model):
    workflow = models.ForeignKey(
        "workflows.Workflow",
        on_delete=models.CASCADE,
        related_name="code_blocks",
    )
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    description = models.TextField(blank=True, default="")
    language = models.CharField(max_length=20, default="python")
    timeout_seconds = models.IntegerField(default=30)
    file_path = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Derived path for Git export, e.g. code/slug.py",
    )
    published_version = models.ForeignKey(
        "workflows.CodeBlockVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    draft_version = models.ForeignKey(
        "workflows.CodeBlockVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class CodeBlockVersion(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        TESTING = "testing", "Testing"
        PUBLISHED = "published", "Published"
        DEPRECATED = "deprecated", "Deprecated"

    class Source(models.TextChoices):
        UI = "ui", "UI"
        GIT_PULL = "git_pull", "Git Pull"

    code_block = models.ForeignKey(
        CodeBlock,
        on_delete=models.CASCADE,
        related_name="versions",
    )
    version_number = models.IntegerField()
    code = models.TextField()
    code_hash = models.CharField(max_length=64, help_text="SHA256 hash")
    input_schema = models.JSONField(null=True, blank=True)
    output_schema = models.JSONField(null=True, blank=True)
    requirements = models.JSONField(default=list, help_text="pip packages")
    commit_message = models.TextField(blank=True, default="")
    author = models.ForeignKey(
        "users.UserProfile",
        on_delete=models.SET_NULL,
        null=True,
        related_name="code_versions",
    )
    git_commit = models.ForeignKey(
        "workflows.GitCommit",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="code_versions",
    )
    source = models.CharField(
        max_length=10,
        choices=Source.choices,
        default=Source.UI,
    )
    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("code_block", "version_number")]
        ordering = ["-version_number"]

    def __str__(self):
        return f"{self.code_block.name} v{self.version_number}"


class CodeBlockTest(models.Model):
    code_block = models.ForeignKey(
        CodeBlock,
        on_delete=models.CASCADE,
        related_name="tests",
    )
    name = models.CharField(max_length=255)
    input_data = models.JSONField()
    expected_output = models.JSONField(null=True, blank=True)
    expected_error = models.CharField(max_length=500, blank=True, default="")

    def __str__(self):
        return f"Test: {self.name} ({self.code_block.name})"


class CodeBlockTestRun(models.Model):
    version = models.ForeignKey(
        CodeBlockVersion,
        on_delete=models.CASCADE,
        related_name="test_runs",
    )
    test = models.ForeignKey(
        CodeBlockTest,
        on_delete=models.CASCADE,
        related_name="runs",
    )
    passed = models.BooleanField()
    actual_output = models.JSONField(null=True, blank=True)
    error = models.TextField(blank=True, default="")
    execution_time_ms = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        status = "PASS" if self.passed else "FAIL"
        return f"{status}: {self.test.name} on {self.version}"

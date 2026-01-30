from django.db import models


class ToolDefinition(models.Model):
    class ToolType(models.TextChoices):
        WEB_SEARCH = "web_search", "Web Search"
        BROWSER = "browser", "Browser"
        API = "api", "API"
        CUSTOM = "custom", "Custom"

    name = models.CharField(max_length=255, unique=True)
    tool_type = models.CharField(max_length=20, choices=ToolType.choices)
    description = models.TextField(blank=True, default="")
    input_schema = models.JSONField(null=True, blank=True)
    default_config = models.JSONField(default=dict)
    credential_type = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="What credential type is needed",
    )

    def __str__(self):
        return self.name


class WorkflowTool(models.Model):
    workflow = models.ForeignKey(
        "workflows.Workflow",
        on_delete=models.CASCADE,
        related_name="tools",
    )
    tool_definition = models.ForeignKey(
        ToolDefinition,
        on_delete=models.CASCADE,
        related_name="workflow_tools",
    )
    config_overrides = models.JSONField(default=dict)
    enabled = models.BooleanField(default=True)
    priority = models.IntegerField(default=0)

    class Meta:
        ordering = ["priority"]

    def __str__(self):
        return f"{self.tool_definition.name} in {self.workflow}"


class ToolCredentialMapping(models.Model):
    tool_definition = models.ForeignKey(
        ToolDefinition,
        on_delete=models.CASCADE,
        related_name="credential_mappings",
    )
    tool_credential = models.ForeignKey(
        "credentials.ToolCredential",
        on_delete=models.CASCADE,
        related_name="tool_mappings",
    )
    user_profile = models.ForeignKey(
        "users.UserProfile",
        on_delete=models.CASCADE,
        related_name="tool_credential_mappings",
    )
    is_default = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.tool_definition.name} <- {self.tool_credential}"

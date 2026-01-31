from django.db import models


class ComponentType(models.TextChoices):
    CATEGORIZER = "categorizer", "Categorizer"
    ROUTER = "router", "Router"
    EXTRACTOR = "extractor", "Extractor"
    AI_MODEL = "ai_model", "AI Model"
    SIMPLE_AGENT = "simple_agent", "Simple Agent"
    PLANNER_AGENT = "planner_agent", "Planner Agent"
    TOOL_NODE = "tool_node", "Tool Node"
    AGGREGATOR = "aggregator", "Aggregator"
    HUMAN_CONFIRMATION = "human_confirmation", "Human Confirmation"
    PARALLEL = "parallel", "Parallel"
    WORKFLOW = "workflow", "Workflow"
    CODE = "code", "Code"
    LOOP = "loop", "Loop"
    WAIT = "wait", "Wait"
    MERGE = "merge", "Merge"
    FILTER = "filter", "Filter"
    TRANSFORM = "transform", "Transform"
    SORT = "sort", "Sort"
    LIMIT = "limit", "Limit"
    HTTP_REQUEST = "http_request", "HTTP Request"
    ERROR_HANDLER = "error_handler", "Error Handler"
    OUTPUT_PARSER = "output_parser", "Output Parser"
    TRIGGER_TELEGRAM = "trigger_telegram", "Trigger: Telegram"
    TRIGGER_WEBHOOK = "trigger_webhook", "Trigger: Webhook"
    TRIGGER_SCHEDULE = "trigger_schedule", "Trigger: Schedule"
    TRIGGER_MANUAL = "trigger_manual", "Trigger: Manual"
    TRIGGER_WORKFLOW = "trigger_workflow", "Trigger: Workflow"
    TRIGGER_ERROR = "trigger_error", "Trigger: Error"
    TRIGGER_CHAT = "trigger_chat", "Trigger: Chat"


class BaseComponentConfig(models.Model):
    """Base config for all workflow components. Uses multi-table inheritance."""

    component_type = models.CharField(max_length=30, choices=ComponentType.choices)
    extra_config = models.JSONField(
        default=dict,
        help_text="temperature, max_tokens, categories, etc.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Config({self.component_type})"

    @property
    def concrete(self):
        """Return the concrete child config instance."""
        for attr in (
            "modelcomponentconfig",
            "aicomponentconfig",
            "codecomponentconfig",
            "toolcomponentconfig",
            "othercomponentconfig",
            "triggercomponentconfig",
        ):
            try:
                return getattr(self, attr)
            except self.__class__.DoesNotExist:
                continue
            except Exception:
                continue
        return self


class ModelComponentConfig(BaseComponentConfig):
    """Config for ai_model nodes — has direct LLM references."""

    llm_credential = models.ForeignKey(
        "credentials.BaseCredentials",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    model_name = models.CharField(max_length=255, blank=True, default="")
    # LLM parameters — None means "use provider default"
    temperature = models.FloatField(null=True, blank=True)
    max_tokens = models.IntegerField(null=True, blank=True)
    frequency_penalty = models.FloatField(null=True, blank=True)
    presence_penalty = models.FloatField(null=True, blank=True)
    top_p = models.FloatField(null=True, blank=True)
    timeout = models.IntegerField(null=True, blank=True)
    max_retries = models.IntegerField(null=True, blank=True)
    response_format = models.JSONField(null=True, blank=True)


class AIComponentConfig(BaseComponentConfig):
    """Config for AI components (simple_agent, planner_agent, categorizer, router, extractor).

    LLM is resolved via edge to an ai_model node, not stored here.
    """

    system_prompt = models.TextField(blank=True, default="")
    response_format = models.JSONField(null=True, blank=True)


class CodeComponentConfig(BaseComponentConfig):
    """Config for code-type components (code, loop, filter, transform, sort, limit, merge, wait, parallel, error_handler)."""

    code_language = models.CharField(max_length=20, blank=True, default="python")
    code_snippet = models.TextField(blank=True, default="")


class ToolComponentConfig(BaseComponentConfig):
    """Config for tool_node and http_request. Tool config lives in extra_config."""

    pass


class OtherComponentConfig(BaseComponentConfig):
    """Config for human_confirmation, aggregator, workflow, output_parser."""

    pass


class TriggerComponentConfig(BaseComponentConfig):
    """Config for trigger nodes (telegram, webhook, schedule, manual, workflow, error)."""

    credential = models.ForeignKey(
        "credentials.BaseCredentials",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    is_active = models.BooleanField(default=True)
    priority = models.IntegerField(default=0)
    trigger_config = models.JSONField(default=dict)


# Mapping from component_type to config subclass
COMPONENT_TYPE_TO_CONFIG = {
    "ai_model": ModelComponentConfig,
    "simple_agent": AIComponentConfig,
    "planner_agent": AIComponentConfig,
    "categorizer": AIComponentConfig,
    "router": AIComponentConfig,
    "extractor": AIComponentConfig,
    "code": CodeComponentConfig,
    "loop": CodeComponentConfig,
    "filter": CodeComponentConfig,
    "transform": CodeComponentConfig,
    "sort": CodeComponentConfig,
    "limit": CodeComponentConfig,
    "merge": CodeComponentConfig,
    "wait": CodeComponentConfig,
    "parallel": CodeComponentConfig,
    "error_handler": CodeComponentConfig,
    "tool_node": ToolComponentConfig,
    "http_request": ToolComponentConfig,
    "human_confirmation": OtherComponentConfig,
    "aggregator": OtherComponentConfig,
    "workflow": OtherComponentConfig,
    "output_parser": OtherComponentConfig,
    "trigger_telegram": TriggerComponentConfig,
    "trigger_webhook": TriggerComponentConfig,
    "trigger_schedule": TriggerComponentConfig,
    "trigger_manual": TriggerComponentConfig,
    "trigger_workflow": TriggerComponentConfig,
    "trigger_error": TriggerComponentConfig,
    "trigger_chat": TriggerComponentConfig,
}


class WorkflowNode(models.Model):
    workflow = models.ForeignKey(
        "workflows.Workflow",
        on_delete=models.CASCADE,
        related_name="nodes",
    )
    node_id = models.CharField(max_length=255)
    component_type = models.CharField(max_length=30, choices=ComponentType.choices)
    component_config = models.ForeignKey(
        BaseComponentConfig,
        on_delete=models.CASCADE,
        related_name="nodes",
    )
    subworkflow = models.ForeignKey(
        "workflows.Workflow",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="used_as_subworkflow_in",
    )
    code_block = models.ForeignKey(
        "workflows.CodeBlock",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="nodes",
    )
    is_entry_point = models.BooleanField(default=False)
    interrupt_before = models.BooleanField(default=False)
    interrupt_after = models.BooleanField(default=False)
    position_x = models.IntegerField(default=0)
    position_y = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("workflow", "node_id")]

    def __str__(self):
        return f"{self.node_id} ({self.component_type})"


class EdgeLabel(models.TextChoices):
    NONE = "", "Control Flow"
    LLM = "llm", "LLM"
    TOOL = "tool", "Tool"
    MEMORY = "memory", "Memory"
    OUTPUT_PARSER = "output_parser", "Output Parser"


class WorkflowEdge(models.Model):
    class EdgeType(models.TextChoices):
        DIRECT = "direct", "Direct"
        CONDITIONAL = "conditional", "Conditional"

    workflow = models.ForeignKey(
        "workflows.Workflow",
        on_delete=models.CASCADE,
        related_name="edges",
    )
    source_node_id = models.CharField(max_length=255)
    target_node_id = models.CharField(max_length=255, blank=True, default="")
    edge_type = models.CharField(
        max_length=15,
        choices=EdgeType.choices,
        default=EdgeType.DIRECT,
    )
    edge_label = models.CharField(
        max_length=20,
        choices=EdgeLabel.choices,
        default=EdgeLabel.NONE,
        blank=True,
    )
    condition_mapping = models.JSONField(
        null=True,
        blank=True,
        help_text="route -> target node mapping for conditional edges",
    )
    priority = models.IntegerField(default=0)

    class Meta:
        ordering = ["priority"]

    def __str__(self):
        label = f" [{self.edge_label}]" if self.edge_label else ""
        return f"{self.source_node_id} -> {self.target_node_id or '(conditional)'}{label}"

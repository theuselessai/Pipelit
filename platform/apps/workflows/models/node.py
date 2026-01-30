from django.db import models


class ComponentType(models.TextChoices):
    CATEGORIZER = "categorizer", "Categorizer"
    ROUTER = "router", "Router"
    CHAT_MODEL = "chat_model", "Chat Model"
    REACT_AGENT = "react_agent", "React Agent"
    PLAN_AND_EXECUTE = "plan_and_execute", "Plan and Execute"
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


class ComponentConfig(models.Model):
    component_type = models.CharField(max_length=30, choices=ComponentType.choices)
    llm_model = models.ForeignKey(
        "credentials.LLMModel",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    llm_credential = models.ForeignKey(
        "credentials.LLMProviderCredentials",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    system_prompt = models.TextField(blank=True, default="")
    extra_config = models.JSONField(
        default=dict,
        help_text="temperature, max_tokens, categories, etc.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Config({self.component_type})"


class WorkflowNode(models.Model):
    workflow = models.ForeignKey(
        "workflows.Workflow",
        on_delete=models.CASCADE,
        related_name="nodes",
    )
    node_id = models.CharField(max_length=255)
    component_type = models.CharField(max_length=30, choices=ComponentType.choices)
    component_config = models.ForeignKey(
        ComponentConfig,
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
    condition_mapping = models.JSONField(
        null=True,
        blank=True,
        help_text="route -> target node mapping for conditional edges",
    )
    priority = models.IntegerField(default=0)

    class Meta:
        ordering = ["priority"]

    def __str__(self):
        return f"{self.source_node_id} -> {self.target_node_id or '(conditional)'}"

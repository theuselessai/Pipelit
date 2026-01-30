from django.contrib import admin

from .models import (
    CodeBlock,
    CodeBlockTest,
    CodeBlockTestRun,
    CodeBlockVersion,
    ComponentConfig,
    ExecutionLog,
    GitCommit,
    GitRepository,
    GitSyncTask,
    PendingTask,
    ToolCredentialMapping,
    ToolDefinition,
    Workflow,
    WorkflowCollaborator,
    WorkflowEdge,
    WorkflowExecution,
    WorkflowNode,
    WorkflowTool,
    WorkflowTrigger,
)


@admin.register(Workflow)
class WorkflowAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "owner", "is_active", "is_default", "created_at")
    list_filter = ("is_active", "is_public", "is_template", "is_callable", "is_default")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(WorkflowCollaborator)
class WorkflowCollaboratorAdmin(admin.ModelAdmin):
    list_display = ("workflow", "user_profile", "role", "invited_at")


@admin.register(WorkflowTrigger)
class WorkflowTriggerAdmin(admin.ModelAdmin):
    list_display = ("workflow", "trigger_type", "is_active", "priority")
    list_filter = ("trigger_type", "is_active")


@admin.register(ComponentConfig)
class ComponentConfigAdmin(admin.ModelAdmin):
    list_display = ("id", "component_type", "llm_model")


@admin.register(WorkflowNode)
class WorkflowNodeAdmin(admin.ModelAdmin):
    list_display = ("node_id", "workflow", "component_type", "is_entry_point")
    list_filter = ("component_type", "is_entry_point")


@admin.register(WorkflowEdge)
class WorkflowEdgeAdmin(admin.ModelAdmin):
    list_display = ("workflow", "source_node_id", "target_node_id", "edge_type")
    list_filter = ("edge_type",)


@admin.register(ToolDefinition)
class ToolDefinitionAdmin(admin.ModelAdmin):
    list_display = ("name", "tool_type")


@admin.register(WorkflowTool)
class WorkflowToolAdmin(admin.ModelAdmin):
    list_display = ("workflow", "tool_definition", "enabled", "priority")


@admin.register(ToolCredentialMapping)
class ToolCredentialMappingAdmin(admin.ModelAdmin):
    list_display = ("tool_definition", "tool_credential", "user_profile", "is_default")


@admin.register(CodeBlock)
class CodeBlockAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "workflow", "language")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(CodeBlockVersion)
class CodeBlockVersionAdmin(admin.ModelAdmin):
    list_display = ("code_block", "version_number", "status", "source", "created_at")
    list_filter = ("status", "source")


@admin.register(CodeBlockTest)
class CodeBlockTestAdmin(admin.ModelAdmin):
    list_display = ("name", "code_block")


@admin.register(CodeBlockTestRun)
class CodeBlockTestRunAdmin(admin.ModelAdmin):
    list_display = ("test", "version", "passed", "execution_time_ms")
    list_filter = ("passed",)


@admin.register(GitRepository)
class GitRepositoryAdmin(admin.ModelAdmin):
    list_display = ("name", "provider", "auto_sync_enabled", "last_synced_at")


@admin.register(GitCommit)
class GitCommitAdmin(admin.ModelAdmin):
    list_display = ("commit_hash", "repository", "author", "committed_at")


@admin.register(GitSyncTask)
class GitSyncTaskAdmin(admin.ModelAdmin):
    list_display = ("repository", "direction", "status", "created_at")
    list_filter = ("direction", "status")


@admin.register(WorkflowExecution)
class WorkflowExecutionAdmin(admin.ModelAdmin):
    list_display = ("execution_id", "workflow", "status", "started_at")
    list_filter = ("status",)


@admin.register(ExecutionLog)
class ExecutionLogAdmin(admin.ModelAdmin):
    list_display = ("execution", "node_id", "status", "duration_ms", "timestamp")
    list_filter = ("status",)


@admin.register(PendingTask)
class PendingTaskAdmin(admin.ModelAdmin):
    list_display = ("task_id", "execution", "node_id", "expires_at")

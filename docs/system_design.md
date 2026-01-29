# Workflow Automation Platform - System Design

## Overview

A workflow automation platform that:
- Executes LangGraph-based workflows triggered by various sources (Telegram, schedules, webhooks, other workflows)
- Supports collaborative editing with per-workflow Git repositories
- Provides version-controlled code blocks with testing and deployment pipelines
- Uses Django-RQ for async execution and Redis/PostgreSQL for state management

## Technology Stack

| Layer | Technology |
|-------|------------|
| Framework | Django 5.x |
| Async Queue | Django-RQ (Redis Queue) |
| Workflow Engine | LangGraph |
| LLM Framework | LangChain |
| Database | PostgreSQL |
| Cache | Redis |
| Checkpointing | LangGraph PostgresSaver |
| Version Control | Git (GitHub/GitLab/Bitbucket) |
| Bot Interface | python-telegram-bot |

---

## Domain Model

### Entity Relationship Diagram

```mermaid
erDiagram
    %% ==================== USER & AUTH ====================
    DjangoUser ||--|| UserProfile : "one-to-one"
    UserProfile ||--o{ Workflow : "owns"
    UserProfile ||--o{ WorkflowCollaborator : "collaborates on"
    UserProfile ||--o{ GitCredential : "has credentials"
    UserProfile ||--o{ WorkflowExecution : "runs"
    UserProfile ||--o{ GitCommit : "authors"

    DjangoUser {
        int id PK
        string username
        string email
        string password
        bool is_active
        datetime date_joined
    }

    UserProfile {
        int id PK
        int django_user_id FK
        bigint telegram_user_id UK
        string github_username
        string gitlab_username
        datetime created_at
    }

    %% ==================== CREDENTIALS ====================
    BaseCredentials ||--o| GitCredential : "extends"
    BaseCredentials ||--o| LLMProviderCredentials : "extends"
    BaseCredentials ||--o| TelegramCredential : "extends"
    BaseCredentials ||--o| ToolCredential : "extends"
    LLMProviderCredentials }o--|| LLMProvider : "uses"
    LLMProvider ||--o{ LLMModel : "offers"

    BaseCredentials {
        int id PK
        int user_profile_id FK
        string name
        string credential_type "discriminator"
        datetime created_at
        datetime updated_at
    }

    GitCredential {
        int id PK
        int base_credentials_id FK
        string provider "github | gitlab | bitbucket"
        string credential_type "ssh_key | token | app"
        text ssh_private_key "encrypted"
        string access_token "encrypted"
        string username
        string webhook_secret
    }

    LLMProviderCredentials {
        int id PK
        int base_credentials_id FK
        int provider_id FK
        string api_key "encrypted"
        string base_url
    }

    LLMProvider {
        int id PK
        string name "openai | anthropic | openai_compatible"
        string provider_type
    }

    LLMModel {
        int id PK
        int provider_id FK
        string model_name
        float default_temperature
        int context_window
    }

    TelegramCredential {
        int id PK
        int base_credentials_id FK
        string bot_token "encrypted"
        string allowed_user_ids "comma-separated"
    }

    ToolCredential {
        int id PK
        int base_credentials_id FK
        string tool_type "searxng | browser | api"
        json config "encrypted sensitive fields"
    }

    %% ==================== WORKFLOW CORE ====================
    Workflow }o--o| LLMProviderCredentials : "default LLM credential"
    Workflow }o--o| TelegramCredential : "runs on bot"
    Workflow ||--|| GitRepository : "has dedicated repo"
    Workflow ||--o{ WorkflowCollaborator : "has collaborators"
    Workflow ||--|{ WorkflowTrigger : "activated by"
    Workflow ||--|{ WorkflowNode : "contains"
    Workflow ||--o{ WorkflowEdge : "defines"
    Workflow ||--o{ WorkflowTool : "has tools"
    Workflow ||--o{ CodeBlock : "contains code"
    Workflow ||--o{ WorkflowExecution : "runs as"
    Workflow ||--o| Workflow : "forked from"

    Workflow {
        int id PK
        string name
        string slug UK
        text description
        int owner_id FK "UserProfile"
        int repository_id FK "GitRepository"
        int default_llm_credential_id FK "LLMProviderCredentials, nullable — default LLM for this workflow"
        int default_llm_model_id FK "LLMModel, nullable — inherited by nodes without explicit model"
        int telegram_credential_id FK "TelegramCredential, nullable — which bot runs this workflow"
        bool is_active
        bool is_public "discoverable"
        bool is_template "can be forked"
        bool is_callable "can be invoked by other workflows"
        bool is_default "fallback for user"
        int forked_from_id FK "Workflow, nullable"
        json input_schema "for callable workflows"
        json output_schema "for callable workflows"
        datetime created_at
        datetime updated_at
        datetime deleted_at "nullable, soft-delete"
    }

    WorkflowCollaborator {
        int id PK
        int workflow_id FK
        int user_profile_id FK
        string role "owner | editor | viewer"
        int invited_by_id FK "UserProfile"
        datetime invited_at
        datetime accepted_at
    }

    %% ==================== TRIGGERS ====================
    WorkflowTrigger {
        int id PK
        int workflow_id FK
        string trigger_type "telegram_message | telegram_chat | schedule | webhook | manual | workflow"
        json config "type-specific configuration"
        bool is_active
        int priority "for matching order"
        datetime created_at
    }

    %% ==================== NODES & EDGES ====================
    WorkflowNode }o--|| ComponentConfig : "configured by"
    WorkflowNode }o--o| Workflow : "calls subworkflow"
    WorkflowNode }o--o| CodeBlock : "uses code block"

    WorkflowNode {
        int id PK
        int workflow_id FK
        string node_id "unique_together(workflow_id, node_id)"
        string component_type "categorizer | router | chat_model | react_agent | plan_and_execute | tool_node | aggregator | human_confirmation | parallel | workflow | code"
        int component_config_id FK
        int subworkflow_id FK "if type = workflow"
        int code_block_id FK "if type = code"
        bool is_entry_point
        bool interrupt_before "human-in-loop"
        bool interrupt_after
        int position_x "UI layout"
        int position_y "UI layout"
        datetime updated_at
    }

    WorkflowEdge {
        int id PK
        int workflow_id FK
        string source_node_id FK
        string target_node_id FK "nullable, set for unconditional edges"
        string edge_type "direct | conditional"
        json condition_mapping "route -> target node mapping, set for conditional edges"
        int priority "edge selection order"
    }

    ComponentConfig {
        int id PK
        string component_type
        int llm_model_id FK "nullable"
        string system_prompt
        json extra_config "temperature, max_tokens, categories, etc"
        datetime updated_at
    }

    %% ==================== TOOLS ====================
    ToolDefinition ||--o{ WorkflowTool : "used in"
    ToolDefinition ||--o{ ToolCredentialMapping : "requires"
    ToolCredentialMapping }o--|| ToolCredential : "uses"

    ToolDefinition {
        int id PK
        string name UK "unique tool identifier"
        string tool_type "web_search | browser | api | custom"
        string description
        json input_schema "JSON schema for args"
        json default_config
        string credential_type "what credential type needed"
    }

    WorkflowTool {
        int id PK
        int workflow_id FK
        int tool_definition_id FK
        json config_overrides "per-workflow config"
        bool enabled
        int priority "for tool selection ordering"
    }

    ToolCredentialMapping {
        int id PK
        int tool_definition_id FK
        int tool_credential_id FK
        int user_profile_id FK
        bool is_default
    }

    %% ==================== CODE BLOCKS ====================
    CodeBlock ||--|{ CodeBlockVersion : "has versions"
    CodeBlock ||--o{ CodeBlockTest : "has tests"
    CodeBlockVersion ||--o{ CodeBlockTestRun : "test results"
    CodeBlockVersion }o--o| GitCommit : "tracked by"

    %% Source of truth: PostgreSQL (CodeBlockVersion.code).
    %% Git repo is the sync/export target. On pull from Git,
    %% a new CodeBlockVersion is created from the file contents.
    %% code_hash is used to detect drift between DB and Git.
    CodeBlock {
        int id PK
        int workflow_id FK
        string name
        string slug UK
        text description
        string language "python"
        int timeout_seconds
        string file_path "code/slug.py — derived, for Git export"
        int published_version_id FK "CodeBlockVersion"
        int draft_version_id FK "CodeBlockVersion"
        datetime created_at
        datetime updated_at
    }

    CodeBlockVersion {
        int id PK
        int code_block_id FK
        int version_number
        text code "source of truth"
        string code_hash "SHA256 — used to detect Git drift"
        json input_schema
        json output_schema
        json requirements "pip packages"
        string commit_message
        int author_id FK "UserProfile"
        int git_commit_id FK "GitCommit, nullable"
        string source "ui | git_pull — where this version originated"
        string status "draft | testing | published | deprecated"
        datetime created_at
    }

    CodeBlockTest {
        int id PK
        int code_block_id FK
        string name
        json input_data
        json expected_output
        string expected_error
    }

    CodeBlockTestRun {
        int id PK
        int version_id FK "CodeBlockVersion"
        int test_id FK "CodeBlockTest"
        bool passed
        json actual_output
        text error
        int execution_time_ms
        datetime created_at
    }

    %% ==================== GIT VERSION CONTROL ====================
    GitRepository ||--o{ GitCommit : "has commits"
    GitRepository ||--o{ GitSyncTask : "sync history"
    GitRepository }o--|| GitCredential : "authenticated by"

    GitRepository {
        int id PK
        string name "workflow slug"
        int credential_id FK "GitCredential"
        string provider "github | gitlab | bitbucket"
        string remote_url
        string default_branch "main"
        string local_path "/data/repos/workflow_id"
        string last_commit_hash
        datetime last_synced_at
        bool auto_sync_enabled
        string webhook_url "for incoming webhooks"
        datetime created_at
    }

    GitCommit {
        int id PK
        int repository_id FK
        string commit_hash UK
        string message
        int author_id FK "UserProfile, nullable"
        json files_changed
        int additions
        int deletions
        datetime committed_at
        datetime synced_at
    }

    GitSyncTask {
        int id PK
        int repository_id FK
        string direction "push | pull | both"
        string status "pending | running | completed | failed"
        string commit_message
        string commit_hash
        json files_changed
        text error_log
        int retry_count
        int max_retries
        int triggered_by_id FK "UserProfile, nullable"
        datetime created_at
        datetime started_at
        datetime completed_at
    }

    %% ==================== EXECUTION ====================
    WorkflowExecution ||--o| WorkflowExecution : "parent (if subworkflow)"
    WorkflowExecution ||--o{ ExecutionLog : "logs"
    WorkflowExecution }o--o| WorkflowTrigger : "triggered by"
    WorkflowExecution ||--o{ PendingTask : "awaits"

    WorkflowExecution {
        string execution_id PK "UUID"
        int workflow_id FK
        int trigger_id FK "nullable if called by workflow"
        string parent_execution_id FK "nullable if root"
        string parent_node_id "which node invoked this"
        int user_profile_id FK
        string thread_id "LangGraph thread"
        string status "pending | running | interrupted | completed | failed | cancelled"
        json trigger_payload "initial data from trigger"
        json final_output
        int retry_count "default 0"
        int max_retries "default 3"
        text error_message "last error, nullable"
        datetime started_at
        datetime completed_at
    }

    ExecutionLog {
        int id PK
        string execution_id FK
        string node_id
        string status "started | completed | failed | skipped"
        json input
        json output
        text error
        int duration_ms
        datetime timestamp
    }

    %% PendingTask is stored in PostgreSQL for persistence and
    %% queryability (FK to execution, user). Expiry is enforced at
    %% the application layer by checking expires_at on lookup.
    %% A periodic cleanup job deletes expired rows.
    PendingTask {
        string task_id PK "8-char UUID"
        string execution_id FK
        int user_profile_id FK
        bigint telegram_chat_id
        string node_id "which node is waiting"
        string prompt "message shown to user"
        datetime created_at
        datetime expires_at "app-enforced TTL, cleanup job deletes expired"
    }

    %% ==================== CONVERSATION ====================
    UserProfile ||--o{ Conversation : "has"
    Conversation }o--o| WorkflowExecution : "linked to"

    Conversation {
        int id PK
        int user_profile_id FK
        string thread_id "LangGraph thread reference"
        int workflow_id FK
        int execution_id FK "WorkflowExecution, nullable"
        json metadata
        datetime created_at
        datetime updated_at
    }

    %% ==================== SYSTEM ====================
    %% Infrastructure config (redis, database, etc.) stays in environment
    %% variables since it's needed before the DB is accessible.
    %% SystemConfig holds only application-level settings.
    SystemConfig {
        int id PK "singleton"
        int default_llm_model_id FK "nullable, global default LLM"
        string default_timezone "UTC"
        int max_workflow_execution_seconds "600"
        int confirmation_timeout_seconds "300"
        json feature_flags
        datetime updated_at
    }
```

---

## Component Types

### Component Type Hierarchy

```mermaid
classDiagram
    class BaseWorkflowComponent {
        <<interface>>
        +string component_type
        +execute(state, config) dict
    }

    class Categorizer {
        +list~Category~ categories
        +float confidence_threshold
        +string fallback_category
        +string system_prompt
        Sets state.route based on LLM classification
    }

    class Router {
        +string condition_expression
        +dict condition_mapping
        Rule-based routing without LLM
    }

    class ChatModel {
        +int llm_model_id
        +string system_prompt
        +float temperature
        Single LLM completion
    }

    class ReactAgent {
        +int llm_model_id
        +list~Tool~ tools
        +string system_prompt
        ReAct pattern with tool calling
    }

    class PlanAndExecute {
        +int planner_llm_id
        +int executor_llm_id
        +list~Tool~ tools
        +int max_replans
        Dynamic planning agent
    }

    class ToolNode {
        +list~Tool~ tools
        Execute tool calls from previous node
    }

    class Aggregator {
        +string strategy "collect | race | all_settled"
        Combine parallel branch results
    }

    class HumanConfirmation {
        +string prompt_template
        +int timeout_seconds
        Wait for user confirmation
    }

    class Parallel {
        +list~Branch~ branches
        +string aggregation
        Execute branches in parallel
    }

    class WorkflowNode {
        +int subworkflow_id
        +dict input_mapping
        +dict output_mapping
        Call another workflow as subgraph
    }

    class CodeNode {
        +int code_block_id
        +string inline_code
        +dict input_mapping
        Execute Python code safely
    }

    BaseWorkflowComponent <|-- Categorizer
    BaseWorkflowComponent <|-- Router
    BaseWorkflowComponent <|-- ChatModel
    BaseWorkflowComponent <|-- ReactAgent
    BaseWorkflowComponent <|-- PlanAndExecute
    BaseWorkflowComponent <|-- ToolNode
    BaseWorkflowComponent <|-- Aggregator
    BaseWorkflowComponent <|-- HumanConfirmation
    BaseWorkflowComponent <|-- Parallel
    BaseWorkflowComponent <|-- WorkflowNode
    BaseWorkflowComponent <|-- CodeNode
```

### Component Type Enum

```python
from enum import Enum

class ComponentType(str, Enum):
    # Routing & Classification
    CATEGORIZER = "categorizer"      # LLM-based intent classification
    ROUTER = "router"                # Rule-based conditional routing
    
    # LLM Components
    CHAT_MODEL = "chat_model"        # Single LLM call
    REACT_AGENT = "react_agent"      # ReAct pattern with tools
    PLAN_AND_EXECUTE = "plan_and_execute"  # Dynamic planning agent
    
    # Tool Execution
    TOOL_NODE = "tool_node"          # Execute tool calls
    
    # Control Flow
    AGGREGATOR = "aggregator"        # Combine parallel results
    HUMAN_CONFIRMATION = "human_confirmation"  # Await user input
    PARALLEL = "parallel"            # Concurrent branch execution
    
    # Composition
    WORKFLOW = "workflow"            # Call another workflow
    
    # Code Execution
    CODE = "code"                    # Execute Python code
```

---

## Trigger Types

### Trigger Type Hierarchy

```mermaid
classDiagram
    class BaseTrigger {
        <<interface>>
        +string trigger_type
        +bool is_active
        +int priority
    }

    class TelegramMessageTrigger {
        +string pattern "regex"
        +string command "/command"
        +list~string~ chat_types
        One-shot message trigger
    }

    class TelegramChatTrigger {
        +string pattern
        +string command
        +list~string~ chat_types
        +int session_timeout_minutes
        Conversational with thread state
    }

    class ScheduleTrigger {
        +string cron_expression
        +string timezone
        +dict payload
        Cron-based scheduled execution
    }

    class WebhookTrigger {
        +string path
        +list~string~ methods
        +string auth_type
        +string auth_secret_key
        HTTP endpoint trigger
    }

    class ManualTrigger {
        +dict input_schema
        UI or API triggered
    }

    class WorkflowTrigger {
        +dict input_schema
        Called by another workflow
    }

    BaseTrigger <|-- TelegramMessageTrigger
    BaseTrigger <|-- TelegramChatTrigger
    BaseTrigger <|-- ScheduleTrigger
    BaseTrigger <|-- WebhookTrigger
    BaseTrigger <|-- ManualTrigger
    BaseTrigger <|-- WorkflowTrigger
```

### Trigger Type Enum

```python
from enum import Enum

class TriggerType(str, Enum):
    # External triggers
    TELEGRAM_MESSAGE = "telegram_message"  # One-shot message
    TELEGRAM_CHAT = "telegram_chat"        # Conversational with thread
    SCHEDULE = "schedule"                   # Cron-based
    WEBHOOK = "webhook"                     # HTTP endpoint
    MANUAL = "manual"                       # UI/API triggered
    
    # Internal triggers
    WORKFLOW = "workflow"                   # Called by another workflow
```

### Trigger Configuration Schemas

The `WorkflowTrigger.config` JSON field is validated at the application layer
using these Pydantic models (dispatched by `trigger_type`). Django model `clean()`
calls the appropriate schema on save; invalid configs raise `ValidationError`.

```python
from pydantic import BaseModel
from typing import Literal

class TelegramMessageTriggerConfig(BaseModel):
    """One-shot telegram message trigger"""
    trigger_type: Literal["telegram_message"] = "telegram_message"
    pattern: str | None = None              # Regex pattern to match
    command: str | None = None              # /command to match
    chat_types: list[str] = ["private"]     # private, group, supergroup

class TelegramChatTriggerConfig(BaseModel):
    """Conversational telegram trigger - maintains thread state"""
    trigger_type: Literal["telegram_chat"] = "telegram_chat"
    pattern: str | None = None
    command: str | None = None
    chat_types: list[str] = ["private"]
    session_timeout_minutes: int = 30       # Thread expires after inactivity

class ScheduleTriggerConfig(BaseModel):
    """Cron-based scheduled trigger"""
    trigger_type: Literal["schedule"] = "schedule"
    cron_expression: str                    # "0 9 * * *" = 9am daily
    timezone: str = "UTC"
    payload: dict = {}                      # Static payload to pass

class WebhookTriggerConfig(BaseModel):
    """HTTP webhook trigger"""
    trigger_type: Literal["webhook"] = "webhook"
    path: str                               # /webhook/my-endpoint
    methods: list[str] = ["POST"]
    auth_type: str | None = None            # "bearer", "basic", "hmac"
    auth_secret_key: str | None = None      # Reference to credential

class ManualTriggerConfig(BaseModel):
    """Manual trigger via UI or API"""
    trigger_type: Literal["manual"] = "manual"
    input_schema: dict | None = None        # JSON schema for required input

class WorkflowTriggerConfig(BaseModel):
    """Called by another workflow"""
    trigger_type: Literal["workflow"] = "workflow"
    input_schema: dict | None = None        # Expected input schema
```

---

## Workflow State (LangGraph)

### State Schema

```python
from typing import Annotated, TypedDict, Any
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage

class UserContext(TypedDict):
    """Immutable context passed through workflow"""
    user_profile_id: int
    telegram_chat_id: int | None
    telegram_user_id: int | None
    conversation_id: int | None
    thread_id: str

class TriggerPayload(TypedDict):
    """Normalized payload from any trigger type"""
    trigger_type: str
    trigger_id: int
    timestamp: str  # ISO format
    source: dict    # trigger-specific source info
    user_profile_id: int | None
    data: dict      # the actual payload data
    thread_id: str | None
    is_continuation: bool

class PlanStep(TypedDict):
    """For PlanAndExecute agents"""
    order: int
    action: str
    agent: str      # which tool/agent to use
    status: str     # pending | running | completed | failed | skipped
    result: str | None
    error: str | None
    depends_on: list[int]

class PlanState(TypedDict, total=False):
    """Optional planning state - only used by planner nodes"""
    goal: str
    steps: list[PlanStep]
    current_step: int
    replan_count: int
    max_replans: int

class WorkflowState(TypedDict, total=False):
    """
    Main state schema for all workflows.
    Using total=False so fields are optional.
    """
    # ===== Trigger Context (set once at start) =====
    trigger: TriggerPayload
    
    # ===== Messages (for conversational workflows) =====
    messages: Annotated[list[BaseMessage], add_messages]
    
    # ===== User Context =====
    user_context: UserContext
    
    # ===== Execution Tracking =====
    current_node: str | None
    execution_id: str
    
    # ===== Routing =====
    route: str | None  # Set by categorizer/router
    
    # ===== Parallel Execution =====
    branch_results: dict[str, Any]  # Results from parallel branches
    
    # ===== Planning =====
    plan: PlanState | None  # For plan_and_execute nodes
    
    # ===== Node Outputs =====
    node_outputs: dict[str, Any]  # Keyed by node_id
    
    # ===== Final Output =====
    output: Any  # Set by terminal nodes
    
    # ===== Error Handling =====
    error: str | None
    should_retry: bool
```

---

## Message Flow

### Complete Flow Diagram

```mermaid
flowchart TD
    %% ==================== TRIGGER SOURCES ====================
    subgraph TriggerSources["1. Trigger Sources"]
        TG_MSG[Telegram Message]
        TG_CHAT[Telegram Chat]
        CRON[Scheduler]
        WEBHOOK[Webhook]
        MANUAL[Manual/API]
        PARENT_WF[Parent Workflow]
    end

    %% ==================== TRIGGER HANDLERS ====================
    subgraph TriggerHandlers["2. Trigger Handlers"]
        TG_HANDLER[TelegramTriggerHandler]
        SCHEDULE_HANDLER[ScheduleTriggerHandler]
        WEBHOOK_HANDLER[WebhookTriggerHandler]
        MANUAL_HANDLER[ManualTriggerHandler]
        INTERNAL_HANDLER[InternalTriggerHandler]
    end

    TG_MSG --> TG_HANDLER
    TG_CHAT --> TG_HANDLER
    CRON --> SCHEDULE_HANDLER
    WEBHOOK --> WEBHOOK_HANDLER
    MANUAL --> MANUAL_HANDLER
    PARENT_WF --> INTERNAL_HANDLER

    %% ==================== TRIGGER RESOLUTION ====================
    subgraph TriggerResolution["3. Trigger Resolution"]
        RESOLVER[TriggerResolver]
        
        ACTIVE_SESSION{Active Chat Session?}
        PATTERN_MATCH{Pattern Match?}
        DEFAULT_WF[Load Default Workflow]
        MATCHED_WF[Load Matched Workflow]
        CONTINUE_SESSION[Continue Existing Thread]
        
        RESOLVER --> ACTIVE_SESSION
        ACTIVE_SESSION --> |yes| CONTINUE_SESSION
        ACTIVE_SESSION --> |no| PATTERN_MATCH
        PATTERN_MATCH --> |yes| MATCHED_WF
        PATTERN_MATCH --> |no| DEFAULT_WF
    end

    TG_HANDLER --> RESOLVER
    SCHEDULE_HANDLER --> DIRECT_LOAD[Direct Load Workflow]
    WEBHOOK_HANDLER --> DIRECT_LOAD
    MANUAL_HANDLER --> DIRECT_LOAD
    INTERNAL_HANDLER --> DIRECT_LOAD

    %% ==================== PAYLOAD BUILDING ====================
    subgraph PayloadBuilding["4. Build Trigger Payload"]
        BUILD_PAYLOAD[Build TriggerPayload]
        
        BUILD_PAYLOAD --> |contains| PAYLOAD_DATA["
            trigger_type
            trigger_id
            timestamp
            source
            user_profile_id
            data
            thread_id
            is_continuation
        "]
    end

    CONTINUE_SESSION --> BUILD_PAYLOAD
    MATCHED_WF --> BUILD_PAYLOAD
    DEFAULT_WF --> BUILD_PAYLOAD
    DIRECT_LOAD --> BUILD_PAYLOAD

    %% ==================== GRAPH RESOLUTION ====================
    subgraph GraphResolution["5. Graph Resolution"]
        CACHE_CHECK{Graph in Memory Cache?}
        BUILD_GRAPH[WorkflowBuilder.build]
        CACHE_STORE[Store in Process Memory]
        GRAPH[CompiledGraph]

        CACHE_CHECK --> |hit| GRAPH
        CACHE_CHECK --> |miss| BUILD_GRAPH
        BUILD_GRAPH --> CACHE_STORE
        CACHE_STORE --> GRAPH
    end

    BUILD_PAYLOAD --> CACHE_CHECK

    %% ==================== EXECUTION SETUP ====================
    subgraph ExecutionSetup["6. Execution Setup"]
        THREAD_CHECK{Continuation?}
        LOAD_CHECKPOINT[Load Checkpoint from PostgreSQL]
        CREATE_EXECUTION[Create WorkflowExecution Record]
        PREPARE_STATE[Prepare Initial WorkflowState]
        
        THREAD_CHECK --> |yes| LOAD_CHECKPOINT
        THREAD_CHECK --> |no| CREATE_EXECUTION
        LOAD_CHECKPOINT --> PREPARE_STATE
        CREATE_EXECUTION --> PREPARE_STATE
    end

    GRAPH --> THREAD_CHECK

    %% ==================== JOB QUEUE ====================
    subgraph JobQueue["7. Django-RQ Queue"]
        ENQUEUE[Enqueue execute_workflow_job]
        RQ_WORKER[RQ Worker Picks Up Job]
    end

    PREPARE_STATE --> ENQUEUE
    ENQUEUE --> RQ_WORKER

    %% ==================== LANGGRAPH EXECUTION ====================
    subgraph LangGraphExecution["8. LangGraph Execution"]
        INVOKE[graph.invoke / graph.ainvoke]
        
        EXEC_NODE[Execute Current Node]
        NODE_TYPE{Node Type?}
        
        CATEGORIZER_EXEC[Categorizer]
        ROUTER_EXEC[Router]
        CHAT_EXEC[ChatModel]
        REACT_EXEC[ReactAgent]
        PLAN_EXEC[PlanAndExecute]
        TOOL_EXEC[ToolNode]
        AGG_EXEC[Aggregator]
        HUMAN_EXEC[HumanConfirmation]
        PARALLEL_EXEC[Parallel]
        SUBWF_EXEC[Workflow]
        CODE_EXEC[Code]
        
        NODE_TYPE --> |categorizer| CATEGORIZER_EXEC
        NODE_TYPE --> |router| ROUTER_EXEC
        NODE_TYPE --> |chat_model| CHAT_EXEC
        NODE_TYPE --> |react_agent| REACT_EXEC
        NODE_TYPE --> |plan_and_execute| PLAN_EXEC
        NODE_TYPE --> |tool_node| TOOL_EXEC
        NODE_TYPE --> |aggregator| AGG_EXEC
        NODE_TYPE --> |human_confirmation| HUMAN_EXEC
        NODE_TYPE --> |parallel| PARALLEL_EXEC
        NODE_TYPE --> |workflow| SUBWF_EXEC
        NODE_TYPE --> |code| CODE_EXEC
    end

    RQ_WORKER --> INVOKE
    INVOKE --> EXEC_NODE
    EXEC_NODE --> NODE_TYPE

    %% ==================== NODE RESULTS ====================
    subgraph NodeResults["9. Node Results"]
        NODE_RESULT[Node Result + State Update]
        CHECKPOINT_SAVE[Save Checkpoint to PostgreSQL]
        LOG_EXECUTION[Log to ExecutionLog]
    end

    CATEGORIZER_EXEC --> NODE_RESULT
    ROUTER_EXEC --> NODE_RESULT
    CHAT_EXEC --> NODE_RESULT
    REACT_EXEC --> NODE_RESULT
    PLAN_EXEC --> NODE_RESULT
    TOOL_EXEC --> NODE_RESULT
    AGG_EXEC --> NODE_RESULT
    CODE_EXEC --> NODE_RESULT

    NODE_RESULT --> CHECKPOINT_SAVE
    CHECKPOINT_SAVE --> LOG_EXECUTION

    %% ==================== SPECIAL NODE HANDLING ====================
    subgraph HumanInLoop["10. Human-in-Loop"]
        CREATE_PENDING[Create PendingTask]
        SEND_PROMPT[Send Prompt via Telegram]
        AWAIT_RESPONSE[Await User Response]
        
        USER_CONFIRM[/confirm]
        USER_CANCEL[/cancel]
        USER_TIMEOUT[Timeout]
        
        RESUME_EXEC[Resume Execution]
        CANCEL_EXEC[Cancel Execution]
    end

    HUMAN_EXEC --> CREATE_PENDING
    CREATE_PENDING --> SEND_PROMPT
    SEND_PROMPT --> AWAIT_RESPONSE
    AWAIT_RESPONSE --> |confirm| USER_CONFIRM --> RESUME_EXEC
    AWAIT_RESPONSE --> |cancel| USER_CANCEL --> CANCEL_EXEC
    AWAIT_RESPONSE --> |timeout| USER_TIMEOUT --> CANCEL_EXEC
    RESUME_EXEC --> NODE_RESULT

    subgraph ParallelExec["11. Parallel Execution"]
        SPAWN_BRANCHES[Spawn Concurrent Tasks]
        AWAIT_BRANCHES[Await Based on Strategy]
        COLLECT_RESULTS[Collect Branch Results]
    end

    PARALLEL_EXEC --> SPAWN_BRANCHES
    SPAWN_BRANCHES --> AWAIT_BRANCHES
    AWAIT_BRANCHES --> COLLECT_RESULTS
    COLLECT_RESULTS --> NODE_RESULT

    subgraph SubworkflowExec["12. Subworkflow Execution"]
        MAP_INPUT[Map Input from Parent State]
        CREATE_CHILD_EXEC[Create Child WorkflowExecution]
        INVOKE_SUBGRAPH[Invoke Subworkflow Graph]
        MAP_OUTPUT[Map Output to Parent State]
    end

    SUBWF_EXEC --> MAP_INPUT
    MAP_INPUT --> CREATE_CHILD_EXEC
    CREATE_CHILD_EXEC --> INVOKE_SUBGRAPH
    INVOKE_SUBGRAPH --> |recursive| CACHE_CHECK
    INVOKE_SUBGRAPH --> MAP_OUTPUT
    MAP_OUTPUT --> NODE_RESULT

    %% ==================== EDGE FOLLOWING ====================
    subgraph EdgeFollowing["13. Edge Following"]
        FOLLOW_EDGES{Follow Outgoing Edges}
        EVAL_CONDITION[Evaluate Condition / state.route]
        NEXT_NODE[Determine Next Node]
        END_NODE[Reached END]
    end

    LOG_EXECUTION --> FOLLOW_EDGES
    FOLLOW_EDGES --> |has edges| EVAL_CONDITION
    EVAL_CONDITION --> NEXT_NODE
    NEXT_NODE --> EXEC_NODE
    FOLLOW_EDGES --> |no edges / END| END_NODE

    %% ==================== COMPLETION ====================
    subgraph Completion["14. Completion"]
        EXTRACT_OUTPUT[Extract Final Output]
        UPDATE_EXECUTION[Update WorkflowExecution: completed]
        SAVE_CONVERSATION[Save to Conversation]
    end

    END_NODE --> EXTRACT_OUTPUT
    EXTRACT_OUTPUT --> UPDATE_EXECUTION
    UPDATE_EXECUTION --> SAVE_CONVERSATION

    %% ==================== OUTPUT DELIVERY ====================
    subgraph OutputDelivery["15. Output Delivery"]
        OUTPUT_ROUTER{Trigger Type?}
        TG_REPLY[Send Telegram Reply]
        WEBHOOK_RESP[Return Webhook Response]
        PARENT_RETURN[Return to Parent Workflow]
        LOG_ONLY[Log Only]
    end

    SAVE_CONVERSATION --> OUTPUT_ROUTER
    OUTPUT_ROUTER --> |telegram| TG_REPLY
    OUTPUT_ROUTER --> |webhook| WEBHOOK_RESP
    OUTPUT_ROUTER --> |workflow| PARENT_RETURN
    OUTPUT_ROUTER --> |schedule| LOG_ONLY

    PARENT_RETURN --> MAP_OUTPUT

    %% ==================== ERROR HANDLING ====================
    subgraph ErrorHandling["16. Error Handling"]
        ERROR_CAUGHT[Error Caught]
        SHOULD_RETRY{Retry?}
        RETRY_BACKOFF[Exponential Backoff]
        MARK_FAILED[Update Execution: failed]
        ERROR_NOTIFY[Notify User]
    end

    EXEC_NODE --> |error| ERROR_CAUGHT
    ERROR_CAUGHT --> SHOULD_RETRY
    SHOULD_RETRY --> |yes, retries left| RETRY_BACKOFF
    RETRY_BACKOFF --> EXEC_NODE
    SHOULD_RETRY --> |no| MARK_FAILED
    MARK_FAILED --> ERROR_NOTIFY
    CANCEL_EXEC --> MARK_FAILED
```

---

## Git Sync Flow

### Sync Flow Diagram

```mermaid
flowchart TD
    subgraph SyncTriggers["Sync Triggers"]
        WF_SAVE[Workflow Save in UI]
        CODE_SAVE[Code Block Save]
        SCHEDULED[Scheduled Auto-Sync]
        GIT_WEBHOOK[Git Provider Webhook]
        MANUAL_SYNC[Manual Sync Request]
    end

    subgraph SyncQueue["Django-RQ git-sync Queue"]
        CREATE_TASK[Create GitSyncTask]
        ENQUEUE_SYNC[Enqueue git_sync_job]
        SYNC_WORKER[Git Sync Worker]
    end

    WF_SAVE --> CREATE_TASK
    CODE_SAVE --> CREATE_TASK
    SCHEDULED --> CREATE_TASK
    GIT_WEBHOOK --> CREATE_TASK
    MANUAL_SYNC --> CREATE_TASK
    CREATE_TASK --> ENQUEUE_SYNC
    ENQUEUE_SYNC --> SYNC_WORKER

    subgraph SyncExecution["Sync Execution"]
        DIRECTION{Direction?}
        
        subgraph PullFlow["Pull Flow"]
            FETCH[Fetch from Remote]
            DETECT_CHANGES[Detect Changed Files]
            PULL[Pull Changes]
            IMPORT_WF[Import Workflow Definition]
            IMPORT_CODE[Import Code Blocks]
            INVALIDATE_CACHE[Invalidate Graph Cache]
        end
        
        subgraph PushFlow["Push Flow"]
            EXPORT_WF[Export Workflow Definition]
            EXPORT_CODE[Export Code Blocks]
            STAGE[Stage Changes]
            COMMIT[Commit with Message]
            PUSH[Push to Remote]
        end
        
        DIRECTION --> |pull| FETCH
        FETCH --> DETECT_CHANGES
        DETECT_CHANGES --> PULL
        PULL --> IMPORT_WF
        IMPORT_WF --> IMPORT_CODE
        IMPORT_CODE --> INVALIDATE_CACHE
        
        DIRECTION --> |push| EXPORT_WF
        EXPORT_WF --> EXPORT_CODE
        EXPORT_CODE --> STAGE
        STAGE --> COMMIT
        COMMIT --> PUSH
        
        DIRECTION --> |both| FETCH
        INVALIDATE_CACHE --> EXPORT_WF
    end

    SYNC_WORKER --> DIRECTION

    subgraph SyncCompletion["Sync Completion"]
        RECORD_COMMIT[Record GitCommit]
        UPDATE_REPO[Update Repository State]
        COMPLETE_TASK[Complete GitSyncTask]
    end

    PUSH --> RECORD_COMMIT
    INVALIDATE_CACHE --> RECORD_COMMIT
    RECORD_COMMIT --> UPDATE_REPO
    UPDATE_REPO --> COMPLETE_TASK

    subgraph ErrorHandling["Error Handling"]
        SYNC_ERROR[Sync Error]
        RETRY_CHECK{Retry?}
        BACKOFF[Exponential Backoff]
        FAIL_TASK[Mark Task Failed]
        NOTIFY_USER[Notify User]
    end

    FETCH --> |error| SYNC_ERROR
    PUSH --> |error| SYNC_ERROR
    SYNC_ERROR --> RETRY_CHECK
    RETRY_CHECK --> |yes| BACKOFF --> ENQUEUE_SYNC
    RETRY_CHECK --> |no| FAIL_TASK --> NOTIFY_USER
```

---

## Code Block Version Control Flow

```mermaid
flowchart TD
    subgraph Development["Development"]
        EDIT[Edit Code in UI]
        SAVE_DRAFT[Save as Draft]
        NEW_VERSION[Create CodeBlockVersion<br/>status: draft]
    end

    EDIT --> SAVE_DRAFT
    SAVE_DRAFT --> NEW_VERSION

    subgraph Testing["Testing"]
        RUN_TESTS[Run CodeBlockTests]
        TEST_RESULTS{All Pass?}
        UPDATE_STATUS[Update status: testing]
        FIX_CODE[Fix Code]
    end

    NEW_VERSION --> RUN_TESTS
    RUN_TESTS --> TEST_RESULTS
    TEST_RESULTS --> |yes| UPDATE_STATUS
    TEST_RESULTS --> |no| FIX_CODE
    FIX_CODE --> SAVE_DRAFT

    subgraph Publishing["Publishing"]
        REVIEW[Review Changes]
        APPROVE{Approved?}
        PUBLISH[Publish Version]
        DEPRECATE_OLD[Deprecate Old Version]
        SET_PUBLISHED[Set as published_version]
    end

    UPDATE_STATUS --> REVIEW
    REVIEW --> APPROVE
    APPROVE --> |yes| PUBLISH
    APPROVE --> |no| FIX_CODE
    PUBLISH --> DEPRECATE_OLD
    DEPRECATE_OLD --> SET_PUBLISHED

    subgraph GitSync["Git Sync"]
        EXPORT_FILE[Export to code/slug.py]
        COMMIT_PUSH[Commit & Push]
    end

    SET_PUBLISHED --> EXPORT_FILE
    EXPORT_FILE --> COMMIT_PUSH

    subgraph Rollback["Rollback (if needed)"]
        DETECT_ISSUE[Detect Issue in Production]
        SELECT_VERSION[Select Previous Version]
        RESTORE[Restore as Published]
    end

    DETECT_ISSUE --> SELECT_VERSION
    SELECT_VERSION --> RESTORE
    RESTORE --> DEPRECATE_OLD
```

---

## Repository Structure

Each workflow has its own Git repository with this structure:

```
workflow-{slug}/
├── workflow.yaml                    # Workflow definition
│   ├── name, description
│   ├── triggers[]
│   ├── nodes[]
│   └── edges[]
├── code/
│   ├── {code_block_slug}.py        # Code block source
│   ├── {code_block_slug}.py
│   └── tests/
│       ├── test_{slug}.py          # Test cases
│       └── test_{slug}.py
├── .github/
│   └── workflows/
│       ├── test.yaml               # CI: Run tests on PR
│       └── sync.yaml               # CD: Sync on merge
├── requirements.txt                 # Python dependencies
├── CHANGELOG.md
├── README.md
└── LICENSE
```

### Workflow Definition Schema (workflow.yaml)

```yaml
name: "Research Assistant"
slug: "research-assistant"
description: "AI-powered research assistant"
is_callable: false
is_public: false
is_template: true

# Credential references — resolved by name from the owner's credentials in DB.
# These are not secrets; they are lookup keys into the credentials app.
credentials:
  telegram: "my-telegram-bot"            # name of a TelegramCredential
  llm: "openai-production"               # name of an LLMProviderCredentials
  llm_model: "gpt-4o"                    # name of an LLMModel (under the llm credential's provider)

input_schema:  # For callable workflows
  type: object
  properties:
    query:
      type: string
  required: [query]

output_schema:
  type: object
  properties:
    result:
      type: string

triggers:
  - type: telegram_chat
    config:
      pattern: null
      session_timeout_minutes: 30
    is_active: true
    priority: 1

nodes:
  - node_id: categorizer
    component_type: categorizer
    is_entry_point: true
    config:
      categories:
        - name: research
          description: "User wants to research a topic"
          examples: ["research quantum computing", "find info about"]
        - name: general
          description: "General conversation"
      confidence_threshold: 0.7
      fallback_category: general

  - node_id: research_agent
    component_type: react_agent
    config:
      system_prompt: "You are a research assistant..."
      tools: [web_search, research]
      # Optional per-node credential override (defaults to workflow-level):
      # llm: "anthropic-production"
      # llm_model: "claude-sonnet-4-20250514"

  - node_id: chat
    component_type: chat_model
    config:
      system_prompt: "You are a helpful assistant..."

edges:
  - source_node_id: categorizer
    condition_mapping:
      research: research_agent
      general: chat
```

---

## Storage Summary

| Entity | Store | TTL | Notes |
|--------|-------|-----|-------|
| User, Workflow, Nodes, Edges | PostgreSQL | Permanent | Core configuration (Workflow uses soft-delete) |
| Credentials | PostgreSQL | Permanent | Encrypted sensitive fields |
| CodeBlock, Versions | PostgreSQL | Permanent | Source of truth; Git is sync target |
| GitRepository, Commits | PostgreSQL | Permanent | Audit trail |
| WorkflowExecution, Logs | PostgreSQL | Permanent | Execution history |
| PendingTasks | PostgreSQL | App-enforced | `expires_at` checked on lookup; periodic cleanup job |
| LangGraph Checkpoints | PostgreSQL | Permanent | Via PostgresSaver |
| Compiled Graphs | In-memory (per worker) | 1 hour | Not serializable; Redis pub/sub for cross-worker invalidation |
| Active Chat Sessions | Redis | 30 minutes | Session tracking |
| Django-RQ Jobs | Redis | Per queue | Job queue |

---

## Queue Configuration

| Queue | Purpose | Timeout | Workers |
|-------|---------|---------|---------|
| `default` | General tasks | 5m | 2 |
| `workflows` | Workflow execution | 10m | 4 |
| `browser` | Browser agent tasks (single worker for Playwright) | 10m | 1 |
| `git-sync` | Git operations | 5m | 1 |
| `scheduled` | Cron triggers | 10m | 2 |

> **Migration note:** The current codebase uses queues `high`, `default`, `low`,
> `browser`. In the new design, `high` is removed (categorization is now part of
> the workflow graph), `low` is removed (compression handled internally),
> `browser` is retained, and `workflows`, `git-sync`, `scheduled` are added.

---

## Key Implementation Classes

### WorkflowBuilder

Compiles Django models into LangGraph `CompiledGraph`:

```python
class WorkflowBuilder:
    """Builds LangGraph StateGraph from Django Workflow model"""
    
    def __init__(self, workflow: Workflow):
        self.workflow = workflow
        self.tool_factory = ToolFactory(workflow)
        self.tools = self.tool_factory.get_tools()
    
    def build(self) -> CompiledGraph:
        builder = StateGraph(WorkflowState)
        
        # Add all nodes
        for node in self.workflow.nodes.select_related('component_config').all():
            runnable = self._create_node_runnable(node)
            builder.add_node(node.node_id, runnable)
        
        # Add edges
        for edge in self.workflow.edges.all():
            if edge.edge_type == "conditional":
                builder.add_conditional_edges(
                    edge.source_node_id,
                    self._build_router_function(edge),
                    edge.condition_mapping
                )
            else:
                builder.add_edge(edge.source_node_id, edge.target_node_id)
        
        # Set entry point
        entry = self.workflow.nodes.get(is_entry_point=True)
        builder.set_entry_point(entry.node_id)
        
        # Collect interrupt points
        interrupt_before = [
            n.node_id for n in self.workflow.nodes.filter(interrupt_before=True)
        ]
        interrupt_after = [
            n.node_id for n in self.workflow.nodes.filter(interrupt_after=True)
        ]
        
        return builder.compile(
            checkpointer=get_checkpointer(),
            interrupt_before=interrupt_before or None,
            interrupt_after=interrupt_after or None,
        )
```

### GraphCache

Caches compiled graphs in process memory. CompiledGraph objects contain runtime
callables and LLM clients that cannot be serialized to Redis, so we use an
in-memory dict with TTL-based expiry. Redis is used only for cross-worker
invalidation signals (pub/sub or key deletion).

```python
import time
import threading

class GraphCache:
    """In-memory cache for compiled LangGraph instances.

    CompiledGraph objects are not serializable (they contain closures,
    LLM clients, tool references), so they must be cached in-process.
    Redis pub/sub is used to broadcast invalidation across workers.
    """

    TTL = 60 * 60  # 1 hour

    _cache: dict[str, tuple[CompiledGraph, float]] = {}
    _lock = threading.Lock()

    @classmethod
    def _cache_key(cls, workflow: Workflow) -> str:
        config_hash = cls._compute_config_hash(workflow)
        return f"{workflow.id}:{config_hash}"

    @classmethod
    def get_or_build(cls, workflow: Workflow) -> CompiledGraph:
        key = cls._cache_key(workflow)

        with cls._lock:
            if key in cls._cache:
                graph, cached_at = cls._cache[key]
                if time.time() - cached_at < cls.TTL:
                    return graph
                del cls._cache[key]

        graph = WorkflowBuilder(workflow).build()

        with cls._lock:
            cls._cache[key] = (graph, time.time())

        return graph

    @classmethod
    def invalidate(cls, workflow: Workflow) -> None:
        """Invalidate local cache and broadcast to other workers via Redis."""
        prefix = f"{workflow.id}:"
        with cls._lock:
            keys_to_delete = [k for k in cls._cache if k.startswith(prefix)]
            for k in keys_to_delete:
                del cls._cache[k]

        # Broadcast invalidation to other RQ workers
        redis_client.publish("graph_invalidation", str(workflow.id))
```

### TriggerResolver

Resolves incoming events to workflows:

```python
class TriggerResolver:
    """Resolves incoming events to workflows"""
    
    def resolve_telegram_message(
        self,
        message: str,
        chat_id: int,
        chat_type: str,
        user_profile_id: int,
    ) -> tuple[Workflow, WorkflowTrigger, bool] | None:
        """
        Find matching workflow for telegram message.
        Returns (workflow, trigger, is_chat_continuation)
        """
        
        # First check for active chat sessions
        active_session = self._get_active_chat_session(chat_id, user_profile_id)
        if active_session:
            return (
                active_session.workflow,
                active_session.trigger,
                True
            )
        
        # Find matching triggers by pattern/command
        # ...
        
        # Fallback to default workflow
        # ...
```

### WorkflowExecutor

Executes workflows via Django-RQ:

```python
@django_rq.job('workflows', timeout=600)
def execute_workflow_job(
    workflow_id: int,
    thread_id: str,
    trigger_payload: dict,
    resume: bool = False,
):
    """Execute workflow in RQ worker"""
    
    workflow = Workflow.objects.get(id=workflow_id)
    execution = WorkflowExecution.objects.get(thread_id=thread_id)
    
    # Get or build graph
    graph = GraphCache.get_or_build(workflow)
    
    config = {"configurable": {"thread_id": thread_id}}
    
    try:
        if resume:
            result = graph.invoke(None, config)
        else:
            initial_state = build_initial_state(trigger_payload)
            result = graph.invoke(initial_state, config)
        
        # Check if interrupted
        state = graph.get_state(config)
        
        if state.next:
            # Workflow is interrupted, waiting for human
            execution.status = "interrupted"
            create_pending_task(execution, state)
        else:
            # Workflow completed
            execution.status = "completed"
            execution.final_output = result
            deliver_output(execution, result)
    
    except Exception as e:
        execution.status = "failed"
        notify_error(execution, e)
    
    finally:
        execution.save()
```

---

## Example Workflows

### 1. Default Conversational Assistant

```yaml
name: "Default Assistant"
is_default: true

credentials:
  telegram: "my-telegram-bot"
  llm: "openai-production"
  llm_model: "gpt-4o"

triggers:
  - type: telegram_chat
    config:
      session_timeout_minutes: 30

nodes:
  - node_id: categorizer
    component_type: categorizer
    is_entry_point: true
    config:
      categories:
        - name: research
          description: "Research tasks"
        - name: browser
          description: "Web automation"
        - name: planning
          description: "Complex multi-step tasks"
        - name: sensitive
          description: "Actions needing confirmation"
        - name: general
          description: "General conversation"
      fallback_category: general

  - node_id: research_agent
    component_type: react_agent
    config:
      tools: [web_search, research]

  - node_id: browser_agent
    component_type: react_agent
    config:
      tools: [browser, web_search]

  - node_id: planner
    component_type: plan_and_execute
    config:
      max_replans: 3
      tools: [web_search, browser, research]

  - node_id: confirmation
    component_type: human_confirmation
    config:
      prompt_template: "This action requires confirmation: {action}"
      timeout_seconds: 300

  - node_id: sensitive_agent
    component_type: react_agent
    config:
      tools: [browser]

  - node_id: chat
    component_type: chat_model

edges:
  - source_node_id: categorizer
    condition_mapping:
      research: research_agent
      browser: browser_agent
      planning: planner
      sensitive: confirmation
      general: chat

  - source_node_id: confirmation
    target_node_id: sensitive_agent
```

### 2. Scheduled Daily Report

```yaml
name: "Daily Market Report"

credentials:
  telegram: "my-telegram-bot"
  llm: "openai-production"
  llm_model: "gpt-4o"

triggers:
  - type: schedule
    config:
      cron_expression: "0 9 * * 1-5"
      timezone: "Australia/Adelaide"

nodes:
  - node_id: fetch_data
    component_type: react_agent
    is_entry_point: true
    config:
      tools: [web_search, market_data_api]
      system_prompt: "Fetch latest market data..."

  - node_id: generate_report
    component_type: chat_model
    config:
      system_prompt: "Generate a concise market report..."

  - node_id: send_notification
    component_type: tool_node
    config:
      tools: [telegram_send]

edges:
  - source_node_id: fetch_data
    target_node_id: generate_report

  - source_node_id: generate_report
    target_node_id: send_notification
```

### 3. Reusable Summarizer (Callable)

```yaml
name: "Summarizer"
is_callable: true

credentials:
  llm: "openai-production"
  llm_model: "gpt-4o"

input_schema:
  type: object
  properties:
    content:
      type: string
    max_length:
      type: integer
      default: 200
  required: [content]

output_schema:
  type: object
  properties:
    summary:
      type: string
    key_points:
      type: array

nodes:
  - node_id: summarize
    component_type: chat_model
    is_entry_point: true
    config:
      system_prompt: |
        Summarize the content in {max_length} words or less.
        Extract 3-5 key points.
        Respond in JSON: {"summary": "...", "key_points": [...]}
```

---

## Project Structure

```
project/
├── config/
│   ├── settings/
│   │   ├── base.py
│   │   ├── development.py
│   │   └── production.py
│   ├── urls.py
│   └── wsgi.py
├── apps/
│   ├── users/
│   │   ├── models.py          # UserProfile
│   │   ├── serializers.py
│   │   └── views.py
│   ├── credentials/
│   │   ├── models.py          # BaseCredentials, GitCredential, etc.
│   │   ├── serializers.py
│   │   └── views.py
│   ├── workflows/
│   │   ├── models/
│   │   │   ├── workflow.py    # Workflow, WorkflowCollaborator
│   │   │   ├── trigger.py     # WorkflowTrigger
│   │   │   ├── node.py        # WorkflowNode, WorkflowEdge
│   │   │   ├── tool.py        # ToolDefinition, WorkflowTool
│   │   │   ├── code.py        # CodeBlock, CodeBlockVersion
│   │   │   ├── git.py         # GitRepository, GitCommit, GitSyncTask
│   │   │   └── execution.py   # WorkflowExecution, ExecutionLog, PendingTask
│   │   ├── components/
│   │   │   ├── base.py        # BaseWorkflowComponent
│   │   │   ├── categorizer.py
│   │   │   ├── router.py
│   │   │   ├── chat.py
│   │   │   ├── react_agent.py
│   │   │   ├── plan_and_execute.py
│   │   │   ├── tool_node.py
│   │   │   ├── aggregator.py
│   │   │   ├── human_confirmation.py
│   │   │   ├── parallel.py
│   │   │   ├── subworkflow.py
│   │   │   └── code.py
│   │   ├── triggers/
│   │   │   ├── types.py       # TriggerType, TriggerConfigs
│   │   │   ├── handlers.py    # TelegramHandler, ScheduleHandler, etc.
│   │   │   ├── resolver.py    # TriggerResolver
│   │   │   └── payload.py     # TriggerPayload
│   │   ├── builder.py         # WorkflowBuilder
│   │   ├── executor.py        # WorkflowExecutor
│   │   ├── cache.py           # GraphCache
│   │   ├── state.py           # WorkflowState
│   │   ├── serializers.py
│   │   ├── views.py
│   │   └── urls.py
│   ├── tools/
│   │   ├── registry.py        # TOOL_REGISTRY
│   │   ├── factory.py         # ToolFactory
│   │   ├── web_search.py
│   │   ├── browser.py
│   │   └── research.py
│   ├── versioning/
│   │   ├── git_sync.py        # WorkflowGitSync
│   │   └── code_executor.py   # CodeExecutor (RestrictedPython)
│   ├── telegram/
│   │   ├── bot.py             # Telegram bot setup
│   │   ├── handlers.py        # Message handlers
│   │   └── callbacks.py       # Callback query handlers
│   └── conversations/
│       ├── models.py          # Conversation
│       └── views.py
├── tasks/
│   ├── workflows.py           # execute_workflow_job
│   ├── git_sync.py            # git_sync_job
│   └── scheduled.py           # Scheduled trigger jobs
├── manage.py
├── requirements.txt
└── docker-compose.yml
```

---

## Environment Variables

```bash
# Infrastructure only — everything else lives in the database (Credentials app).

# Database
DATABASE_URL=postgresql://user:pass@localhost:5432/workflows

# Redis
REDIS_URL=redis://localhost:6379/0

# Django
SECRET_KEY=your-secret-key
DEBUG=false
ALLOWED_HOSTS=localhost,yourdomain.com

# Git Repos Storage
REPOS_BASE_PATH=/data/repos

# Encryption (for credential fields in DB)
FIELD_ENCRYPTION_KEY=your-encryption-key
```

> **Note:** Telegram bot tokens, LLM API keys, and other service credentials
> are stored in the `credentials` app (`TelegramCredential`,
> `LLMProviderCredentials`, `ToolCredential`). They are **not** environment
> variables — this allows multiple bots, multiple LLM providers, and
> per-workflow credential selection via the database and workflow YAML.

---

## Next Steps

1. **Generate Django Models** - Create all model files based on this design
2. **Implement Components** - Build each component type
3. **Build Trigger Handlers** - Implement Telegram, Schedule, Webhook handlers
4. **Create Git Sync** - Implement repository sync logic
5. **Build API** - REST API for workflow management
6. **Create UI** - Workflow editor (optional, can use n8n-style)
7. **Testing** - Unit and integration tests
8. **Deployment** - Docker setup, CI/CD

---

## References

- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [LangChain Documentation](https://python.langchain.com/)
- [Django-RQ](https://github.com/rq/django-rq)
- [n8n Workflow Concepts](https://docs.n8n.io/)

# Domain Model

## Core Entities

```mermaid
erDiagram
    DjangoUser ||--|| UserProfile : "one-to-one"
    UserProfile ||--o| Conversation : has
    UserProfile ||--o{ Plan : owns
    UserProfile ||--o{ PendingTask : awaits
    UserProfile ||--o{ Workflow : defines
    Plan ||--|{ Step : contains
    PendingTask }o--o| Plan : references
    Conversation ||--|{ Message : "stores (JSON)"

    BaseCredentials ||--|| TelegramCredential : extends
    BaseCredentials ||--|| LLMProviderCredentials : extends
    LLMProviderCredentials }o--|| BaseLLMProvider : "uses"
    BaseLLMProvider ||--o{ LLMModel : offers

    Workflow ||--|{ WorkflowNode : contains
    WorkflowNode }o--o{ WorkflowEdge : "connected via"
    BaseWorkflowComponent ||--|| LLMAgent : extends
    BaseWorkflowComponent ||--|| Chat : extends
    BaseWorkflowComponent ||--|| IfBlock : extends
    BaseWorkflowComponent ||--|| Aggregator : extends
    WorkflowNode }o--|| BaseWorkflowComponent : "instance of"

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
        int django_user_id FK "OneToOne"
        int telegram_user_id UK "Telegram user ID"
    }

    Conversation {
        int id PK
        int user_profile_id FK
        text messages "JSON array of Message"
        int token_count
        datetime created_at
        datetime updated_at
    }

    Message {
        string role "user | assistant | system"
        string content
    }

    Plan {
        string plan_id PK
        int user_profile_id FK
        string goal
        int current_step
        string status "active | completed | cancelled"
        list checkpoints "step orders needing confirmation"
    }

    Step {
        int order PK
        string agent "system | browser | search | research"
        string action
        string status "pending | running | completed | failed | skipped"
        string result
        string error
        list depends_on "step orders"
    }

    PendingTask {
        string task_id PK "8-char UUID"
        int user_profile_id FK
        int chat_id
        string message
        string target "agent name or planner"
        string strategy "macro | agent | dynamic | plan_step"
        string plan_id FK "optional"
        string created_at
        string expires_at
    }
```

## Credentials & Providers

```mermaid
erDiagram
    BaseCredentials ||--|| TelegramCredential : extends
    BaseCredentials ||--|| LLMProviderCredentials : extends
    LLMProviderCredentials }o--|| BaseLLMProvider : uses
    BaseLLMProvider ||--o{ LLMModel : offers

    BaseCredentials {
        int id PK
        string name
        string credential_type "discriminator"
        datetime created_at
        datetime updated_at
    }

    TelegramCredential {
        int id PK
        int base_credentials_id FK
        string bot_token
        string allowed_user_ids "comma-separated"
    }

    LLMProviderCredentials {
        int id PK
        int base_credentials_id FK
        int provider_id FK
        string api_key
        string base_url "for openai_compatible"
    }

    BaseLLMProvider {
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
```

## System Configuration

```mermaid
erDiagram
    SystemConf {
        int id PK
        string redis_host
        int redis_port
        int redis_db
        string searxng_base_url
        string session_storage_name "db path or connection string"
    }
```

## Workflow Components

```mermaid
classDiagram
    class BaseWorkflowComponent {
        +int id
        +string name
        +string component_type
        +json config
        +execute(input) output
    }

    class LLMAgent {
        +int llm_model_id
        +float temperature
        +list~Tool~ tools
        +string system_prompt
    }

    class Chat {
        +int llm_model_id
        +float temperature
        +string system_prompt
    }

    class IfBlock {
        +string condition_expression
        +string true_branch
        +string false_branch
    }

    class Aggregator {
        +string aggregation_strategy "concat | summarize | pick_best"
    }

    BaseWorkflowComponent <|-- LLMAgent
    BaseWorkflowComponent <|-- Chat
    BaseWorkflowComponent <|-- IfBlock
    BaseWorkflowComponent <|-- Aggregator
```

## Workflow Definition (n8n-style)

```mermaid
erDiagram
    UserProfile ||--o{ Workflow : defines
    Workflow ||--|{ WorkflowNode : contains
    WorkflowNode }o--o{ WorkflowEdge : "connected via"
    WorkflowNode }o--|| BaseWorkflowComponent : "instance of"

    Workflow {
        int id PK
        int user_profile_id FK
        string name
        bool is_active
        string trigger_type "message | command | schedule"
        datetime created_at
        datetime updated_at
    }

    WorkflowNode {
        int id PK
        int workflow_id FK
        int component_id FK "BaseWorkflowComponent"
        json config_overrides "per-node param overrides"
        int position_x
        int position_y
    }

    WorkflowEdge {
        int id PK
        int workflow_id FK
        int source_node_id FK
        int target_node_id FK
        string condition "optional, for IfBlock branches"
        int sort_order
    }
```

## Message Flow

```mermaid
flowchart TD
    MSG[User Message] --> CR[ChatRequest]
    CR --> WF{Workflow defined?}

    WF -->|yes| ENGINE[Workflow Engine]
    WF -->|no| CAT{Gateway enabled?}

    ENGINE --> RESOLVE[Resolve trigger node]
    RESOLVE --> WALK[Walk edges, execute nodes]
    WALK --> |LLMAgent| AGENT_EXEC[Agent execution]
    WALK --> |Chat| CHAT_EXEC[LLM chat]
    WALK --> |IfBlock| BRANCH[Evaluate condition]
    WALK --> |Aggregator| AGG[Aggregate results]
    BRANCH --> WALK
    AGG --> WALK

    CAT -->|yes| LLM[Categorizer LLM]
    CAT -->|no| DIRECT[Direct chat]

    LLM --> RR[RouteResult]
    RR --> CONF{requires_confirmation?}

    CONF -->|yes| PT[PendingTask in Redis]
    PT --> APPROVE{User confirms?}
    APPROVE -->|/confirm| EXEC
    APPROVE -->|/cancel| DONE[Cancelled]

    CONF -->|no| EXEC[Executor]

    RR -.-> STRAT

    subgraph STRAT[Execution Strategy]
        AGENT[AGENT]
        CHAT[CHAT]
        DYNAMIC[DYNAMIC_PLAN]
    end

    EXEC --> RQ[RQ Queue]
    RQ --> WORKER[RQ Worker]

    WORKER --> AGENT
    WORKER --> CHAT
    WORKER --> DYNAMIC

    DYNAMIC --> PLAN[Plan with Steps]
    PLAN --> STEP[Execute steps sequentially]
    STEP --> AGENT

    AGENT --> SAVE[Save to Conversation]
    CHAT --> SAVE
    AGENT_EXEC --> SAVE
    CHAT_EXEC --> SAVE
    SAVE --> REPLY[Reply to user via Telegram]
    DIRECT --> SAVE
```

## Storage

| Entity | Store | TTL |
|--------|-------|-----|
| DjangoUser | PostgreSQL / SQLite | permanent |
| UserProfile | PostgreSQL / SQLite | permanent |
| Conversation | per SystemConf.session_storage_name | permanent |
| Credentials | PostgreSQL / SQLite | permanent |
| Workflow, Nodes, Edges | PostgreSQL / SQLite | permanent |
| Plan | Redis | 1 hour |
| PendingTask | Redis | 5 minutes (configurable) |
| RQ Jobs | Redis | per queue defaults |

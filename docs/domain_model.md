# Domain Model

```mermaid
erDiagram
    User ||--o| Conversation : has
    User ||--o{ Plan : owns
    User ||--o{ PendingTask : awaits
    Plan ||--|{ Step : contains
    PendingTask }o--o| Plan : "references"
    Conversation ||--|{ Message : "stores (JSON)"

    User {
        int user_id PK "Telegram user ID"
    }

    Conversation {
        int user_id PK
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
        int user_id FK
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
        int user_id FK
        int chat_id
        string message
        string target "agent name or planner"
        string strategy "macro | agent | dynamic | plan_step"
        string plan_id FK "optional"
        string created_at
        string expires_at
    }
```

## Message Flow

```mermaid
flowchart TD
    MSG[User Message] --> CR[ChatRequest]
    CR --> CAT{Gateway enabled?}

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
        AGENT[AGENT → agent_task]
        CHAT[CHAT → chat_task]
        DYNAMIC[DYNAMIC_PLAN → Planner]
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
    SAVE --> REPLY[Reply to user via Telegram]
    DIRECT --> SAVE
```

## Storage

| Entity | Store | TTL |
|--------|-------|-----|
| Conversation | SQLite | permanent |
| Plan | Redis | 1 hour |
| PendingTask | Redis | 5 minutes (configurable) |
| RQ Jobs | Redis | per queue defaults |

## Agents

```mermaid
classDiagram
    class AgentWrapper {
        +graph: LangGraph agent
        +invoke(inputs) dict
    }

    class SystemAgent {
        tools: shell_execute, file_read, file_write, disk_usage
        temperature: 0
    }

    class BrowserAgent {
        tools: navigate, screenshot, click, type, get_page_text
        temperature: 0
    }

    class SearchAgent {
        tools: web_search, web_search_news, web_search_images
        temperature: 0.3
    }

    class ResearchAgent {
        tools: analyze_text, compare_items
        temperature: 0.3
    }

    AgentWrapper <|-- SystemAgent
    AgentWrapper <|-- BrowserAgent
    AgentWrapper <|-- SearchAgent
    AgentWrapper <|-- ResearchAgent
```

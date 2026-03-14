# Triggers

<span class="badge badge--trigger">Trigger</span>

Triggers are the entry points of every workflow. They receive events from external sources -- a chat message, a scheduled interval, a webhook payload, or an error condition -- and initiate workflow execution.

## Triggers Are Nodes

In Pipelit, triggers are **not** separate entities. They are first-class nodes on the canvas, sharing the same unified node model as agents, tools, and logic components. This means:

- Triggers appear on the canvas with the same drag-and-drop behavior as other nodes.
- They have defined output ports that emit typed data downstream.
- They connect to other nodes via standard edges.
- Multiple triggers can exist on the same canvas, each firing independently.

On the canvas, all trigger nodes display with an **orange border** (`#f97316`) and strip the `trigger_` prefix in their label (e.g., `trigger_chat` displays as `chat`).

## Trigger Types

| Component Type | Display Name | Description |
|----------------|-------------|-------------|
| [`trigger_chat`](chat.md) | Chat Trigger | Receives messages from chat clients via the message gateway |
| [`trigger_telegram`](../triggers/chat.md) | Telegram Trigger | Receives messages from Telegram via the message gateway |
| [`trigger_manual`](manual.md) | Manual Trigger | One-click execution from the UI |
| [`trigger_schedule`](schedule.md) | Schedule Trigger | Fired by the scheduler system on intervals |
| [`trigger_workflow`](workflow.md) | Workflow Trigger | Triggered by a parent workflow |
| [`trigger_error`](error.md) | Error Trigger | Triggered when errors occur in the workflow |
| [`trigger_webhook`](webhook.md) | Webhook Trigger | Receives external HTTP POST payloads |

!!! info "Gateway-mediated messaging"
    Chat and Telegram triggers receive messages via the [plit message gateway](https://github.com/theuselessai/plit). The gateway handles external channel integration (Telegram bots, chat clients) and forwards messages to Pipelit's inbound endpoint.

## Trigger-Scoped Execution

When a trigger fires, the execution engine does **not** compile the entire workflow graph. Instead, it performs a BFS (breadth-first search) from the fired trigger node and only compiles nodes that are **reachable downstream** from that trigger via direct edges.

This design has two important consequences:

1. **Multiple trigger branches**: A single workflow can have a Chat Trigger feeding one agent and a Schedule Trigger feeding a different agent. Each trigger fires independently and only executes its own branch.

2. **Unused nodes are ignored**: Nodes on the canvas that are not connected to the firing trigger are skipped entirely. This allows you to keep draft or experimental nodes on the canvas without causing build errors.

```mermaid
graph LR
    TC[Chat Trigger] --> A1[Agent A]
    TS[Schedule Trigger] --> A2[Agent B]
    TM[Manual Trigger] --> A1

    style TC fill:#f97316,color:white
    style TS fill:#f97316,color:white
    style TM fill:#f97316,color:white
```

In this example, firing the Chat Trigger executes only Agent A. Firing the Schedule Trigger executes only Agent B. The Manual Trigger also routes to Agent A, providing a second entry point to the same branch.

## Trigger Resolution

When an event arrives via the gateway inbound endpoint, the route specifies the target workflow and trigger node directly:

| Event Source | Component Type |
|------------|---------------|
| Gateway inbound (chat) | `trigger_chat` |
| Gateway inbound (Telegram) | `trigger_telegram` |
| Scheduler | `trigger_schedule` |
| Manual execution | `trigger_manual` |
| Parent workflow | `trigger_workflow` |
| Execution error | `trigger_error` |

## Trigger Payload

Every trigger receives an event payload that becomes available to downstream nodes via the `trigger` Jinja2 shorthand:

```
{{ trigger.text }}       {# message text #}
{{ trigger.payload }}    {# full event payload object #}
```

The exact fields available depend on the trigger type. See each trigger's documentation for its specific output ports.

## Non-Executable Status

Triggers themselves do not "execute" in the traditional sense -- they initiate execution. On the canvas, trigger nodes do not show running/success/failed status badges during execution. Their role is to receive events and pass data downstream to the first executable node in the chain.

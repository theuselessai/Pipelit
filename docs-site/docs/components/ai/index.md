# AI Components

AI components are the LLM-powered nodes in Pipelit. They send messages to a language model, interpret the response, and produce structured outputs that drive the rest of your workflow.

## Overview

There are five AI component types:

| Component | Purpose | Key Output |
|-----------|---------|------------|
| [Agent](agent.md) | Autonomous reasoning with tool calling | `output` (final text), `messages` (full conversation) |
| [Deep Agent](deep-agent.md) | Advanced agent with built-in task planning, filesystem tools, and subagent delegation | `output` (final text), `messages` (full conversation) |
| [Categorizer](categorizer.md) | Classify input into predefined categories | `category` (matched label), `raw` (LLM response) |
| [Router](router.md) | Route execution to different branches based on input content | `route` (branch identifier) |
| [Extractor](extractor.md) | Extract structured data from unstructured text | `extracted` (JSON object) |

All five share a common trait: they require an **AI Model** sub-component connection to function. Without a model, the node cannot resolve which LLM to use and will fail at build time.

## Canvas Appearance

AI nodes have a distinctive visual treatment on the workflow canvas:

- **Fixed 250px width** with a separator line dividing the node header from the sub-component pills below.
- **Bottom diamond handles** for connecting sub-components (model, tools, memory, output parser).
- **Left circle handle** for the input connection (messages).
- **Right circle handle** for the output connection.

## Sub-Component Support

Each AI node type supports a different set of sub-components. Connect these via the colored diamond handles at the bottom of the node.

| Node | Model | Tools | Memory | Output Parser |
|------|:-----:|:-----:|:------:|:-------------:|
| **Agent** | :material-check: | :material-check: | :material-check: | :material-close: |
| **Deep Agent** | :material-check: | :material-check: | :material-close: | :material-close: |
| **Categorizer** | :material-check: | :material-close: | :material-check: | :material-check: |
| **Router** | :material-check: | :material-close: | :material-check: | :material-check: |
| **Extractor** | :material-check: | :material-close: | :material-check: | :material-check: |

**Handle colors:**

| Sub-Component | Handle Color | Edge Label |
|---------------|-------------|------------|
| Model | Blue (`#3b82f6`) | `llm` |
| Tools | Green (`#10b981`) | `tool` |
| Memory | Amber (`#f59e0b`) | `memory` |
| Output Parser | Slate (`#94a3b8`) | `output_parser` |

!!! note "Agent and Deep Agent support tool connections"
    Only Agent and Deep Agent nodes support connecting tool sub-components. Categorizer, Router, and Extractor rely solely on the LLM's text generation without tool calling.

## Common Input

All five AI nodes accept the same input:

| Port | Type | Required |
|------|------|----------|
| `messages` | `MESSAGES` | Yes |

The `messages` input typically comes from a trigger node (Chat, Telegram, etc.) or from an upstream node that produces LangChain messages. The messages list carries the full conversation context that the LLM uses to generate its response.

## System Prompt and Jinja2

All AI nodes support a **system prompt** that instructs the LLM on its behavior. System prompts support Jinja2 template expressions, resolved by the orchestrator before execution:

```
You are a {{ trigger.payload.role }} assistant.
The user said: {{ trigger.text }}
Previous output: {{ code_abc123.output }}
```

See [Expressions](../../concepts/expressions.md) for the full template syntax.

## What's Next?

- [Agent](agent.md) -- autonomous reasoning with tool calling
- [Deep Agent](deep-agent.md) -- advanced agent with built-in task planning, filesystem tools, and subagents
- [Categorizer](categorizer.md) -- classify input into categories
- [Router](router.md) -- route execution based on input content
- [Extractor](extractor.md) -- extract structured data from text

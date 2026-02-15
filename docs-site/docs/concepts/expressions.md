# Expressions

Pipelit uses **Jinja2 template expressions** to pass data between nodes. Expressions let you reference the output of any upstream node or the trigger payload inside system prompts, code snippets, and extra config fields -- without writing code.

## Syntax

The basic syntax is:

```
{{ nodeId.portName }}
```

Where:

- **nodeId** is the unique identifier of an upstream node (e.g., `categorizer_abc123`).
- **portName** is the name of an output port on that node (e.g., `category`, `output`, `text`).

### Examples

```jinja2
{# Reference an upstream categorizer's output #}
The category is: {{ categorizer_abc123.category }}

{# Reference the trigger text #}
User said: {{ trigger.text }}

{# Use a Jinja2 filter #}
CATEGORY: {{ categorizer_abc123.category | upper }}

{# Combine multiple sources #}
Based on the {{ categorizer_abc123.category }} classification,
here is the extracted data: {{ extractor_def456.extracted }}
```

## Where Expressions Are Available

Expressions are resolved in three node configuration fields:

| Field | Description | Typical Use |
|-------|-------------|-------------|
| **System Prompt** | Agent, categorizer, router, extractor instructions | Injecting trigger data or upstream results into the LLM prompt |
| **Code Snippet** | Code node Python/Bash source | Templating dynamic values into code |
| **Extra Config** | Key-value pairs in `extra_config` | Dynamic URLs, parameters, or settings based on upstream output |

!!! note "Resolution Timing"
    Expressions are resolved **just before** a node executes, not at workflow build time. This means the values reflect the actual runtime output from upstream nodes in the current execution.

## Context Variables

When the orchestrator resolves expressions, the following variables are available in the template context:

### Upstream Node Outputs

Every node that has already executed in the current run is available by its `node_id`. Each node's output is a dict keyed by port name:

```python
# If categorizer_abc123 produced {"category": "billing", "raw": "..."}
# then in a template:
{{ categorizer_abc123.category }}  # -> "billing"
{{ categorizer_abc123.raw }}       # -> "..."
```

### The `trigger` Shorthand

The special `trigger` variable refers to whichever trigger fired the current execution. This is particularly useful in workflows with multiple triggers (e.g., a chat trigger and a Telegram trigger feeding the same downstream agent).

| Property | Type | Description |
|----------|------|-------------|
| `trigger.text` | `string` | The message text from the trigger |
| `trigger.payload` | `dict` | The full trigger payload (varies by trigger type) |

```jinja2
{# Works regardless of which trigger fired #}
You are responding to: {{ trigger.text }}

{# Access nested payload data #}
Chat ID: {{ trigger.payload.chat_id }}
```

!!! tip "Multi-Trigger Workflows"
    The `trigger` shorthand always resolves to the trigger that initiated the current execution. If a workflow has both a chat trigger and a Telegram trigger connected to the same agent, `{{ trigger.text }}` works correctly in both cases.

### Loop Context

Inside a loop body, the `loop` variable provides information about the current iteration:

| Property | Type | Description |
|----------|------|-------------|
| `loop.item` | `any` | The current item being iterated |
| `loop.index` | `int` | Zero-based index of the current iteration |
| `loop.total` | `int` | Total number of items in the loop |

```jinja2
Processing item {{ loop.index }} of {{ loop.total }}: {{ loop.item }}
```

## Jinja2 Filters

Standard Jinja2 filters are supported for transforming values inline:

```jinja2
{{ trigger.text | upper }}           {# UPPERCASE #}
{{ trigger.text | lower }}           {# lowercase #}
{{ trigger.text | title }}           {# Title Case #}
{{ trigger.text | length }}          {# character count #}
{{ trigger.text | truncate(100) }}   {# truncate to 100 chars #}
{{ trigger.text | default("N/A") }} {# fallback if undefined #}
```

## Graceful Fallback

If an expression cannot be resolved -- because the referenced node has not executed yet, the port does not exist, or there is a syntax error -- the **original template string is returned unchanged**. This prevents crashes from misconfigured expressions.

```jinja2
{# If node_xyz has not executed, this returns the literal string: #}
{{ node_xyz.output }}
{# -> "{{ node_xyz.output }}" (unchanged) #}
```

!!! info "StrictUndefined with Graceful Recovery"
    Internally, the expression resolver uses Jinja2's `StrictUndefined` mode, which raises an error on undefined variables. The resolver catches this error and falls back to the original template string. This means partial resolution does not happen -- either the entire template resolves successfully, or none of it does.

## Frontend Variable Picker

The workflow editor provides a visual way to insert expressions without typing them manually.

### The { } Button

On System Prompt, Code Snippet, and Extra Config fields, a **{ }** button appears next to the text area. Clicking it opens the **Variable Picker** popover:

1. The picker performs a BFS traversal of upstream nodes from the current node.
2. It displays each reachable node with its output ports.
3. Clicking a port inserts `{{ nodeId.portName }}` at the cursor position in the text area.

This ensures you only see variables that are actually available to the current node based on the workflow topology.

### Syntax Highlighting

All three CodeMirror modal editors (System Prompt, Code Snippet, Extra Config) apply Jinja2 syntax highlighting:

| Element | Style |
|---------|-------|
| `{{ }}`, `{% %}`, `{# #}` brackets | Bold, lighter green |
| Inner content between brackets | Bold, amber/orange |

The highlighting is implemented as a CodeMirror 6 `ViewPlugin` that applies decorations to regex-matched Jinja2 delimiters in visible ranges. Both light and dark theme variants are provided. Whitespace-control variants (`{{-`, `-%}}`, `{%-`, etc.) are also recognized.

## Resolution Implementation

Expression resolution happens in `platform/services/expressions.py` and is invoked by the orchestrator before each node executes:

1. **`resolve_expressions(template_str, node_outputs, trigger)`** -- resolves a single string template.
2. **`resolve_config_expressions(config, node_outputs, trigger)`** -- recursively resolves all string values in a config dict, including nested dicts and lists.

The orchestrator calls these on both `system_prompt` and `extra_config` before passing the node configuration to its component factory:

```python
# In orchestrator.py, before executing a component:
if db_node.component_config.system_prompt:
    db_node.component_config.system_prompt = resolve_expressions(
        db_node.component_config.system_prompt, node_outputs, trigger
    )
if db_node.component_config.extra_config:
    db_node.component_config.extra_config = resolve_config_expressions(
        db_node.component_config.extra_config, node_outputs, trigger
    )
```

!!! note "Short-Circuit Optimization"
    If the template string does not contain `{{`, the resolver returns it immediately without invoking the Jinja2 engine. This keeps resolution fast for nodes that do not use expressions.

# Adding Components

This guide walks through the complete process of adding a new workflow component type to Pipelit. A component type is a kind of node that can be placed on the workflow canvas.

!!! danger "Register in ALL required places"
    New component types must be registered in **every** layer of the stack. Missing any registration point will cause build errors, validation failures, or missing UI elements. Follow all steps below.

## Overview

Adding a new component requires changes in up to six places:

| Step | File(s) | Layer |
|------|---------|-------|
| 1. Register node type | `platform/schemas/node_type_defs.py` | Schema |
| 2. Implement component | `platform/components/your_component.py` | Backend |
| 3. Register import | `platform/components/__init__.py` | Backend |
| 4. Add polymorphic identity | `platform/models/node.py` (if needed) | ORM |
| 5. Add Pydantic literal | `platform/frontend/src/types/models.ts` | Frontend |
| 6. Create migration | `platform/alembic/versions/` (if schema changes) | Database |

## Step 1: Register the Node Type

Define the component's ports (inputs and outputs) in `platform/schemas/node_type_defs.py`:

```python
register_node_type(NodeTypeSpec(
    component_type="my_component",
    display_name="My Component",
    description="Does something useful",
    category="logic",  # trigger, ai, tool, logic, memory, sub_component, self_awareness
    inputs=[
        PortDefinition(
            name="input",
            data_type=DataType.STRING,
            required=True,
            description="The input text",
        ),
    ],
    outputs=[
        PortDefinition(
            name="output",
            data_type=DataType.STRING,
            description="The processed result",
        ),
    ],
))
```

### Available Data Types

The `DataType` enum defines the types that ports can carry:

| DataType | Description |
|----------|-------------|
| `STRING` | Text data |
| `NUMBER` | Numeric data (int or float) |
| `BOOLEAN` | True/false |
| `OBJECT` | JSON object (dict) |
| `ARRAY` | JSON array (list) |
| `MESSAGES` | LangGraph message list |
| `ANY` | Accepts any type |

### NodeTypeSpec Fields

| Field | Type | Description |
|-------|------|-------------|
| `component_type` | `str` | Unique identifier (used everywhere) |
| `display_name` | `str` | Human-readable name for the UI |
| `description` | `str` | Short description shown in the node palette |
| `category` | `str` | Grouping in the palette |
| `inputs` | `list[PortDefinition]` | Input ports |
| `outputs` | `list[PortDefinition]` | Output ports |
| `requires_model` | `bool` | Whether this node needs an AI model sub-component |
| `requires_tools` | `bool` | Whether this node accepts tool connections |
| `requires_memory` | `bool` | Whether this node accepts a memory connection |
| `requires_output_parser` | `bool` | Whether this node accepts an output parser |
| `config_schema` | `dict` | JSON Schema for `extra_config` fields |
| `executable` | `bool` | Whether this node shows execution badges (default `True`) |

## Step 2: Implement the Component

Create a new file in `platform/components/`. The component is a factory function decorated with `@register`:

```python title="platform/components/my_component.py"
"""My component — does something useful."""

from __future__ import annotations

from components import register


@register("my_component")
def my_component_factory(node):
    """Build a LangGraph node function for this component.

    Args:
        node: The WorkflowNode ORM instance (with config, edges, etc.)

    Returns:
        A callable that takes WorkflowState dict and returns an output dict.
    """
    # Read configuration from the node
    config = node.component_config
    extra = config.extra_config or {}
    my_setting = extra.get("my_setting", "default_value")

    def run(state: dict) -> dict:
        # Access input data from upstream nodes via state
        # The orchestrator resolves Jinja2 expressions before calling this
        input_text = state.get("input", "")

        # Do your processing
        result = f"Processed: {input_text}"

        # Return output ports as a flat dict
        return {"output": result}

    return run
```

### Component Conventions

- **Return a flat dict** with keys matching your output port names
- **Underscore-prefixed keys** are reserved for side effects:
    - `_route` -- sets `state["route"]` for conditional routing
    - `_messages` -- appended to the LangGraph message list
    - `_state_patch` -- merged into global state
- **Do not use `node_id`** in the component logic; components are node-agnostic
- **Tool components** return a LangChain `@tool` function instead of a state function

### Tool Component Example

Tool components are used as sub-components attached to agent nodes. They return a LangChain tool:

```python title="platform/components/my_tool.py"
from __future__ import annotations

from langchain_core.tools import tool

from components import register


@register("my_tool")
def my_tool_factory(node):
    """Return a LangChain tool."""
    config = node.component_config
    extra = config.extra_config or {}

    @tool
    def my_tool(query: str) -> str:
        """Description of what this tool does (shown to the LLM)."""
        # Tool implementation
        return f"Result for: {query}"

    return my_tool
```

## Step 3: Register the Import

Add your component module to the imports in `platform/components/__init__.py`:

```python title="platform/components/__init__.py"
# Import all component modules to trigger @register decorators
from components import (  # noqa: E402, F401
    # ... existing imports ...
    my_component,    # <-- Add your component here
)
```

This import triggers the `@register` decorator, adding your factory to the `COMPONENT_REGISTRY`.

## Step 4: Add Polymorphic Identity (If Needed)

If your component requires custom fields on `BaseComponentConfig` beyond what `extra_config` provides, you may need to add columns to the `component_configs` table.

For most components, the existing `extra_config` JSON field is sufficient -- store custom settings there:

```python
extra = config.extra_config or {}
my_setting = extra.get("my_setting", "default_value")
```

If you do need new columns on `BaseComponentConfig`, add them to `platform/models/node.py` and create an Alembic migration.

## Step 5: Add Frontend Type Definition

Add your component type to the `ComponentType` union in `platform/frontend/src/types/models.ts`:

```typescript
export type ComponentType =
    | "trigger_telegram"
    | "trigger_manual"
    // ... existing types ...
    | "my_component"    // <-- Add here
```

The frontend dynamically loads node type specifications from the `/api/v1/workflows/node-types/` endpoint, so the palette entry and port handles appear automatically once the backend registration is complete.

## Step 6: Create Migration (If Needed)

If you modified SQLAlchemy models (added columns, changed constraints), create an Alembic migration:

```bash
cd platform
source ../.venv/bin/activate

# Check for conflicting heads
alembic heads

# Generate migration
alembic revision --autogenerate -m "add my_component support"

# Review the generated file, then apply
alembic upgrade head
```

See [Migrations](migrations.md) for best practices.

## Testing Your Component

Write tests for the new component in `platform/tests/`:

```python title="platform/tests/test_my_component.py"
"""Tests for my_component."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_platform_dir = str(Path(__file__).resolve().parent.parent)
if _platform_dir not in sys.path:
    sys.path.insert(0, _platform_dir)

from components import get_component_factory


def test_my_component_basic():
    """Test basic component behavior."""
    factory = get_component_factory("my_component")

    # Create a mock node with minimal config
    class MockConfig:
        extra_config = {"my_setting": "test_value"}

    class MockNode:
        component_config = MockConfig()

    run = factory(MockNode())
    result = run({"input": "hello"})

    assert "output" in result
    assert result["output"] == "Processed: hello"
```

## Verification Checklist

After completing all steps, verify:

- [ ] `python -c "from components import get_component_factory; get_component_factory('my_component')"` succeeds
- [ ] The component appears in `GET /api/v1/workflows/node-types/`
- [ ] The node can be added to a workflow canvas in the UI
- [ ] Edges can be created to/from the node respecting port types
- [ ] The node executes correctly in a workflow
- [ ] Tests pass: `python -m pytest tests/ -v`

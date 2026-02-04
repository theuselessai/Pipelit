"""Register all built-in node type definitions."""

from services.topology import SUB_COMPONENT_TYPES
from schemas.node_types import DataType, NodeTypeSpec, PortDefinition, register_node_type

# ── Triggers ──────────────────────────────────────────────────────────────────

register_node_type(NodeTypeSpec(
    component_type="trigger_telegram",
    display_name="Telegram Trigger",
    description="Receives messages from Telegram",
    category="trigger",
    outputs=[
        PortDefinition(name="text", data_type=DataType.STRING, description="Message text"),
        PortDefinition(name="chat_id", data_type=DataType.NUMBER, description="Telegram chat ID"),
        PortDefinition(name="payload", data_type=DataType.OBJECT, description="Full trigger payload"),
    ],
))

register_node_type(NodeTypeSpec(
    component_type="trigger_webhook",
    display_name="Webhook Trigger",
    category="trigger",
    outputs=[
        PortDefinition(name="body", data_type=DataType.OBJECT),
        PortDefinition(name="headers", data_type=DataType.OBJECT),
    ],
))

register_node_type(NodeTypeSpec(
    component_type="trigger_manual",
    display_name="Manual Trigger",
    category="trigger",
    outputs=[PortDefinition(name="payload", data_type=DataType.OBJECT)],
))

register_node_type(NodeTypeSpec(
    component_type="trigger_schedule",
    display_name="Schedule Trigger",
    category="trigger",
    outputs=[PortDefinition(name="timestamp", data_type=DataType.STRING)],
))

register_node_type(NodeTypeSpec(
    component_type="trigger_chat",
    display_name="Chat Trigger",
    category="trigger",
    outputs=[
        PortDefinition(name="text", data_type=DataType.STRING),
        PortDefinition(name="payload", data_type=DataType.OBJECT),
    ],
))

register_node_type(NodeTypeSpec(
    component_type="trigger_workflow",
    display_name="Workflow Trigger",
    category="trigger",
    outputs=[PortDefinition(name="payload", data_type=DataType.OBJECT)],
))

register_node_type(NodeTypeSpec(
    component_type="trigger_error",
    display_name="Error Trigger",
    category="trigger",
    outputs=[PortDefinition(name="error", data_type=DataType.OBJECT)],
))

# ── AI Agents ─────────────────────────────────────────────────────────────────

register_node_type(NodeTypeSpec(
    component_type="agent",
    display_name="Agent",
    description="LangGraph react agent with tools",
    category="ai",
    requires_model=True, requires_tools=True, requires_memory=True,
    inputs=[PortDefinition(name="messages", data_type=DataType.MESSAGES, required=True)],
    outputs=[
        PortDefinition(name="messages", data_type=DataType.MESSAGES),
        PortDefinition(name="output", data_type=DataType.STRING),
    ],
))

register_node_type(NodeTypeSpec(
    component_type="categorizer",
    display_name="Categorizer",
    description="Classifies input into categories",
    category="ai",
    requires_model=True, requires_memory=True, requires_output_parser=True,
    inputs=[PortDefinition(name="messages", data_type=DataType.MESSAGES, required=True)],
    outputs=[
        PortDefinition(name="category", data_type=DataType.STRING),
        PortDefinition(name="route", data_type=DataType.STRING),
    ],
))

register_node_type(NodeTypeSpec(
    component_type="router",
    display_name="Router",
    description="Routes to different branches based on input",
    category="ai",
    requires_model=True, requires_memory=True, requires_output_parser=True,
    inputs=[PortDefinition(name="messages", data_type=DataType.MESSAGES, required=True)],
    outputs=[PortDefinition(name="route", data_type=DataType.STRING)],
))

register_node_type(NodeTypeSpec(
    component_type="extractor",
    display_name="Extractor",
    description="Extracts structured data from input",
    category="ai",
    requires_model=True, requires_memory=True, requires_output_parser=True,
    inputs=[PortDefinition(name="messages", data_type=DataType.MESSAGES, required=True)],
    outputs=[PortDefinition(name="extracted", data_type=DataType.OBJECT)],
))

# ── Sub-components ────────────────────────────────────────────────────────────

register_node_type(NodeTypeSpec(
    component_type="ai_model",
    display_name="AI Model",
    category="sub_component",
    outputs=[PortDefinition(name="model", data_type=DataType.OBJECT)],
))

register_node_type(NodeTypeSpec(
    component_type="run_command",
    display_name="Run Command",
    category="sub_component",
    inputs=[PortDefinition(name="command", data_type=DataType.STRING)],
    outputs=[PortDefinition(name="result", data_type=DataType.STRING)],
))

register_node_type(NodeTypeSpec(
    component_type="http_request",
    display_name="HTTP Request",
    category="sub_component",
    inputs=[PortDefinition(name="url", data_type=DataType.STRING, required=True)],
    outputs=[PortDefinition(name="result", data_type=DataType.STRING)],
))

register_node_type(NodeTypeSpec(
    component_type="web_search",
    display_name="Web Search",
    category="sub_component",
    inputs=[PortDefinition(name="query", data_type=DataType.STRING, required=True)],
    outputs=[PortDefinition(name="result", data_type=DataType.STRING)],
))

register_node_type(NodeTypeSpec(
    component_type="calculator",
    display_name="Calculator",
    category="sub_component",
    inputs=[PortDefinition(name="expression", data_type=DataType.STRING)],
    outputs=[PortDefinition(name="result", data_type=DataType.STRING)],
))

register_node_type(NodeTypeSpec(
    component_type="datetime",
    display_name="Date & Time",
    category="sub_component",
    outputs=[PortDefinition(name="result", data_type=DataType.STRING)],
))

register_node_type(NodeTypeSpec(
    component_type="output_parser",
    display_name="Output Parser",
    category="sub_component",
    inputs=[PortDefinition(name="text", data_type=DataType.STRING)],
    outputs=[PortDefinition(name="parsed", data_type=DataType.OBJECT)],
))

# ── Memory ───────────────────────────────────────────────────────────────────

register_node_type(NodeTypeSpec(
    component_type="memory_read",
    display_name="Memory Read",
    description="Recall tool — retrieves information from global memory",
    category="sub_component",
    outputs=[
        PortDefinition(name="result", data_type=DataType.STRING, description="Retrieved memory content"),
    ],
    config_schema={
        "type": "object",
        "properties": {
            "memory_type": {
                "type": "string",
                "enum": ["facts", "episodes", "procedures", "all"],
                "default": "facts",
                "description": "Type of memory to search",
            },
            "limit": {
                "type": "integer",
                "default": 10,
                "minimum": 1,
                "maximum": 100,
                "description": "Maximum results to return",
            },
            "min_confidence": {
                "type": "number",
                "default": 0.5,
                "minimum": 0,
                "maximum": 1,
                "description": "Minimum confidence for facts",
            },
        },
    },
))

register_node_type(NodeTypeSpec(
    component_type="memory_write",
    display_name="Memory Write",
    description="Remember tool — stores information in global memory",
    category="sub_component",
    outputs=[
        PortDefinition(name="result", data_type=DataType.STRING, description="Confirmation of what was stored"),
    ],
    config_schema={
        "type": "object",
        "properties": {
            "fact_type": {
                "type": "string",
                "enum": ["user_preference", "world_knowledge", "self_knowledge", "correction", "relationship"],
                "default": "world_knowledge",
                "description": "Type of fact being stored",
            },
            "overwrite": {
                "type": "boolean",
                "default": True,
                "description": "Overwrite if key exists",
            },
        },
    },
))

register_node_type(NodeTypeSpec(
    component_type="identify_user",
    display_name="Identify User",
    description="Identify who is talking and load their context",
    category="memory",
    inputs=[
        PortDefinition(name="trigger_input", data_type=DataType.OBJECT, required=True, description="Raw trigger payload"),
        PortDefinition(name="channel", data_type=DataType.STRING, required=True, description="Channel type (telegram, webhook, etc.)"),
    ],
    outputs=[
        PortDefinition(name="user_id", data_type=DataType.STRING, description="Canonical user ID"),
        PortDefinition(name="user_context", data_type=DataType.OBJECT, description="User facts, preferences, history"),
        PortDefinition(name="is_new_user", data_type=DataType.BOOLEAN, description="Whether this is a first-time user"),
    ],
))

register_node_type(NodeTypeSpec(
    component_type="code_execute",
    display_name="Code Execute",
    description="Execute Python or Bash code in a sandboxed environment",
    category="sub_component",
    outputs=[
        PortDefinition(name="result", data_type=DataType.STRING, description="Execution output"),
    ],
    config_schema={
        "type": "object",
        "properties": {
            "language": {
                "type": "string",
                "enum": ["python", "bash"],
                "default": "python",
                "description": "Programming language",
            },
            "timeout_seconds": {
                "type": "integer",
                "default": 30,
                "minimum": 1,
                "maximum": 300,
                "description": "Maximum execution time",
            },
            "sandbox": {
                "type": "boolean",
                "default": True,
                "description": "Enable security restrictions",
            },
        },
    },
))

# ── Logic / Flow ──────────────────────────────────────────────────────────────

register_node_type(NodeTypeSpec(
    component_type="code",
    display_name="Code",
    category="logic",
    inputs=[PortDefinition(name="input", data_type=DataType.ANY)],
    outputs=[PortDefinition(name="output", data_type=DataType.ANY)],
))

register_node_type(NodeTypeSpec(
    component_type="merge",
    display_name="Merge",
    category="flow",
    inputs=[PortDefinition(name="branches", data_type=DataType.ARRAY, required=True)],
    outputs=[PortDefinition(name="merged", data_type=DataType.OBJECT)],
))

register_node_type(NodeTypeSpec(
    component_type="filter",
    display_name="Filter",
    category="flow",
    inputs=[PortDefinition(name="input", data_type=DataType.ARRAY, required=True)],
    outputs=[PortDefinition(name="filtered", data_type=DataType.ARRAY)],
))

register_node_type(NodeTypeSpec(
    component_type="transform",
    display_name="Transform",
    category="flow",
    inputs=[PortDefinition(name="input", data_type=DataType.ANY, required=True)],
    outputs=[PortDefinition(name="output", data_type=DataType.ANY)],
))

register_node_type(NodeTypeSpec(
    component_type="loop",
    display_name="Loop",
    category="flow",
    inputs=[PortDefinition(name="items", data_type=DataType.ARRAY, required=True)],
    outputs=[PortDefinition(name="results", data_type=DataType.ARRAY)],
))

register_node_type(NodeTypeSpec(
    component_type="human_confirmation",
    display_name="Human Confirmation",
    category="flow",
    inputs=[PortDefinition(name="prompt", data_type=DataType.STRING)],
    outputs=[PortDefinition(name="response", data_type=DataType.STRING)],
))

register_node_type(NodeTypeSpec(
    component_type="aggregator",
    display_name="Aggregator",
    category="flow",
    inputs=[PortDefinition(name="items", data_type=DataType.ARRAY)],
    outputs=[PortDefinition(name="aggregated", data_type=DataType.ANY)],
))

# ── Mark non-executable types ─────────────────────────────────────────────────
# Triggers don't execute (they initiate), ai_model and output_parser are config-only.
# Tools (run_command, http_request, etc.) ARE executable - they run when agents invoke them.

from schemas.node_types import NODE_TYPE_REGISTRY

NON_EXECUTABLE_TYPES = {"ai_model", "output_parser"}

for _ct, _spec in NODE_TYPE_REGISTRY.items():
    if _ct.startswith("trigger_") or _ct in NON_EXECUTABLE_TYPES:
        _spec.executable = False

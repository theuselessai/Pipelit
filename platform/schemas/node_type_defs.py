"""Register all built-in node type definitions."""

from schemas.node_types import DataType, NodeTypeSpec, PortDefinition, register_node_type

# ── Shared schemas ────────────────────────────────────────────────────────────

_FILES_PORT_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "filename": {"type": "string"},
            "mime_type": {"type": "string"},
            "size_bytes": {"type": "integer"},
            "url": {"type": "string"},
        },
        "required": ["filename", "mime_type", "size_bytes", "url"],
    },
}

# ── Triggers ──────────────────────────────────────────────────────────────────

register_node_type(NodeTypeSpec(
    component_type="trigger_telegram",
    display_name="Telegram Trigger",
    description="Receives messages from Telegram via msg-gateway",
    category="trigger",
    outputs=[
        PortDefinition(name="text", data_type=DataType.STRING, description="Message text"),
        PortDefinition(name="chat_id", data_type=DataType.NUMBER, description="Telegram chat ID"),
        PortDefinition(
            name="files",
            data_type=DataType.ARRAY,
            description="Document files",
            port_schema=_FILES_PORT_SCHEMA,
        ),
        PortDefinition(name="payload", data_type=DataType.OBJECT, description="Full trigger payload"),
    ],
))

register_node_type(NodeTypeSpec(
    component_type="trigger_manual",
    display_name="Manual Trigger",
    description="Manually triggered workflow execution",
    category="trigger",
    outputs=[PortDefinition(name="payload", data_type=DataType.OBJECT, description="Manual trigger payload")],
))

register_node_type(NodeTypeSpec(
    component_type="trigger_schedule",
    display_name="Schedule Trigger",
    description="Executes workflow on a scheduled interval",
    category="trigger",
    outputs=[
        PortDefinition(name="timestamp", data_type=DataType.STRING, description="ISO 8601 timestamp of when the job fired"),
        PortDefinition(name="payload", data_type=DataType.OBJECT, description="Scheduled job payload"),
    ],
))

register_node_type(NodeTypeSpec(
    component_type="trigger_chat",
    display_name="Chat Trigger",
    description="Receives messages from external chat clients via msg-gateway generic adapter",
    category="trigger",
    outputs=[
        PortDefinition(name="text", data_type=DataType.STRING, description="Chat message text"),
        PortDefinition(
            name="files",
            data_type=DataType.ARRAY,
            description="Document files",
            port_schema=_FILES_PORT_SCHEMA,
        ),
        PortDefinition(name="payload", data_type=DataType.OBJECT, description="Full chat trigger payload"),
    ],
))

register_node_type(NodeTypeSpec(
    component_type="trigger_workflow",
    display_name="Workflow Trigger",
    description="Triggered by another workflow execution",
    category="trigger",
    outputs=[
        PortDefinition(name="text", data_type=DataType.STRING, description="Text content from workflow trigger"),
        PortDefinition(name="payload", data_type=DataType.OBJECT, description="Full trigger payload object"),
    ],
))

register_node_type(NodeTypeSpec(
    component_type="trigger_error",
    display_name="Error Trigger",
    description="Triggered when a workflow execution encounters an error",
    category="trigger",
    outputs=[PortDefinition(name="error", data_type=DataType.OBJECT)],
))

# ── Output Nodes ──────────────────────────────────────────────────────────────

register_node_type(NodeTypeSpec(
    component_type="reply_chat",
    display_name="Reply to Chat",
    description="Sends a message back to the chat caller and ends the workflow",
    category="output",
    config_schema={
        "message": {"type": "string", "description": "Message to send back (supports {{ node.output }} templates)", "default": ""},
    },
    inputs=[PortDefinition(name="input", data_type=DataType.ANY)],
    outputs=[PortDefinition(name="output", data_type=DataType.STRING)],
))

# ── AI Agents ─────────────────────────────────────────────────────────────────

register_node_type(NodeTypeSpec(
    component_type="agent",
    display_name="Agent",
    description="LangGraph react agent with tools",
    category="ai",
    requires_model=True, requires_tools=True, requires_skills=True,
    # NOTE: requires_memory is intentionally absent. It controlled the canvas memory
    # diamond handle, which was removed. The "conversation_memory" config below is
    # unrelated — it toggles SqliteSaver checkpointer persistence across executions.
    inputs=[PortDefinition(name="messages", data_type=DataType.MESSAGES, required=True)],
    outputs=[
        PortDefinition(name="messages", data_type=DataType.MESSAGES),
        PortDefinition(name="output", data_type=DataType.STRING),
    ],
    config_schema={
        "type": "object",
        "properties": {
            "conversation_memory": {
                "type": "boolean",
                "default": False,
                "description": "Enable conversation memory across executions",
            },
        },
    },
))

register_node_type(NodeTypeSpec(
    component_type="deep_agent",
    display_name="Deep Agent",
    description="Advanced agent with built-in task planning, filesystem tools, and subagents",
    category="ai",
    requires_model=True, requires_tools=True, requires_skills=True,
    inputs=[PortDefinition(name="messages", data_type=DataType.MESSAGES, required=True)],
    outputs=[
        PortDefinition(name="messages", data_type=DataType.MESSAGES),
        PortDefinition(name="output", data_type=DataType.STRING),
    ],
    config_schema={
        "type": "object",
        "properties": {
            "conversation_memory": {
                "type": "boolean",
                "default": False,
                "description": "Enable conversation memory across executions",
            },
            "enable_filesystem": {
                "type": "boolean",
                "default": False,
                "description": "Enable built-in filesystem tools",
            },
            "filesystem_backend": {
                "type": "string",
                "enum": ["state", "filesystem", "store"],
                "default": "state",
                "description": "Filesystem storage backend",
            },
            "filesystem_root_dir": {
                "type": "string",
                "default": "",
                "description": "Root directory for filesystem backend (filesystem mode only)",
            },
            "enable_todos": {
                "type": "boolean",
                "default": False,
                "description": "Enable built-in task planning (todos)",
            },
            "subagents": {
                "type": "array",
                "default": [],
                "description": "Inline subagent definitions",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "system_prompt": {"type": "string"},
                        "model": {"type": "string", "default": ""},
                    },
                    "required": ["name", "description", "system_prompt"],
                },
            },
        },
    },
))

register_node_type(NodeTypeSpec(
    component_type="categorizer",
    display_name="Categorizer",
    description="Classifies input into categories",
    category="ai",
    requires_model=True, requires_output_parser=True,
    inputs=[PortDefinition(name="messages", data_type=DataType.MESSAGES, required=True)],
    outputs=[
        PortDefinition(name="category", data_type=DataType.STRING),
        PortDefinition(name="raw", data_type=DataType.STRING, description="Raw LLM response"),
    ],
))

register_node_type(NodeTypeSpec(
    component_type="router",
    display_name="Router",
    description="Routes to different branches based on input",
    category="ai",
    requires_model=True, requires_output_parser=True,
    inputs=[PortDefinition(name="messages", data_type=DataType.MESSAGES, required=True)],
    outputs=[PortDefinition(name="route", data_type=DataType.STRING)],
))

register_node_type(NodeTypeSpec(
    component_type="extractor",
    display_name="Extractor",
    description="Extracts structured data from input",
    category="ai",
    requires_model=True, requires_output_parser=True,
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
    component_type="platform_api",
    display_name="Platform API",
    description="Make authenticated requests to the platform API",
    category="agent",
    outputs=[PortDefinition(name="response", data_type=DataType.STRING, description="JSON response from API")],
    config_schema={
        "type": "object",
        "properties": {
            "api_base_url": {
                "type": "string",
                "default": "http://localhost:8000",
                "description": "Base URL for API",
            },
        },
    },
))

register_node_type(NodeTypeSpec(
    component_type="whoami",
    display_name="Who Am I",
    description="Get self-awareness - workflow, node ID, and how to modify yourself",
    category="agent",
    outputs=[PortDefinition(name="identity", data_type=DataType.STRING, description="JSON with identity and self-modification instructions")],
))

register_node_type(NodeTypeSpec(
    component_type="get_totp_code",
    display_name="Get TOTP Code",
    description="Retrieve the current TOTP code for agent identity verification",
    category="agent",
    outputs=[PortDefinition(name="totp_code", data_type=DataType.STRING, description="JSON with username and current TOTP code")],
))

register_node_type(NodeTypeSpec(
    component_type="spawn_and_await",
    display_name="Spawn & Await",
    description="Spawn a child workflow and wait for its result inside an agent's reasoning loop",
    category="agent",
    outputs=[PortDefinition(name="result", data_type=DataType.STRING, description="JSON result from child workflow")],
))

register_node_type(NodeTypeSpec(
    component_type="workflow_create",
    display_name="Workflow Create",
    description="Create workflows programmatically from a YAML DSL specification",
    category="agent",
    outputs=[PortDefinition(name="result", data_type=DataType.STRING, description="JSON with workflow_id, slug, and counts")],
))

register_node_type(NodeTypeSpec(
    component_type="workflow_discover",
    display_name="Workflow Discover",
    description="Search existing workflows by requirements and get reuse recommendations",
    category="sub_component",
    outputs=[PortDefinition(name="result", data_type=DataType.STRING, description="JSON with matches, scores, and recommendations")],
))

register_node_type(NodeTypeSpec(
    component_type="scheduler_tools",
    display_name="Scheduler Tools",
    description="Create, pause, resume, stop, and list scheduled recurring jobs",
    category="agent",
    outputs=[PortDefinition(name="result", data_type=DataType.STRING, description="JSON result from schedule operations")],
))

register_node_type(NodeTypeSpec(
    component_type="system_health",
    display_name="System Health",
    description="Check platform infrastructure health: Redis, RQ workers, queues, stuck executions, failed executions, and scheduled jobs",
    category="agent",
    outputs=[PortDefinition(name="result", data_type=DataType.STRING, description="JSON health report with summary, checks, and issues")],
))

register_node_type(NodeTypeSpec(
    component_type="validate_gherkin",
    display_name="Validate Gherkin",
    description="Validate Gherkin .feature specs for syntax errors and lint warnings",
    category="sub_component",
    inputs=[PortDefinition(name="gherkin_spec", data_type=DataType.STRING, description="Gherkin feature spec text")],
    outputs=[PortDefinition(name="result", data_type=DataType.STRING, description="JSON validation result")],
))

register_node_type(NodeTypeSpec(
    component_type="validate_topology",
    display_name="Validate Topology",
    description="Validate a topology YAML string via the DSL compiler dry-run",
    category="sub_component",
    inputs=[PortDefinition(name="topology_yaml", data_type=DataType.STRING, description="Workflow topology YAML to validate")],
    outputs=[PortDefinition(name="result", data_type=DataType.STRING, description="JSON validation result")],
))


# ── mailbox_action operation schema ─────────────────────────────────────────
# The parameters each operation reads from extra_config, in the same shape the
# binary catalogs emit — so one form renders both. Text fields accept {{ }}
# expressions, which is how an address reaches a downstream node, so nothing
# here is validated as a literal.
_MB_ADDRESS = {
    "type": "string", "title": "Address", "placeholder": "{{ create_mailbox_1.address }}",
    "description": "Use the address the service returned, never one rebuilt from the name.",
}
_MB_JWT = {
    "type": "string", "title": "Mailbox JWT", "placeholder": "{{ create_mailbox_1.jwt }}",
    "description": "Optional. Supplying it keeps the full-service admin secret out of this call.",
}
_MB_TIMEOUT = {
    "type": "number", "title": "Timeout (seconds)", "placeholder": "150",
    "description": "Verification mail has been observed at 60-120s.",
}


def _mb(summary, outputs, **properties):
    return {"summary": summary, "outputs": outputs,
            "params": {"type": "object", "properties": properties}}


MAILBOX_OPERATIONS = {
    "create_mailbox": _mb(
        "Creates a disposable address. Emits address, address_id and a mailbox-scoped jwt.",
        ["result", "address", "address_id", "jwt"],
        name={"type": "string", "title": "Name", "placeholder": "(random, e2e-prefixed)",
              "description": "Alphanumeric only — the service silently strips everything else."},
    ),
    "wait_for_verification_email": _mb(
        "Polls for the confirmation mail, then extracts its token. Needs address; "
        "jwt optional but avoids using the admin secret.",
        ["result", "token"],
        address=_MB_ADDRESS, jwt=_MB_JWT, timeout_seconds=_MB_TIMEOUT,
    ),
    "wait_for_reset_password_email": _mb(
        "Same, for the password-reset token.",
        ["result", "token"],
        address=_MB_ADDRESS, jwt=_MB_JWT, timeout_seconds=_MB_TIMEOUT,
    ),
    "wait_for_mail": _mb(
        "Polls until any message arrives, or one matching `contains`.",
        ["result", "mails"],
        address=_MB_ADDRESS, jwt=_MB_JWT,
        contains={"type": "string", "title": "Body contains",
                  "description": "Optional. Without it the first message that arrives matches."},
        timeout_seconds=_MB_TIMEOUT,
        poll_seconds={"type": "number", "title": "Poll interval (seconds)", "placeholder": "2"},
    ),
    "list_mails": _mb(
        "Lists what is currently in the mailbox.",
        ["result", "mails"], address=_MB_ADDRESS, jwt=_MB_JWT,
    ),
    "delete_mailbox": _mb(
        "Deletes by address_id. This is what revokes the mailbox jwt.",
        ["result"],
        address_id={"type": "string", "title": "Address ID",
                    "placeholder": "{{ create_mailbox_1.address_id }}",
                    "description": "The numeric id, not the address. This is what revokes the mailbox JWT."},
    ),
    "list_unknown_mails": _mb(
        "Mail sent to addresses that do not exist — use when a wait times out.",
        ["result", "mails"],
    ),
    "prune_mailboxes": _mb(
        "Bulk delete by prefix. Dry-run unless confirm=true, and requires an explicit protect list.",
        ["result"],
        prefix={"type": "string", "title": "Prefix", "placeholder": "tmpe2e",
                "description": "Required, no default: this prefix is shared across repos and "
                               "matches other suites' mailboxes."},
        protect={"type": "array", "title": "Protect (comma separated)",
                 "placeholder": "tmpkeepme0000@mail.example",
                 "description": "Required to delete. Reconcile against your permanent-fixture "
                                "inventory first — the prefix cannot tell disposable mailboxes "
                                "from irreplaceable ones."},
        older_than_days={"type": "number", "title": "Only older than (days)",
                         "description": "Secondary guard. Measured: it cannot separate junk "
                                        "from the permanent fixtures."},
        limit={"type": "number", "title": "Scan limit", "placeholder": "100"},
        # Defaults ON: prune deletes real mailboxes on a shared instance, so the
        # harmless setting is the one you get without deciding.
        dry_run={"type": "boolean", "title": "Dry run", "default": True},
        confirm={"type": "boolean", "title": "Confirm deletion"},
    ),
}

register_node_type(NodeTypeSpec(
    component_type="mailbox_action",
    display_name="Mailbox",
    description=(
        "Disposable inboxes on the temp-mail service: create, wait for a message, "
        "read a verification or reset token, delete, prune. Needs a mailbox credential."
    ),
    category="action",
    inputs=[PortDefinition(name="input", data_type=DataType.ANY, required=False,
                           description="Optional upstream value; parameters come from config")],
    outputs=[
        PortDefinition(name="result", data_type=DataType.OBJECT, description="Operation-specific payload"),
        PortDefinition(name="address", data_type=DataType.STRING,
                       description="Mailbox address as returned by the service — authoritative"),
        PortDefinition(name="address_id", data_type=DataType.STRING,
                       description="Numeric id; every /admin/*/:id route keys on this"),
        PortDefinition(name="jwt", data_type=DataType.STRING,
                       description="Per-mailbox token, scoped to this mailbox alone"),
        PortDefinition(name="token", data_type=DataType.STRING,
                       description="Verification or reset token, for the wait_for_*_email operations"),
        PortDefinition(name="mails", data_type=DataType.ARRAY, description="Matched messages"),
    ],
    config_schema={
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "title": "Operation",
                "enum": list(MAILBOX_OPERATIONS),
                "default": "create_mailbox",
            },
        },
        "required": ["operation"],
        "x-operations": MAILBOX_OPERATIONS,
    },
))

register_node_type(NodeTypeSpec(
    component_type="mailbox_parse",
    display_name="Parse Email",
    description=(
        "Pull a verification token, a reset token, or links out of a raw message. "
        "Pure — no network and no credential, so it is safe to give an agent."
    ),
    category="sub_component",
    executable=False,
    inputs=[PortDefinition(name="raw_message", data_type=DataType.STRING, description="Raw RFC-822 message")],
    outputs=[PortDefinition(name="result", data_type=DataType.STRING, description="Extracted token, URLs, or decoded text")],
))

register_node_type(NodeTypeSpec(
    component_type="output_parser",
    display_name="Output Parser",
    category="sub_component",
    inputs=[PortDefinition(name="text", data_type=DataType.STRING)],
    outputs=[PortDefinition(name="parsed", data_type=DataType.OBJECT)],
))

register_node_type(NodeTypeSpec(
    component_type="skill",
    display_name="Skill",
    description="SKILL.md behavioral instructions for agents via progressive disclosure",
    category="sub_component",
    outputs=[PortDefinition(name="skill_path", data_type=DataType.STRING, description="Path to skills directory")],
    config_schema={
        "type": "object",
        "properties": {
            "skill_path": {
                "type": "string",
                "default": "",
                "description": "Directory containing skill subdirectories with SKILL.md files. Empty = platform default (~/.config/pipelit/skills/)",
            },
            "skill_source": {
                "type": "string",
                "enum": ["filesystem"],
                "default": "filesystem",
                "description": "Skill source type (filesystem only for now; git and registry planned)",
            },
        },
    },
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

# ── Logic / Flow ──────────────────────────────────────────────────────────────

register_node_type(NodeTypeSpec(
    component_type="switch",
    display_name="Switch",
    description="Routes to different branches based on a state field or expression",
    category="logic",
    inputs=[PortDefinition(name="input", data_type=DataType.ANY, required=True)],
    outputs=[PortDefinition(name="route", data_type=DataType.STRING)],
))

register_node_type(NodeTypeSpec(
    component_type="assertion",
    display_name="Assertion",
    description="Evaluates all rules against state and routes pass/fail",
    category="logic",
    inputs=[PortDefinition(name="input", data_type=DataType.ANY, required=True)],
    outputs=[
        PortDefinition(name="output", data_type=DataType.OBJECT, description="Results with passed flag and per-rule details"),
        PortDefinition(name="route", data_type=DataType.STRING, description="'pass' or 'fail'"),
    ],
))

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
    description="Merge outputs from multiple branches into one",
    category="logic",
    inputs=[PortDefinition(name="branches", data_type=DataType.ANY, required=True)],
    outputs=[PortDefinition(name="merged", data_type=DataType.ANY)],
))

register_node_type(NodeTypeSpec(
    component_type="filter",
    display_name="Filter",
    description="Filter array items using rule-based matching",
    category="logic",
    inputs=[PortDefinition(name="input", data_type=DataType.ARRAY, required=True)],
    outputs=[PortDefinition(name="filtered", data_type=DataType.ARRAY)],
))

register_node_type(NodeTypeSpec(
    component_type="loop",
    display_name="Loop",
    description="Iterate over an array, executing body nodes for each item",
    category="logic",
    inputs=[PortDefinition(name="items", data_type=DataType.ARRAY, required=True)],
    outputs=[PortDefinition(name="results", data_type=DataType.ARRAY)],
))

register_node_type(NodeTypeSpec(
    component_type="wait",
    display_name="Wait",
    description="Delay downstream execution by a specified duration",
    category="logic",
    inputs=[PortDefinition(name="input", data_type=DataType.ANY)],
    outputs=[PortDefinition(name="output", data_type=DataType.STRING)],
))

register_node_type(NodeTypeSpec(
    component_type="human_confirmation",
    display_name="Human Confirmation",
    category="flow",
    inputs=[PortDefinition(name="prompt", data_type=DataType.STRING)],
    outputs=[
        PortDefinition(name="confirmed", data_type=DataType.BOOLEAN, description="Whether the user confirmed"),
        PortDefinition(name="user_response", data_type=DataType.STRING, description="User's response text"),
    ],
))

register_node_type(NodeTypeSpec(
    component_type="workflow",
    display_name="Subworkflow",
    description="Execute another workflow as a child and return its output",
    category="logic",
    inputs=[PortDefinition(name="payload", data_type=DataType.ANY, description="Data passed to child workflow")],
    outputs=[PortDefinition(name="output", data_type=DataType.ANY, description="Child workflow final output")],
    config_schema={
        "type": "object",
        "properties": {
            "target_workflow": {
                "type": "string",
                "description": "Slug of the workflow to invoke",
            },
            "trigger_mode": {
                "type": "string",
                "enum": ["implicit", "explicit"],
                "default": "implicit",
                "description": "implicit = call workflow directly; explicit = go through trigger resolver",
            },
            "input_mapping": {
                "type": "object",
                "default": {},
                "description": "Map parent state fields to child trigger payload",
            },
        },
        "required": ["target_workflow"],
    },
))

# ── Mark non-executable types ─────────────────────────────────────────────────
# Triggers don't execute (they initiate), ai_model and output_parser are config-only.
# Tools (run_command, etc.) ARE executable - they run when agents invoke them.

from schemas.node_types import NODE_TYPE_REGISTRY

NON_EXECUTABLE_TYPES = {"ai_model", "output_parser", "skill"}

for _ct, _spec in NODE_TYPE_REGISTRY.items():
    if _ct.startswith("trigger_") or _ct in NON_EXECUTABLE_TYPES:
        _spec.executable = False


# Node types derived from binary catalogs, if any are present. Registered last so
# the built-ins above are already in place, and separately so that a malformed or
# missing catalog cannot stop the built-in types from loading.
from schemas.binary_catalogs import load_specs  # noqa: E402

load_specs()

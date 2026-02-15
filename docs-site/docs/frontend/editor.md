# Workflow Editor

The **Workflow Editor** is the core interface for designing and testing workflows. It opens when you navigate to `/workflows/:slug` and provides a three-panel layout built around an interactive React Flow canvas.

## Layout

The editor is split into three panels:

```
┌──────────┬──────────────────────────┬──────────┐
│          │                          │          │
│  Node    │      Workflow Canvas     │  Node    │
│  Palette │      (React Flow)        │  Details │
│  (left)  │                          │  Panel   │
│          │                          │  (right) │
│          │                          │          │
└──────────┴──────────────────────────┴──────────┘
```

- **Node Palette** (left, 240px) -- Categorized list of node types you can add to the canvas
- **Workflow Canvas** (center, flexible) -- Drag-and-drop canvas where you build the workflow graph
- **Node Details Panel** (right, 320px) -- Configuration form for the selected node; hidden when no node is selected

The editor subscribes to the `workflow:<slug>` WebSocket channel on mount, enabling real-time updates when nodes or edges change.

## Node Palette

The left panel displays all available component types organized into categories:

| Category | Node Types |
|----------|-----------|
| **Triggers** | Chat, Telegram, Schedule, Manual, Workflow, Error |
| **AI** | AI Model, Agent |
| **Routing** | Categorizer, Extractor |
| **Memory** | Memory Read, Memory Write, Identify User |
| **Agent** | WhoAmI, Create Agent User, Get TOTP Code, Platform API, Epic Tools, Task Tools, Scheduler Tools, System Health, Spawn & Await, Workflow Create |
| **Tools** | Run Command, HTTP Request, Web Search, Calculator, DateTime, Code Execute, Workflow Discover |
| **Logic** | Switch, Loop, Filter, Merge, Wait |
| **Other** | Workflow, Code, Human Confirmation, Aggregator, Error Handler, Output Parser |

Click any node type to add it to the canvas. Each click creates a new node instance with a unique auto-generated ID (e.g., `agent_m1abc2`).

## Canvas

The canvas is powered by **React Flow** (@xyflow/react v12) and supports:

- **Pan and zoom** -- Scroll to zoom, drag the background to pan
- **Node dragging** -- Drag nodes to reposition them; positions are saved to the backend on drag end
- **Edge creation** -- Drag from an output handle to an input handle to create a connection
- **Selection** -- Click a node to select it and open its details panel
- **Deletion** -- Press ++delete++ or ++backspace++ to delete selected nodes or edges
- **MiniMap** -- Small overview map in the corner for navigating large workflows
- **Controls** -- Zoom in/out and fit-to-view buttons
- **Dark mode** -- Canvas theme follows the application theme setting

### Node Visual Design

Each node on the canvas displays:

- **Icon** -- Font Awesome icon identifying the component type
- **Type label** -- The component type name (e.g., "Agent", "Telegram", "Switch")
- **Node ID** -- Shortened display label (strips the component type prefix)
- **Color-coded border** -- Each component category has a distinct color:

| Category | Color | Hex |
|----------|-------|-----|
| Triggers | Orange | `#f97316` |
| AI nodes (Agent, Categorizer, Router, Extractor) | Purple | `#8b5cf6` |
| AI Model | Blue | `#3b82f6` |
| Tools | Green | `#10b981` |
| Self-Awareness | Teal | `#14b8a6` |
| Logic (Switch, Loop, Filter, Merge, Wait) | Indigo | `#6366f1` |
| Memory | Amber | `#f59e0b` |
| Error Handler | Red | `#ef4444` |

### Node Handles

Handles are the connection points on nodes. Their shape and position indicate their purpose:

**Circle handles** (data flow):

- **Left** -- Target/input. Accepts incoming data from upstream nodes.
- **Right** -- Source/output. Sends data to downstream nodes.

**Diamond handles** (sub-component connections):

- **Bottom** -- Sub-component slots on AI-type nodes (model, tools, memory, output_parser)
- **Top** -- Source on `ai_model` nodes, connecting upward to the AI node that uses the model

### AI-Type Node Sub-Components

Agent, categorizer, router, and extractor nodes have a fixed 250px width with a separator line and sub-component pill icons at the bottom:

| Sub-Component | Icon | Handle Color | Available On |
|---------------|------|-------------|-------------|
| Model | Microchip | Blue (`#3b82f6`) | Agent, Categorizer, Router, Extractor |
| Tools | Wrench | Green (`#10b981`) | Agent only |
| Memory | Brain | Amber (`#f59e0b`) | Agent, Categorizer, Router, Extractor |
| Output Parser | File Export | Slate (`#94a3b8`) | Categorizer, Router, Extractor |

### Switch Node

Switch nodes display their routing rules as labeled output handles on the right side. Each rule has its own handle that you drag to a downstream node. If the fallback route is enabled, an "other" handle appears at the bottom.

### Loop Node

Loop nodes have special handles:

- **Each Item** (amber, right) -- Connect to the first body node
- **Done** (emerald, right) -- Connect to nodes that run after all items
- **Return** (amber, left, bottom) -- Connect from the last body node back to the loop

Loop return edges render with a distinctive **smoothstep path** that routes below the nodes with dashed stroke and a "return" label.

## Drawing Connections

To connect two nodes:

1. Hover over a source handle (right side or bottom diamond) -- the cursor changes to a crosshair
2. Click and drag to the target handle on another node
3. Release to create the edge

The system automatically determines the edge type:

- Dragging from a regular output to a regular input creates a **data flow** edge
- Dragging from a diamond handle creates a **sub-component** edge with the appropriate label (`llm`, `tool`, `memory`, `output_parser`)
- Dragging from a switch rule handle creates a **conditional** edge with the rule ID as the condition value
- Dragging from a loop's "Each Item" handle creates a **loop_body** edge

!!! note "Edge validation"
    The backend validates edge type compatibility when you create a connection. If the source output type is incompatible with the target input type, the edge creation returns a 422 error.

## Live Execution Badges

During workflow execution, each executable node displays a real-time status badge in the top-right corner:

| Badge | Status | Visual |
|-------|--------|--------|
| Spinning circle | Running | Blue, animated spin |
| Hourglass | Waiting | Cyan, animated pulse |
| Checkmark | Success | Green |
| X mark | Failed | Red |
| Dash | Idle | Gray, low opacity |

Badges only appear on executable nodes (as determined by the `executable` flag from the node type registry). Sub-components like `ai_model` and tool nodes show smaller badges in the bottom-right corner.

### Node Output Display

After a successful execution:

- **Success nodes** show a clickable **"output"** link in emerald green that opens a popover with the pretty-printed JSON output.
- **Failed nodes** show a clickable **"error"** link in red that opens a popover with error details and error code.

Execution statuses reset automatically when a new execution starts.

## Node Details Panel

Selecting a node opens the details panel on the right. The panel content varies by node type but always includes:

### Common Controls

- **Node ID** -- Displayed at the top, not editable
- **Component type** -- Shown as a secondary label
- **Interrupt Before / Interrupt After** -- Toggle switches for human-in-the-loop breakpoints
- **Save** button -- Persists all configuration changes to the backend
- **Delete** button -- Removes the node and all its connected edges

### Trigger Node Configuration

Trigger nodes show additional fields:

- **Credential** -- Select a credential for the trigger (e.g., Telegram bot token)
- **Active** -- Toggle whether the trigger is actively listening
- **Priority** -- Numeric priority for ordering when multiple triggers can handle the same event
- **Trigger Config** -- JSON editor for trigger-specific settings

The **Manual Trigger** has a **Run** button to immediately dispatch the workflow.

The **Schedule Trigger** has a dedicated section with interval, repeat count, retry, timeout, and payload settings, plus start/pause/stop controls and a live status display showing run count, errors, retries, last/next run timestamps, and expandable error details.

### AI Model Configuration

The `ai_model` node provides:

- **LLM Credential** -- Dropdown of available LLM credentials
- **Model** -- Either a dropdown of models fetched from the provider or a free-text input
- **Temperature**, **Max Tokens**, **Top P**, **Frequency Penalty**, **Presence Penalty** -- Numeric fields for LLM parameters

### Agent Configuration

Agent nodes expose:

- **System Prompt** -- Text area with an expand button (opens CodeMirror modal) and pop-out button (opens a separate browser window). Supports the variable picker for inserting Jinja2 expressions.
- **Conversation Memory** -- Toggle to persist conversation history across executions

### Categorizer, Router, Extractor

These AI-type nodes share the system prompt editor. The **Categorizer** additionally provides a category editor where you can add, edit, and remove categories with name and description fields.

### Switch Rules Editor

The switch node details panel provides a full rule editor:

- **Add Rule** -- Creates a new routing rule
- Each rule has: Label, Source Node (dropdown of upstream nodes), Output Field, Operator (grouped: Universal, String, Number, Datetime, Boolean, Array), and Value
- **Fallback Route** -- Toggle to add an "other" catch-all route

### Logic Nodes

- **Wait** -- Duration and unit (seconds/minutes/hours)
- **Filter** -- Source node, field, and a list of filter rules
- **Merge** -- Mode selector (Append or Combine)
- **Loop** -- Source node, array field, error handling (stop or continue)
- **Code** -- Language selector (Python/JavaScript/Bash) and a code editor with expand and pop-out options
- **Workflow** (subworkflow) -- Target workflow selector and trigger mode (implicit/explicit)

### Extra Config

All non-trigger nodes have an **Extra Config (JSON)** editor at the bottom. This JSON field can be expanded into a CodeMirror modal or popped out to a separate window. It supports Jinja2 expression insertion via the variable picker.

## Expression Editor and Variable Picker

Text fields that support Jinja2 expressions (System Prompt, Code, Extra Config) include a **`{ }` button** that opens the **Variable Picker**. The picker:

1. Performs a BFS backward through data edges to find all upstream nodes
2. Lists each upstream node's output ports
3. Clicking a port inserts `{{ nodeId.portName }}` at the cursor position

The expanded CodeMirror editors provide **Jinja2 syntax highlighting** via a custom ViewPlugin:

- `{{ }}` delimiters appear in bold green
- Inner expressions appear in bold amber/orange
- `{% %}` block tags and `{# #}` comments are also highlighted

## Chat Panel

Double-clicking a **Chat Trigger** node opens a dedicated chat interface instead of the standard configuration panel. The chat panel provides:

- **Message history** -- Last 10 messages, loaded from the server. A date picker allows filtering older messages.
- **Send message** -- Type a message and press Enter or click Send. The message dispatches through the workflow and the response appears when the execution completes.
- **Pop-out** -- Open the chat in a separate browser window for a larger view
- **Clear history** -- Delete all chat messages for the workflow
- **Reload** -- Refresh the message history from the server

The chat panel listens for `execution_completed` and `execution_failed` WebSocket events to display the assistant's response in real time.

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| ++delete++ / ++backspace++ | Delete selected nodes or edges |
| Mouse wheel | Zoom in/out |
| Click + drag (background) | Pan the canvas |
| Click (node) | Select node and open details panel |
| Double-click (chat trigger) | Open chat panel |

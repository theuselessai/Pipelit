# Pipelit TUI — Design Document

**Version:** 0.1.0-draft
**Date:** 2026-02-14
**Status:** Design Phase

-----

## 1. Overview

Pipelit TUI is a terminal-based mission control interface for the Pipelit orchestration platform. It provides real-time monitoring, interactive control, debugging, and conversational interaction with the orchestrator agent — all from the terminal.

### 1.1 Design Principles

- **Terminal-native** — not a web dashboard crammed into a terminal. Embraces the medium.
- **Conversational DevOps** — chat with the orchestrator as a first-class interaction mode.
- **Vim-native** — full modal interface with hjkl navigation, command mode, and composable actions.
- **Declarative & extensible** — layouts and widget bindings defined in YAML + Rhai scripts, customizable without recompiling.
- **Open-source ready** — clean architecture, documented config, theming support.

### 1.2 Target Users

- Platform operators monitoring orchestrator health and agent activity
- Developers debugging workflow execution, tool calls, and memory operations
- Power users who prefer terminal workflows over web dashboards

-----

## 2. Tech Stack

|Layer           |Choice                                     |Rationale                                                                                |
|----------------|-------------------------------------------|-----------------------------------------------------------------------------------------|
|TUI framework   |**ratatui** 0.30+                          |De facto Rust TUI standard. Immediate-mode rendering. Used by Netflix, AWS, OpenAI.      |
|Terminal backend|**crossterm**                              |Cross-platform (Windows/Mac/Linux), best ratatui integration                             |
|Async runtime   |**tokio**                                  |Required for WebSocket client, concurrent event handling                                 |
|Scripting engine|**Rhai**                                   |Embedded scripting for declarative widget bindings. Rust-like syntax, sandboxed, zero FFI|
|WebSocket client|**tokio-tungstenite**                      |Async WebSocket for real-time orchestrator connection                                    |
|Serialization   |**serde** + **serde_json** / **serde_yaml**|State deserialization from WS, layout config parsing                                     |
|Config parsing  |**toml**                                   |Theme and keybinding configuration                                                       |

### 2.1 Communication Architecture

```
┌──────────────┐     WebSocket (JSON)     ┌────────────────────┐
│  Pipelit TUI │ ◄──────────────────────► │  LangGraph API     │
│  (Rust)      │                          │  (Python)          │
└──────────────┘                          └────────────────────┘

Messages:
  TUI → Server:  { "type": "chat", "content": "..." }
                  { "type": "command", "action": "trigger_task", "task_id": "..." }
                  { "type": "subscribe", "channels": ["logs", "state"] }

  Server → TUI:  { "type": "state_update", "data": { epics, tasks, agents, health } }
                  { "type": "log_entry", "agent": "...", "level": "...", "message": "..." }
                  { "type": "chat_response", "content": "..." }
                  { "type": "tool_call", "agent": "...", "tool": "...", "args": {...} }
```

-----

## 3. Color System

### 3.1 Palette — "Mission Control"

Deep dark base with cyan accent. Technical without being cold. Optimized for long terminal sessions.

|Role            |Name           |Hex      |ANSI fallback|Usage                          |
|----------------|---------------|---------|-------------|-------------------------------|
|bg.deep         |Near-black blue|`#0A0E1A`|Black        |Main background                |
|bg.surface      |Dark navy      |`#111827`|234          |Cards, panels                  |
|bg.elevated     |Slate          |`#1E293B`|236          |Hover, selected row bg         |
|border.default  |Muted slate    |`#334155`|238          |Panel borders, dividers        |
|border.focused  |Bright slate   |`#475569`|240          |Active panel border            |
|text.primary    |Off-white      |`#E2E8F0`|White        |Primary content                |
|text.secondary  |Cool gray      |`#94A3B8`|245          |Labels, metadata               |
|text.muted      |Dark gray      |`#64748B`|242          |Timestamps, hints              |
|accent.primary  |Electric cyan  |`#0ABDC6`|Cyan         |Selection, active items, links |
|accent.secondary|Neon magenta   |`#EA00D9`|Magenta      |Highlights, interactive accents|
|status.success  |Mint green     |`#10B981`|Green        |Healthy, completed             |
|status.warning  |Amber          |`#F59E0B`|Yellow       |Degraded, attention            |
|status.error    |Hot red        |`#EF4444`|Red          |Critical, failed               |
|status.running  |Pulse blue     |`#3B82F6`|Blue         |In progress, active agent      |
|status.pending  |Neutral gray   |`#94A3B8`|245          |Waiting, idle                  |

### 3.2 Color Application Rules

- **Backgrounds**: Always use bg.* colors. Never pure black (`#000000`).
- **Text on dark**: Always `text.primary` or `text.secondary`. Never pure white (`#FFFFFF`).
- **Status indicators**: Use colored dot/icon + text label. Never color alone (accessibility).
- **Focused panel**: `border.focused` border + subtle `bg.elevated` tint on active pane.
- **Selected row**: `accent.primary` foreground on `bg.elevated` background.
- **ANSI fallback**: All colors have 256-color fallbacks for basic terminals.

### 3.3 Theme Configuration

```toml
# config/theme.toml

[colors]
bg_deep       = "#0A0E1A"
bg_surface    = "#111827"
bg_elevated   = "#1E293B"
border        = "#334155"
border_focus  = "#475569"
text_primary  = "#E2E8F0"
text_secondary = "#94A3B8"
text_muted    = "#64748B"
accent        = "#0ABDC6"
accent_alt    = "#EA00D9"
success       = "#10B981"
warning       = "#F59E0B"
error         = "#EF4444"
running       = "#3B82F6"

[borders]
style = "rounded"  # plain | rounded | double | thick

[indicators]
healthy   = "●"
running   = "●"
pending   = "○"
failed    = "✖"
warning   = "▲"
blocked   = "◌"
```

-----

## 4. Screen Architecture

### 4.1 Modal Design

Five primary modes, switchable via number keys. Each mode takes the full main content area.

|Key|Mode     |Purpose                                        |
|---|---------|-----------------------------------------------|
|`1`|Dashboard|System overview — health, agents, epic progress|
|`2`|Epics    |Task tree navigation, status management        |
|`3`|Agents   |Agent inspector, live log streams, tool calls  |
|`4`|Chat     |Conversational interface with orchestrator     |
|`5`|Debug    |Memory viewer, health diagnostics, raw state   |

### 4.2 Global Layout

Every mode shares this chrome:

```
┌─[ Pipelit ]────────────────────────────────────────────────────┐
│ 1:Dash  2:Epics  3:Agents  4:Chat  5:Debug   ● healthy  18:22 │  ← Tab bar + status
├────────────────────────────────────────────────────────────────┤
│                                                                │
│                                                                │
│                      MODE CONTENT                              │  ← Main area (mode-specific)
│                                                                │
│                                                                │
├────────────────────────────────────────────────────────────────┤
│ :                                                  ?:help q:quit│  ← Command / input bar
└────────────────────────────────────────────────────────────────┘
```

**Tab bar**: Mode tabs with active tab highlighted in `accent.primary`. System health dot + local time on right.

**Command bar**: Context-sensitive. In Normal mode: vim command input. In Chat mode: chat prompt. Shows contextual key hints on right.

-----

## 5. Mode Layouts

### 5.1 Dashboard

High-level overview. No interaction needed — purely informational at a glance.

```
┌─ System Health ───────────┬─ Active Agents ──────────────────────────┐
│                            │                                          │
│  System    ● healthy       │  worker-debug      ● running   task-042  │
│  Memory    ● operational   │  worker-deploy     ○ idle                │
│  WebSocket ● connected     │  worker-research   ● running   task-051  │
│  Uptime    4h 23m          │  worker-health     ○ idle                │
│  Last run  2m ago          │                                          │
│                            │                                          │
├─ Epic Progress ────────────┴──────────────────────────────────────────┤
│                                                                       │
│  Platform Health    ████████░░░░░░  3/5 tasks    ● in progress        │
│  Gen2 Migration     ██░░░░░░░░░░░░  1/8 tasks    ◌ blocked           │
│  Project Acacia     ██████████░░░░  5/6 tasks    ● in progress        │
│  Documentation      ████████████░░  6/7 tasks    ● in progress        │
│                                                                       │
├─ Recent Activity ─────────────────────────────────────────────────────┤
│                                                                       │
│  18:21  task-042  memory_write/read mismatch detected                 │
│  18:19  task-051  XRPL doc review — 3 issues flagged                  │
│  18:15  task-038  Gen2 schema migration — blocked on vendor           │
│  18:10  system    Scheduled health check — all clear                  │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
```

**Rhai bindings (dashboard.yaml):**

```yaml
panels:
  - id: health
    widget: key_value_card
    title: "System Health"
    bind:
      items: |
        [
          #{ key: "System",    value: app.health.status,     color: app.health.color },
          #{ key: "Memory",    value: app.memory.status,     color: app.memory.color },
          #{ key: "WebSocket", value: app.ws.status,         color: app.ws.color },
          #{ key: "Uptime",    value: app.uptime_formatted() },
          #{ key: "Last run",  value: app.last_run_ago() },
        ]

  - id: agents
    widget: agent_list
    title: "Active Agents"
    bind:
      items: "app.agents.map(|a| #{ name: a.name, status: a.status, task: a.current_task })"

  - id: epics
    widget: progress_list
    title: "Epic Progress"
    bind:
      items: "app.epics.map(|e| #{ name: e.name, done: e.done, total: e.total, status: e.status })"

  - id: activity
    widget: log_feed
    title: "Recent Activity"
    bind:
      items: "app.recent_activity.take(10)"
```

### 5.2 Epics / Tasks

k9s-style two-pane with tree navigation on left, detail on right.

```
┌─ Epics ─────────────────────┬─ Task Detail ──────────────────────────┐
│                              │                                        │
│  ▼ Platform Health      3/5  │  Fix memory_read tool                  │
│    ● Health check            │                                        │
│    ● Investigate memory      │  Status:     ● in_progress             │
│    ◉ Fix memory_read    ←    │  Priority:   critical                  │
│    ○ Add monitoring          │  Agent:      worker-debug              │
│    ○ Write tests             │  Created:    18:15 today               │
│  ▶ Gen2 Migration       1/8  │  Updated:    18:21 today               │
│  ▼ Project Acacia       5/6  │  Blocked by: none                      │
│    ● Token workflow doc      │                                        │
│    ● Panel slides            │  ─── Notes ─────────────────────────── │
│    ● DEX integration         │  Write claims success but immediate    │
│    ● Regulatory review       │  read returns empty. Suggests either   │
│    ● XRPL testing            │  scoping issue or async write not      │
│    ○ Final report            │  awaited. See diagnostic steps in      │
│  ▶ Documentation        6/7  │  agent log.                            │
│                              │                                        │
│──────────────────────────── │──────────────────────────────────────  │
│ j/k:nav  l/Enter:expand      │  e:edit  p:priority  t:trigger         │
│ h:collapse  /:search         │  a:assign  d:done  x:fail  b:block     │
└──────────────────────────────┴────────────────────────────────────────┘
```

**Vim interactions:**

|Key          |Action                     |
|-------------|---------------------------|
|`j` / `k`    |Navigate up/down in tree   |
|`l` / `Enter`|Expand epic / select task  |
|`h`          |Collapse epic / go up      |
|`gg` / `G`   |Jump to top / bottom       |
|`/`          |Search tasks               |
|`Tab`        |Switch focus between panes |
|`p`          |Set priority (opens picker)|
|`t`          |Trigger task execution     |
|`d`          |Mark task done             |
|`x`          |Mark task failed           |
|`e`          |Edit task (inline)         |
|`a`          |Assign to agent            |
|`b`          |Toggle blocked status      |
|`n`          |New task under current epic|
|`N`          |New epic                   |

### 5.3 Agent Inspector

Live agent monitoring with streaming logs and tool call inspection.

```
┌─ Agents ─────────────────────┬─ Log Stream: worker-debug ────────────┐
│                               │                                       │
│  ◉ worker-debug          ←    │  18:21:03 INFO  Starting task-042     │
│    Status:  ● running         │  18:21:03 TOOL  memory_write          │
│    Task:    task-042          │    key="test" val="hello from v-day"  │
│    Tools:   12 calls          │    → Remembered: test (created)       │
│    Uptime:  6m                │  18:21:04 TOOL  memory_read           │
│                               │    key="test"                         │
│  ○ worker-deploy              │    → No memory found for: test        │
│    Status:  ○ idle            │  18:21:04 WARN  Write/read mismatch   │
│    Last:    task-038          │  18:21:05 PROTO Layer 1 triggered     │
│                               │    query="memory persist failure"     │
│  ○ worker-research            │  18:21:06 TOOL  workflow_discover     │
│    Status:  ○ idle            │    requirements="memory fix"          │
│    Last:    task-051          │    → score: 0.32 → create_new         │
│                               │  18:21:07 INFO  Creating new workflow │
│  ○ worker-health              │  18:21:08 TOOL  memory_write          │
│    Status:  ○ idle            │    key="lesson_memory_debug"          │
│    Last:    health-check      │    → Remembered (created)             │
│                               │  18:21:08 INFO  Task complete         │
│                               │                                       │
│───────────────────────────── │───────────────────────────────────────│
│ j/k:nav  Enter:inspect        │ f:filter  /:search  c:clear           │
│ r:restart  s:stop             │ [A]ll [E]rr [W]arn [I]nfo [T]ool     │
└───────────────────────────────┴───────────────────────────────────────┘
```

**Log level filtering**: Press `A/E/W/I/T` to toggle log level visibility. Active filters shown as highlighted letters in the hint bar.

**Log coloring:**

|Level|Color                       |
|-----|----------------------------|
|ERROR|`status.error` (#EF4444)    |
|WARN |`status.warning` (#F59E0B)  |
|INFO |`text.primary` (#E2E8F0)    |
|TOOL |`accent.primary` (#0ABDC6)  |
|PROTO|`accent.secondary` (#EA00D9)|

### 5.4 Chat

Full-screen conversational interface with the orchestrator. This is the killer feature.

```
┌─ Chat with Orchestrator ──────────────────────────────────────────────┐
│                                                                       │
│  ┃ You                                              18:20             │
│  ┃ What's the status of the memory fix?                               │
│                                                                       │
│  ┃ Orchestrator                                     18:20             │
│  ┃ I investigated the memory_read tool. Write claims success          │
│  ┃ but immediate read returns empty. This points to either a          │
│  ┃ store scoping issue or an unawaited async write.                   │
│  ┃                                                                    │
│  ┃ I've created task-053 under Platform Health to track it.           │
│  ┃ Priority is currently set to high.                                 │
│                                                                       │
│  ┃ You                                              18:21             │
│  ┃ Make it critical and assign worker-debug                           │
│                                                                       │
│  ┃ Orchestrator                                     18:21             │
│  ┃ Done.                                                              │
│  ┃   task-053 → priority: critical                                    │
│  ┃   task-053 → agent: worker-debug                                   │
│  ┃ It will be picked up on the next scheduled run.                    │
│                                                                       │
│  ┃ You                                              18:22             │
│  ┃ Trigger it now                                                     │
│                                                                       │
│  ┃ Orchestrator                                     18:22             │
│  ┃ Spawning worker-debug on task-053...                               │
│  ┃ ████████░░░░ running — switch to Agents (3) to follow live.        │
│                                                                       │
├───────────────────────────────────────────────────────────────────────┤
│ > _                                                                   │
└───────────────────────────────────────────────────────────────────────┘
```

**Chat-specific keys:**

|Key                |Action                                         |
|-------------------|-----------------------------------------------|
|`Enter`            |Send message                                   |
|`Shift+Enter`      |Newline in input (multiline)                   |
|`Ctrl+k` / `Ctrl+j`|Scroll chat history                            |
|`Esc`              |Exit chat input → Normal mode (scroll with j/k)|
|`i` / `a`          |Re-enter input mode                            |
|`y`                |Yank selected message                          |
|`/`                |Search chat history                            |

**Orchestrator response formatting:**

- Tool calls and state changes rendered as indented, colored sub-blocks
- Task references (`task-053`) are highlighted in `accent.primary` — pressing Enter on them jumps to Epics mode with that task focused
- Progress bars for running operations
- Cross-references to other modes ("switch to Agents (3)")

### 5.5 Debug

Raw state inspection for troubleshooting the platform itself.

```
┌─ Debug Panels ─────────────────────────────────────────────────────────┐
│                                                                        │
│  [M]emory  [H]ealth  [S]tate  [W]ebSocket  [R]hai                     │
│                                                                        │
├─ Memory Store ─────────────────────────────────────────────────────────┤
│                                                                        │
│  Key                          │ Value                      │ Updated   │
│  ─────────────────────────────│────────────────────────────│───────────│
│  user_timezone                │ ACDT (UTC+10:30)           │ 18:15     │
│  lesson_memory_debug          │ { "solution": "check..."   │ 18:21     │
│  last_run_context             │ { "tasks_completed": 2,... │ 18:19     │
│  workflow_time_resolution     │ { "id": "wf-042", ...      │ 18:15     │
│                                                                        │
│  Total: 4 keys    Store: InMemoryStore    Status: ● connected          │
│                                                                        │
├─ Raw State (JSON) ─────────────────────────────────────────────────────┤
│                                                                        │
│  {                                                                     │
│    "health": "healthy",                                                │
│    "agents": [                                                         │
│      { "name": "worker-debug", "status": "running", ... },            │
│      { "name": "worker-deploy", "status": "idle", ... }               │
│    ],                                                                  │
│    "epics": [ ... ]                                                    │
│  }                                                                     │
│                                                                        │
│─────────────────────────────────────────────────────────────────────── │
│ M/H/S/W/R:panels  j/k:scroll  Enter:expand  /:search  r:refresh       │
└────────────────────────────────────────────────────────────────────────┘
```

-----

## 6. Rhai Scripting Layer

### 6.1 Architecture

```
  Layout YAML files                    Rhai Engine
  ┌─────────────────┐                ┌──────────────┐
  │ widget: agent_list│               │              │
  │ bind: "app.agents │──── eval ───►│  Scope:      │
  │   .filter(|a|    │               │   app = OrchestratorState
  │    a.status ==   │               │              │
  │    'running')"   │               │  Result:     │
  │                  │               │   Vec<Agent> │
  └─────────────────┘               └──────┬───────┘
                                           │
                                           ▼
                                    Ratatui Widget
                                    (renders result)
```

### 6.2 Exposed State (Rhai Scope)

The `app` object in Rhai scope mirrors the orchestrator state:

```
app
├── health
│   ├── status: String        ("healthy" | "degraded" | "critical")
│   ├── message: String
│   └── last_check: Timestamp
├── agents: Array<Agent>
│   ├── name: String
│   ├── status: String        ("running" | "idle" | "error")
│   ├── current_task: String?
│   ├── tool_calls: Int
│   └── logs: Array<LogEntry>
├── epics: Array<Epic>
│   ├── name: String
│   ├── status: String
│   ├── tasks: Array<Task>
│   │   ├── id: String
│   │   ├── title: String
│   │   ├── status: String
│   │   ├── priority: String
│   │   ├── agent: String?
│   │   ├── blocked_by: Array<String>
│   │   └── notes: String
│   ├── done: Int             (computed)
│   └── total: Int            (computed)
├── memory: Map<String, Dynamic>
├── recent_activity: Array<ActivityEntry>
├── ws
│   ├── status: String
│   └── latency_ms: Int
└── uptime_formatted(): String
```

### 6.3 Custom Widget Example

Users can create custom Rhai scripts for specialized displays:

```rhai
// scripts/custom_widgets.rhai

// Custom agent utilization widget
fn agent_utilization(agents) {
    let running = agents.filter(|a| a.status == "running").len();
    let total = agents.len();
    let pct = if total > 0 { (running * 100) / total } else { 0 };

    #{
        label: `${running}/${total} agents active (${pct}%)`,
        value: pct,
        color: if pct > 80 { "warning" } else if pct > 50 { "running" } else { "success" }
    }
}
```

-----

## 7. Keybinding System

### 7.1 Vim Modal Design

```
                    ┌──────────┐
       Esc / q      │  NORMAL  │      :
      ┌────────────►│  (nav)   │◄──────────┐
      │             └────┬─────┘           │
      │                  │                 │
      │    i / a         │ :               │
      │    ┌─────────────┘ └──────────┐    │
      ▼    ▼                          ▼    │
 ┌──────────┐                   ┌──────────┐
 │  INSERT  │                   │ COMMAND  │
 │  (chat   │                   │ (:cmd)   │
 │   input) │                   │          │
 └──────────┘                   └──────────┘
```

### 7.2 Global Keys (all modes)

|Key     |Action                  |
|--------|------------------------|
|`1`–`5` |Switch to mode          |
|`?`     |Toggle help overlay     |
|`Ctrl+c`|Quit (with confirmation)|
|`Ctrl+z`|Suspend to shell        |
|`Ctrl+r`|Force refresh state     |

### 7.3 Normal Mode Keys

|Key                |Action                                         |
|-------------------|-----------------------------------------------|
|`j` / `k`          |Navigate down / up                             |
|`h` / `l`          |Collapse / expand (trees), switch pane (splits)|
|`gg`               |Jump to top                                    |
|`G`                |Jump to bottom                                 |
|`Ctrl+d` / `Ctrl+u`|Half-page down / up                            |
|`/`                |Enter search                                   |
|`n` / `N`          |Next / previous search result                  |
|`Tab`              |Cycle focus between panes                      |
|`Enter`            |Select / drill into                            |
|`Esc`              |Back / cancel                                  |
|`y`                |Yank (copy to clipboard)                       |

### 7.4 Command Mode

Enter with `:`. Supports tab completion.

|Command                      |Action                    |
|-----------------------------|--------------------------|
|`:trigger <task-id>`         |Manually trigger a task   |
|`:priority <task-id> <level>`|Set task priority         |
|`:assign <task-id> <agent>`  |Assign task to agent      |
|`:health`                    |Run health check          |
|`:connect <url>`             |Reconnect WebSocket       |
|`:theme <name>`              |Switch color theme        |
|`:set <key> <value>`         |Runtime config change     |
|`:q` / `:quit`               |Exit                      |
|`:w`                         |Save current layout config|
|`:wq`                        |Save and quit             |

### 7.5 Keybinding Configuration

```toml
# config/keybindings.toml

[normal]
j = "navigate_down"
k = "navigate_up"
h = "collapse_or_left"
l = "expand_or_right"
gg = "jump_top"
G = "jump_bottom"
"/" = "search"
":" = "command_mode"
Tab = "cycle_focus"
Enter = "select"

[normal.mode_specific.epics]
p = "set_priority"
t = "trigger_task"
d = "mark_done"
x = "mark_failed"
n = "new_task"
N = "new_epic"

[normal.mode_specific.agents]
r = "restart_agent"
s = "stop_agent"
f = "filter_logs"
c = "clear_logs"

[insert]
Enter = "send_message"
Escape = "normal_mode"

[command]
Enter = "execute_command"
Escape = "normal_mode"
Tab = "autocomplete"
```

-----

## 8. Project Structure

```
pipelit-tui/
├── Cargo.toml
├── README.md
├── LICENSE
│
├── config/
│   ├── theme.toml                  # Color palette, border styles, indicators
│   ├── keybindings.toml            # Remappable key bindings
│   └── layouts/
│       ├── dashboard.yaml          # Dashboard panel layout + Rhai bindings
│       ├── epics.yaml              # Epic/task tree layout
│       ├── agents.yaml             # Agent inspector layout
│       ├── chat.yaml               # Chat view layout
│       └── debug.yaml              # Debug panels layout
│
├── scripts/
│   └── custom_widgets.rhai         # User-defined widget logic
│
├── src/
│   ├── main.rs                     # Entry point, arg parsing, startup
│   │
│   ├── app/
│   │   ├── mod.rs
│   │   ├── state.rs                # AppState: current mode, focus, selection
│   │   ├── actions.rs              # Action enum (all possible user actions)
│   │   └── mode.rs                 # Mode enum + transitions
│   │
│   ├── tui/
│   │   ├── mod.rs
│   │   ├── terminal.rs             # Terminal setup, teardown, panic hooks
│   │   └── event.rs                # Async event loop: crossterm + WS + tick
│   │
│   ├── input/
│   │   ├── mod.rs
│   │   ├── handler.rs              # Key → Action mapping (respects current mode)
│   │   ├── vim.rs                  # Vim modal state machine
│   │   └── command.rs              # : command parser + tab completion
│   │
│   ├── views/
│   │   ├── mod.rs                  # View trait definition
│   │   ├── dashboard.rs            # Dashboard view renderer
│   │   ├── epics.rs                # Epics/tasks tree + detail pane
│   │   ├── agents.rs               # Agent list + log stream
│   │   ├── chat.rs                 # Chat message list + input
│   │   └── debug.rs                # Debug panel tabs
│   │
│   ├── widgets/
│   │   ├── mod.rs
│   │   ├── health_card.rs          # Key-value status card
│   │   ├── progress_bar.rs         # Epic progress bars
│   │   ├── agent_list.rs           # Agent status list
│   │   ├── log_stream.rs           # Scrollable log viewer with level filter
│   │   ├── task_tree.rs            # Collapsible epic → task tree
│   │   ├── task_detail.rs          # Task metadata + notes panel
│   │   ├── chat_message.rs         # Chat bubble (user vs orchestrator)
│   │   ├── command_bar.rs          # Bottom command input
│   │   └── tab_bar.rs              # Top mode tabs + status
│   │
│   ├── scripting/
│   │   ├── mod.rs
│   │   ├── engine.rs               # Rhai engine setup, function registration
│   │   ├── bindings.rs             # Register Rust types into Rhai scope
│   │   └── layout_loader.rs        # Parse YAML layouts, resolve Rhai binds
│   │
│   ├── network/
│   │   ├── mod.rs
│   │   ├── ws_client.rs            # WebSocket connection, reconnect logic
│   │   ├── messages.rs             # Message types (serde, server ↔ TUI)
│   │   └── state_sync.rs           # Merge server state updates into AppState
│   │
│   └── config/
│       ├── mod.rs
│       ├── theme.rs                # Parse theme.toml → ratatui::Style
│       └── keymap.rs               # Parse keybindings.toml → input handler
│
└── tests/
    ├── integration/
    │   ├── ws_mock.rs              # Mock WebSocket server for testing
    │   └── render_tests.rs         # Snapshot tests for view rendering
    └── unit/
        ├── vim_tests.rs            # Vim state machine tests
        ├── rhai_tests.rs           # Rhai binding evaluation tests
        └── command_tests.rs        # Command parser tests
```

-----

## 9. Implementation Plan

### Phase 1 — Foundation (Week 1–2)

**Goal:** Terminal renders, keys work, static mock data.

- [ ] Project setup: Cargo workspace, dependencies
- [ ] `tui/terminal.rs`: Setup, teardown, panic hooks (crossterm alternate screen)
- [ ] `tui/event.rs`: Async event loop (crossterm key events + tick timer)
- [ ] `app/state.rs`: Basic AppState with mode switching
- [ ] `input/vim.rs`: Normal/Insert/Command mode state machine
- [ ] `input/handler.rs`: Key → Action dispatch
- [ ] `config/theme.rs`: Parse theme.toml, build ratatui Styles
- [ ] `widgets/tab_bar.rs` + `widgets/command_bar.rs`: Global chrome
- [ ] Static mock OrchestratorState for development

### Phase 2 — Views (Week 3–4)

**Goal:** All five modes render with mock data.

- [ ] `views/dashboard.rs`: Health card, agent list, epic progress, activity feed
- [ ] `views/epics.rs`: Tree navigation (expand/collapse), task detail pane
- [ ] `views/agents.rs`: Agent list, log stream widget with scroll
- [ ] `views/chat.rs`: Message list, input field, message formatting
- [ ] `views/debug.rs`: Tab panels, JSON tree viewer, memory table
- [ ] All supporting widgets in `widgets/`

### Phase 3 — WebSocket Integration (Week 5–6)

**Goal:** Live data from orchestrator.

- [ ] `network/ws_client.rs`: Connect, reconnect, heartbeat
- [ ] `network/messages.rs`: Define message protocol (serde)
- [ ] `network/state_sync.rs`: Merge state updates into AppState
- [ ] Wire up chat: TUI input → WS → orchestrator → WS → TUI display
- [ ] Live log streaming from agents
- [ ] Command actions (`:trigger`, `:priority`) → WS commands

### Phase 4 — Rhai Scripting (Week 7–8)

**Goal:** Declarative layout bindings, user-extensible.

- [ ] `scripting/engine.rs`: Initialize Rhai engine with sandboxing
- [ ] `scripting/bindings.rs`: Register OrchestratorState types
- [ ] `scripting/layout_loader.rs`: Parse YAML layouts, evaluate bind expressions
- [ ] Migrate hardcoded view logic to YAML + Rhai bindings
- [ ] Hot-reload: watch config files, rebuild widget tree on change
- [ ] Custom widget scripts (`scripts/custom_widgets.rhai`)

### Phase 5 — Polish & Release (Week 9–10)

**Goal:** Production-ready for open source.

- [ ] Configurable keybindings (`config/keybindings.toml`)
- [ ] Multiple theme support (dark, light, high-contrast)
- [ ] Search across all modes (tasks, logs, chat, memory)
- [ ] Clipboard integration (yank)
- [ ] Mouse support (optional, togglable)
- [ ] Comprehensive error handling + user-friendly error displays
- [ ] README, screenshots, demo GIF
- [ ] CI: cargo test, clippy, fmt
- [ ] Publish to crates.io

-----

## 10. Open Design Questions

Items to resolve during implementation:

1. **Chat multiline input** — How to handle vim Insert mode with multiline? Shift+Enter for newline, or toggle a "compose" sub-mode?
1. **Task cross-references in chat** — Should `task-053` in chat be clickable (jump to Epics mode)? If so, need a link detection + navigation system.
1. **Log buffer size** — How many log lines to keep in memory per agent? Configurable cap with LRU eviction?
1. **Offline mode** — Should the TUI gracefully degrade when WebSocket disconnects? Show stale data with "disconnected" indicator?
1. **Plugin system** — Beyond Rhai scripts, should there be a more formal plugin API? (Probably post-v1.)
1. **Notification system** — Should critical events (agent failure, health degraded) interrupt the current view with a toast/popup?

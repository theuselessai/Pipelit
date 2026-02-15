# Memories

The **Memories** page at `/memories` provides a tabbed interface for viewing and managing the platform's memory system. Agent memory is organized into five categories, each accessible via a dedicated tab.

## Tab Overview

| Tab | Description |
|-----|-------------|
| **Facts** | Key-value knowledge entries with scope, type, and confidence |
| **Episodes** | Records of agent interactions including trigger, success status, and duration |
| **Checkpoints** | LangGraph conversation checkpoints for agents with conversation memory enabled |
| **Procedures** | Learned procedures (workflows of actions) that agents can reuse |
| **Users** | Identified users from conversations, with cross-channel identity linking |

Each tab displays its own paginated table with selection checkboxes and batch delete support.

## Facts Tab

Facts are discrete knowledge entries stored as key-value pairs. The table columns:

| Column | Description |
|--------|-------------|
| **Checkbox** | Selection for batch delete |
| **Key** | The fact identifier (max 200px, truncated) |
| **Value** | The fact content (max 200px, truncated) |
| **Scope** | Badge showing the fact's scope (e.g., global, workflow, user) |
| **Type** | Badge showing the fact type |
| **Confidence** | Confidence percentage (0-100%) |
| **Accessed** | Number of times the fact has been read |
| **Updated** | Last modification timestamp |

## Episodes Tab

Episodes record individual agent interactions -- one episode per trigger event handled. The table columns:

| Column | Description |
|--------|-------------|
| **Checkbox** | Selection for batch delete |
| **Agent** | The agent node ID that handled the episode |
| **Trigger** | Badge showing the trigger type (chat, telegram, etc.) |
| **Success** | Green "Yes" or red "No" badge |
| **Summary** | Truncated episode summary (max 300px) |
| **Started** | When the episode began |
| **Duration** | Execution time in seconds |

## Checkpoints Tab

Checkpoints are LangGraph state snapshots used for conversation memory persistence. This tab includes a **thread filter** dropdown that shows distinct thread IDs from the current page.

| Column | Description |
|--------|-------------|
| **Checkbox** | Selection for batch delete |
| **Thread ID** | The conversation thread identifier (monospace) |
| **Checkpoint ID** | Truncated checkpoint UUID |
| **Parent** | Truncated parent checkpoint UUID or "--" |
| **Step** | The step number in the conversation |
| **Source** | Badge showing the checkpoint source |
| **Blob Size** | Size of the serialized state (B, KB, or MB) |

!!! info "Thread IDs"
    Thread IDs are constructed from the user profile ID, Telegram chat ID, and workflow ID. This ensures the same user talking to the same workflow gets continuous conversation history across executions.

## Procedures Tab

Procedures are learned action sequences that agents can discover and reuse. The table columns:

| Column | Description |
|--------|-------------|
| **Checkbox** | Selection for batch delete |
| **Name** | The procedure name |
| **Agent** | The agent that created the procedure |
| **Type** | Badge showing the procedure type |
| **Used** | Number of times the procedure has been invoked |
| **Success Rate** | Percentage of successful invocations |
| **Active** | Green "Yes" or gray "No" badge indicating if the procedure is available for use |

## Users Tab

The Users tab shows identified users from conversations. Users can be linked across channels (e.g., a Telegram user matched to a chat user).

| Column | Description |
|--------|-------------|
| **Checkbox** | Selection for batch delete |
| **Name** | Display name (or "--" if unknown) |
| **Canonical ID** | Unique user identifier (monospace) |
| **Telegram** | Telegram user ID (or "--") |
| **Email** | Email address (or "--") |
| **Conversations** | Total number of conversations |
| **Last Seen** | Most recent interaction timestamp |

## Batch Delete

Every tab supports batch deletion:

1. Select entries using individual checkboxes or the header checkbox (toggles all on current page)
2. Click the **Delete Selected (N)** button that appears above the table
3. Confirm in the dialog

!!! warning "Memory deletion is permanent"
    Deleted memory entries cannot be recovered. Facts, episodes, and procedures that agents rely on will no longer be available after deletion.

## Pagination

Each tab maintains its own independent pagination state with **50 items per page**. Switching tabs preserves the page position within each tab.

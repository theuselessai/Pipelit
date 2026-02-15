# Epics

The **Epics** page at `/epics` provides project-level tracking for multi-step agent operations. Epics group related tasks, track progress, and enforce budgets. This page is used to monitor autonomous agent work and manage long-running operations.

## Epic List

The list page displays a paginated table of all epics with the following columns:

| Column | Description |
|--------|-------------|
| **Checkbox** | Row selection for batch operations |
| **Title** | The epic's display title (clickable to open detail) |
| **Status** | Color-coded status badge |
| **Progress** | Completed tasks out of total tasks (e.g., "3/5 tasks") |
| **Priority** | Epic priority level |
| **Created** | Creation timestamp |

### Status Badges

Each epic status has a distinct color:

| Status | Color |
|--------|-------|
| `planning` | Yellow |
| `active` | Blue |
| `paused` | Orange |
| `completed` | Green |
| `failed` | Red |
| `cancelled` | Gray |

### Status Filter

A dropdown in the top-right corner filters epics by status. Options: All, Planning, Active, Paused, Completed, Failed, Cancelled. Changing the filter resets to page 1.

### Batch Delete

Select multiple epics and click **Delete Selected (N)** to remove them after confirmation.

### Navigation

Click any epic row to navigate to the epic detail page.

## Epic Detail

Accessible at `/epics/:epicId`, the detail page provides full information about a single epic. It subscribes to the `epic:<id>` WebSocket channel for real-time updates.

### Summary Cards

Four cards across the top display:

| Card | Content |
|------|---------|
| **Status** | Color-coded status badge |
| **Progress** | Completed/total task count |
| **Budget** | Budget amount in USD or tokens, or "No budget" |
| **Cost** | Spent amount in USD or tokens, or "No cost" |

### Description

If the epic has a description, it is displayed in a card with preformatted whitespace.

### Result Summary

For completed or failed epics:

- **Completed** epics show a "Result Summary" card
- **Failed** epics show the same content in a red-bordered "Error" card

### Tasks Table

The main section lists the epic's tasks in a paginated table:

| Column | Description |
|--------|-------------|
| **Expand** | Chevron icon for rows with details |
| **Checkbox** | Selection for batch delete |
| **Title** | Task title |
| **Status** | Color-coded status badge |
| **Workflow** | The workflow slug used to execute the task (or "--") |
| **Duration** | Execution time in seconds (or "--") |
| **Created** | Creation timestamp |

#### Task Status Colors

| Status | Color |
|--------|-------|
| `pending` | Yellow |
| `blocked` | Orange |
| `running` | Blue |
| `completed` | Green |
| `failed` | Red |
| `cancelled` | Gray |

#### Expandable Task Details

Tasks with additional information (description, dependencies, result, or error) show a clickable chevron. Expanding a task row reveals:

- **Description** -- The task description text
- **Dependencies** -- List of task IDs this task depends on (monospace)
- **Result** -- The task result summary
- **Error** -- Error message in red (for failed tasks)

### Task Batch Delete

Select multiple tasks and click the **Delete (N)** button in the table header to remove them.

### Pagination

Tasks are paginated with **50 items per page**, with independent pagination controls.

# Executions

The **Executions** pages let you monitor, inspect, and manage workflow runs. The list page shows all executions across all workflows, and the detail page provides per-node logs with expandable output.

## Execution List

Accessible at `/executions`, this page displays a paginated table of all workflow executions.

### Table Columns

| Column | Description |
|--------|-------------|
| **Checkbox** | Row selection for batch operations |
| **Execution ID** | Truncated UUID (first 8 characters), clickable to open detail |
| **Workflow** | The workflow slug that was executed |
| **Status** | Color-coded badge |
| **Started** | Timestamp when execution began |
| **Completed** | Timestamp when execution finished |

### Status Badges

Each execution status has a distinct color:

| Status | Color |
|--------|-------|
| `pending` | Yellow |
| `running` | Blue |
| `completed` | Green |
| `failed` | Red |
| `cancelled` | Gray |
| `interrupted` | Orange |

### Status Filter

A dropdown in the top-right corner lets you filter executions by status. Options include: All, Pending, Running, Interrupted, Completed, Failed, Cancelled. Changing the filter resets to page 1.

### Batch Delete

Select multiple executions using checkboxes and click **Delete Selected (N)** to remove them. The header checkbox toggles all rows on the current page.

### Pagination

Executions are paginated with **50 items per page**. Navigation controls appear at the bottom of the table.

### Navigation

Click any execution row to navigate to the execution detail page.

## Execution Detail

Accessible at `/executions/:id`, this page provides full details for a single execution. It subscribes to the `execution:<id>` WebSocket channel for real-time status updates.

### Summary Cards

Four summary cards across the top show:

| Card | Content |
|------|---------|
| **Workflow** | The workflow slug |
| **Status** | Current execution status badge |
| **Started** | Start timestamp with seconds precision |
| **Completed** | Completion timestamp with seconds precision |

### Cancel Button

When the execution is in a cancellable state (`pending`, `running`, or `interrupted`), a **Cancel Execution** button appears in the top-right corner.

### Error Display

If the execution has an error message, a red-bordered card displays the error text in a preformatted block.

### Trigger Payload

If the execution was initiated with a trigger payload, a card displays the full JSON payload in a scrollable preformatted block (max height 192px).

### Final Output

If the execution produced a final output, a card displays the JSON output in the same scrollable format.

### Node Execution Logs

The main section of the detail page is a log table showing per-node execution results:

| Column | Description |
|--------|-------------|
| **Expand** | Chevron icon for rows with output |
| **Node** | The node ID (monospace) |
| **Status** | Status badge (outline variant) |
| **Duration** | Execution time in milliseconds |
| **Timestamp** | When the node executed |

#### Expandable Output

Log rows that have an `output` field display a clickable chevron toggle. Clicking it expands the row to reveal the full output below:

- **String output** is shown as-is in a preformatted block
- **Object output** is pretty-printed as JSON

The expanded output area has a maximum height of 192px and scrolls for large outputs.

!!! tip "Inspecting node outputs"
    Use the expandable log rows to debug data flow between nodes. Each node's output shows exactly what was passed to downstream nodes via Jinja2 expression resolution.

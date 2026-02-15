# Dashboard

The **Dashboard** is the landing page after login, accessible at `/`. It displays all workflows in a paginated table and provides controls for creating, selecting, and deleting workflows.

## Workflow Table

The dashboard presents workflows in a data table with the following columns:

| Column | Description |
|--------|-------------|
| **Checkbox** | Row selection for batch operations |
| **Name** | Workflow display name (clickable to open editor) |
| **Slug** | URL-friendly identifier (auto-generated from name) |
| **Status** | Active/Inactive badge |
| **Nodes** | Number of nodes in the workflow |
| **Edges** | Number of edges (connections) in the workflow |
| **Triggers** | Number of trigger nodes |
| **Created** | Creation date |
| **Actions** | Delete button per row |

Clicking anywhere on a row navigates to the [Workflow Editor](editor.md) for that workflow.

### Pagination

The table displays **50 workflows per page** (the platform default page size). Pagination controls appear at the bottom of the table when the total number of workflows exceeds the page size.

### Loading State

While workflows are loading, the dashboard displays animated skeleton placeholders to indicate content is being fetched.

## Creating a Workflow

Click the **Create Workflow** button in the top-right corner to open a dialog with three fields:

- **Name** (required) -- The display name for the workflow.
- **Slug** (required) -- Auto-generated from the name by converting to lowercase and replacing non-alphanumeric characters with hyphens. You can override the auto-generated slug before creating.
- **Description** (optional) -- A free-text description of the workflow's purpose.

!!! tip "Slug generation"
    As you type the workflow name, the slug field updates automatically. For example, typing "My Chat Bot" generates the slug `my-chat-bot`. You can manually edit the slug if you prefer a different identifier.

After clicking **Create**, the new workflow appears in the table. Navigate to it to start designing on the canvas.

## Deleting Workflows

### Single Delete

Each row has a trash icon button on the right side. Clicking it opens a confirmation dialog:

> "Are you sure you want to delete this workflow? This action cannot be undone."

### Batch Delete

Select multiple workflows using the checkboxes, then click the **Delete Selected (N)** button that appears in the header. A confirmation dialog shows the count of workflows to be deleted.

Use the header checkbox to toggle all workflows on the current page.

!!! warning "Deletion is permanent"
    Deleting a workflow removes it along with all its nodes, edges, and associated configuration. Execution history is preserved separately on the [Executions](executions-ui.md) page.

## Layout

The dashboard, like all authenticated pages, is wrapped in the **App Layout** which provides:

- A **collapsible sidebar** on the left with navigation links (Workflows, Credentials, Executions, Epics, Memories, Agent Users)
- A **user menu** at the bottom of the sidebar with links to Settings and Logout
- The sidebar collapse state is persisted to `localStorage`

The sidebar can be collapsed to a narrow icon-only view by clicking the chevron button in the header.

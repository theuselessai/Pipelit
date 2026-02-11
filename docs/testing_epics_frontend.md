# Manual Testing Plan — Epic/Task Frontend UI (Phase 6)

## Prerequisites

```bash
# Terminal 1: Start backend
cd platform
source ../.venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2: Start frontend dev server
cd platform/frontend
npm run dev

# Terminal 3: Seed test data (get your API key from the UI first)
export API_KEY="<your-api-key>"
export BASE="http://localhost:8000/api/v1"
```

---

## 1. Sidebar Navigation

| # | Step | Expected |
|---|------|----------|
| 1.1 | Open the app, look at the sidebar | "Epics" nav item visible with ListTodo icon, between "Executions" and "Memories" |
| 1.2 | Collapse sidebar | Epics icon still visible, label hidden |
| 1.3 | Click the Epics nav item | Navigates to `/epics`, nav item highlighted |

---

## 2. Epics Page — Empty State

| # | Step | Expected |
|---|------|----------|
| 2.1 | Navigate to `/epics` | Page title "Epics" visible, status filter dropdown shows "All" |
| 2.2 | Observe table | Shows "No epics found." centered message |
| 2.3 | Check pagination | No pagination controls shown (or shows page 1 of 0) |

---

## 3. Seed Test Data via API

Run these curl commands to create test epics and tasks:

```bash
# Epic 1: planning (no tasks, standalone)
curl -s -X POST "$BASE/epics/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"title": "Build Auth System", "description": "Implement full authentication flow", "tags": ["auth", "security"], "priority": 1}' | jq .

# Epic 2: active with tasks
EPIC1=$(curl -s -X POST "$BASE/epics/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"title": "Refactor Database Layer", "description": "Migrate to new ORM patterns", "tags": ["db", "refactor"], "priority": 2}' | jq -r .id)

echo "Epic ID: $EPIC1"

# Activate the epic
curl -s -X PATCH "$BASE/epics/$EPIC1/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"status": "active"}' | jq .status

# Create tasks for the epic
curl -s -X POST "$BASE/tasks/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"epic_id\": \"$EPIC1\", \"title\": \"Create migration scripts\", \"description\": \"Write Alembic migrations for new schema\", \"priority\": 1}" | jq .

TASK1=$(curl -s -X POST "$BASE/tasks/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"epic_id\": \"$EPIC1\", \"title\": \"Update model definitions\", \"description\": \"Refactor SQLAlchemy models\", \"priority\": 2}" | jq -r .id)

curl -s -X POST "$BASE/tasks/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"epic_id\": \"$EPIC1\", \"title\": \"Write integration tests\", \"depends_on\": [\"$TASK1\"], \"priority\": 3}" | jq .

# Epic 3: completed
EPIC3=$(curl -s -X POST "$BASE/epics/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"title": "Setup CI Pipeline", "priority": 3}' | jq -r .id)

curl -s -X PATCH "$BASE/epics/$EPIC3/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"status": "completed", "result_summary": "CI pipeline deployed with GitHub Actions"}' | jq .status

# Epic 4: failed
EPIC4=$(curl -s -X POST "$BASE/epics/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"title": "Deploy to Production", "priority": 1, "budget_usd": 5.00}' | jq -r .id)

curl -s -X PATCH "$BASE/epics/$EPIC4/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"status": "failed", "result_summary": "Deployment failed: container image build timeout"}' | jq .status
```

---

## 4. Epics Page — With Data

| # | Step | Expected |
|---|------|----------|
| 4.1 | Navigate to `/epics` (or refresh) | Table shows all seeded epics |
| 4.2 | Check columns | Each row shows: Title, Status (colored badge), Progress (X/Y tasks), Priority, Created date |
| 4.3 | Verify status badge colors | planning=yellow, active=blue, completed=green, failed=red |
| 4.4 | Check progress column | Epic with tasks shows "X/Y tasks", epic without tasks shows "0/0 tasks" |
| 4.5 | Verify created date format | Shows format like "Feb 11, 14:30" |

---

## 5. Epics Page — Status Filter

| # | Step | Expected |
|---|------|----------|
| 5.1 | Click the status dropdown, select "active" | Only active epics shown, page resets to 1 |
| 5.2 | Select "completed" | Only completed epics shown |
| 5.3 | Select "failed" | Only failed epics shown |
| 5.4 | Select "planning" | Only planning epics shown |
| 5.5 | Select "All" | All epics shown again |

---

## 6. Epics Page — Selection & Batch Delete

| # | Step | Expected |
|---|------|----------|
| 6.1 | Click checkbox on one epic row | Checkbox checked, "Delete Selected (1)" button appears |
| 6.2 | Click checkbox on a second epic | Count updates to "Delete Selected (2)" |
| 6.3 | Click the header checkbox | All visible epics selected |
| 6.4 | Click the header checkbox again | All deselected, delete button disappears |
| 6.5 | Select one epic, change status filter | Selection cleared (delete button disappears) |
| 6.6 | Select one epic, click "Delete Selected" | Confirmation dialog appears: "Delete 1 Epic(s)" with Cancel/Delete buttons |
| 6.7 | Click Cancel in dialog | Dialog closes, selection preserved |
| 6.8 | Click Delete in dialog | Epic deleted, table refreshes, selection cleared |

---

## 7. Epics Page — Row Navigation

| # | Step | Expected |
|---|------|----------|
| 7.1 | Click on an epic row (not the checkbox) | Navigates to `/epics/{epicId}` |
| 7.2 | Click the checkbox cell specifically | Does NOT navigate, only toggles checkbox |

---

## 8. Epic Detail Page — Summary Cards

| # | Step | Expected |
|---|------|----------|
| 8.1 | Navigate to the active epic with tasks | Page loads with title and epic ID |
| 8.2 | Check Status card | Shows "active" badge with blue color |
| 8.3 | Check Progress card | Shows "X/Y tasks" matching actual task count |
| 8.4 | Check Budget card | Shows budget if set (e.g., "$5.00"), or "No budget" |
| 8.5 | Check Cost card | Shows cost (e.g., "$0.0000" or "0 tokens") or "No cost" |

---

## 9. Epic Detail Page — Description & Result

| # | Step | Expected |
|---|------|----------|
| 9.1 | View active epic with description | Description card visible with text |
| 9.2 | View completed epic | "Result Summary" card shown with summary text |
| 9.3 | View failed epic | "Error" card shown with red border and error text |
| 9.4 | View epic without description | No description card shown |

---

## 10. Epic Detail Page — Tasks Table

| # | Step | Expected |
|---|------|----------|
| 10.1 | View epic with tasks | Tasks table shows columns: expand chevron, checkbox, Title, Status, Workflow, Duration, Created |
| 10.2 | Task status badges | pending=yellow, blocked=orange, running=blue, completed=green, failed=red, cancelled=gray |
| 10.3 | Workflow column | Shows workflow slug if assigned, "-" otherwise |
| 10.4 | Duration column | Shows duration in seconds if > 0, "-" otherwise |
| 10.5 | View epic with no tasks | Shows "No tasks found." message |

---

## 11. Epic Detail Page — Task Row Expansion

| # | Step | Expected |
|---|------|----------|
| 11.1 | Click on a task that has a description | Row expands, shows description text |
| 11.2 | Check for dependencies | If task has `depends_on`, shows "Dependencies:" with comma-separated IDs |
| 11.3 | Click expanded task row again | Row collapses |
| 11.4 | Task without description/deps/result | No expand chevron shown, row not clickable |

To test result/error in expanded rows:
```bash
# Complete a task with result
curl -s -X PATCH "$BASE/tasks/$TASK1/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"status": "completed", "result_summary": "Models updated successfully"}' | jq .

# Fail a task with error
TASK_FAIL=$(curl -s "$BASE/epics/$EPIC1/tasks/" \
  -H "Authorization: Bearer $API_KEY" | jq -r '.items[0].id')

curl -s -X PATCH "$BASE/tasks/$TASK_FAIL/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"status": "failed", "error_message": "Migration script syntax error on line 42"}' | jq .
```

| # | Step | Expected |
|---|------|----------|
| 11.5 | Expand completed task | Shows "Result:" with summary text |
| 11.6 | Expand failed task | Shows "Error:" in red with error message |

---

## 12. Epic Detail Page — Task Selection & Batch Delete

| # | Step | Expected |
|---|------|----------|
| 12.1 | Check a task checkbox | "Delete (1)" button appears in Tasks card header |
| 12.2 | Check header checkbox | All tasks selected |
| 12.3 | Click "Delete" button | Confirmation dialog: "Delete N Tasks" |
| 12.4 | Confirm deletion | Tasks deleted, table refreshes, progress card updates |

---

## 13. WebSocket Live Updates

Open the epic detail page in one browser tab, then mutate data via curl in terminal.

| # | Step | Expected |
|---|------|----------|
| 13.1 | On epic detail page, create a task via curl | Task appears in the table without page refresh |
| 13.2 | Update epic status via curl | Status badge updates in real-time |
| 13.3 | Delete a task via curl | Task disappears from table, progress updates |
| 13.4 | Update a task status via curl | Task badge color changes without refresh |

```bash
# Create task while viewing epic detail
curl -s -X POST "$BASE/tasks/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"epic_id\": \"$EPIC1\", \"title\": \"Live update test task\"}" | jq .

# Update epic status
curl -s -X PATCH "$BASE/epics/$EPIC1/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"status": "paused"}' | jq .
```

---

## 14. Edge Cases

| # | Step | Expected |
|---|------|----------|
| 14.1 | Navigate to `/epics/nonexistent-uuid` | Shows "Loading epic..." then appropriate error or empty state |
| 14.2 | Rapidly click pagination back and forth | No crashes, selections clear properly |
| 14.3 | Open `/epics` in two tabs, delete epic in one | Other tab updates on next query refresh (within 30s stale time) |
| 14.4 | Logout and navigate to `/epics` | Redirected to login page |

---

## 15. Cleanup

```bash
# Delete all test epics (get IDs first)
EPIC_IDS=$(curl -s "$BASE/epics/" -H "Authorization: Bearer $API_KEY" | jq -r '[.items[].id] | join(",")')
echo "Epic IDs to delete: $EPIC_IDS"

# Or batch delete
curl -s -X POST "$BASE/epics/batch-delete/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"epic_ids\": $(curl -s "$BASE/epics/" -H "Authorization: Bearer $API_KEY" | jq '[.items[].id]')}"
```

---
name: pr-workflow
description: Manage GitHub PR lifecycle with human-in-the-loop approval gates. Use when user asks to review a PR, check CI, triage code review comments, fix issues, write tests for coverage, or merge a PR. Triggers on mentions of PR numbers, "check CI", "merge PR", "review PR", "fix coverage", or GitHub PR URLs. Requires gh CLI, git, and claude -p for code generation. Sends all status updates and approval requests via Telegram.
---

# PR Workflow

Structured PR lifecycle management with three approval gates. Every plan is presented as a .md report via Telegram before any code changes are made.

## Prerequisites

- `gh` CLI authenticated
- `git` with push access to the repo
- `/workspace/.local/bin/claude -p --dangerously-skip-permissions` for code generation
- Telegram bot configured (bot token + chat ID)

## Workflow

### Step 1: Check CI Status

```
gh pr view <PR#> --json statusCheckRollup
```

Poll until all checks complete. Send Telegram update with results:

```
📋 PR #<N> CI Status:
✅ backend-tests
✅ frontend-lint
❌ codecov/patch (58%, target 92%)
```

If all checks pass → skip to Step 3.
If checks fail → Step 2.

### Step 2: CI Fix Plan (Approval Gate 1)

Analyze failures:
- Fetch failed job logs via GitHub API
- Use `claude -p` to analyze root cause

Generate `/tmp/pr-<N>-ci-fix-plan.md`:

```markdown
# CI Fix Plan — PR #<N>

## Failure: <job-name>
- **Root cause:** <analysis>
- **Proposed fix:** <description>
- **Files to change:** <list>
- **Risk:** low/medium/high

## Failure: <job-name>
...
```

Send file via Telegram. **Wait for user approval before proceeding.**

After approval: apply fixes with `claude -p`, commit, push, re-run Step 1.

### Step 3: Review Triage (Approval Gate 2)

Pull review comments:

```
gh pr view <PR#> --json comments
```

Use `claude -p` to triage each issue: confirm bug vs false positive.

Generate `/tmp/pr-<N>-triage-report.md`:

```markdown
# Review Triage — PR #<N>

## Issue #1: <title>
- **Reviewer:** <name>
- **File:** <path:lines>
- **Verdict:** ✅ Confirmed bug / ❌ False positive
- **Reasoning:** <why>
- **Proposed fix:** <code change summary>

## Issue #2: <title>
...

## Summary
- Confirmed: X issues to fix
- False positives: Y issues to skip
```

Send file via Telegram. **Wait for user approval before proceeding.**

After approval: fix confirmed issues with `claude -p`, commit, push.

### Step 4: Coverage Plan (Approval Gate 3)

Check codecov status. If passing → skip to Step 5.

If failing, analyze uncovered lines. Use `claude -p` to identify what tests are needed.

Generate `/tmp/pr-<N>-coverage-plan.md`:

```markdown
# Coverage Plan — PR #<N>

Current patch coverage: X% (target: Y%)
Lines missing coverage: Z

## File: <path> (N lines uncovered)
- **Lines:** <range>
- **What they do:** <description>
- **Tests to write:**
  - `test_<name>`: <what it verifies>
  - `test_<name>`: <what it verifies>

## File: <path> (N lines uncovered)
...

## Estimated coverage after tests: ~X%
```

Send file via Telegram. **Wait for user approval before proceeding.**

After approval: write tests with `claude -p`, commit, push, re-check CI.

### Step 5: Final Check

Poll all CI checks. Send Telegram summary:

```
🏁 PR #<N> Final Status:
✅ backend-tests
✅ frontend-lint
✅ review
✅ codecov/patch
Ready to merge?
```

**Wait for user confirmation before merging.**

### Step 6: Merge

```
gh pr merge <PR#> --squash --admin
```

Send Telegram confirmation:

```
✅ PR #<N> merged.
```

## Key Rules

1. **Never make code changes without presenting a plan first** — always generate .md, send via Telegram, wait for approval.
2. **Use `claude -p` for all code generation** — it uses the flat-rate Max subscription, not per-token API.
3. **Send Telegram updates at every milestone** — the user cannot see your work in real-time.
4. **Triage critically** — not every reviewer comment is a real bug. Verify before accepting.
5. **Write proper tests** — never lower coverage thresholds to pass CI.

## Telegram Messaging

Send text:
```bash
curl -s -F chat_id=<CHAT_ID> -F text="<message>" "https://api.telegram.org/bot<TOKEN>/sendMessage"
```

Send file:
```bash
curl -s -F chat_id=<CHAT_ID> -F document=@/tmp/pr-<N>-report.md "https://api.telegram.org/bot<TOKEN>/sendDocument"
```

# Writing Skills

Skills are structured Claude Code workflows defined in YAML-frontmatter Markdown files. This guide covers how to write custom skills.

## Skill File Structure

A skill is a single `.md` file with YAML frontmatter:

```markdown
---
name: skill-name
description: What the skill does and when to trigger it
---

# Skill Name

## Overview

Description of what this skill accomplishes...
```

## YAML Frontmatter

### Required Fields

| Field | Description |
|-------|-------------|
| `name` | Unique identifier (kebab-case) |
| `description` | When to trigger this skill |

The description should include trigger phrases:

```yaml
name: pr-workflow
description: Manage GitHub PR lifecycle. Use when user asks to review a PR, check CI, merge PR, or fix coverage issues.
```

## Workflow Structure

Always pause before destructive actions (approval gates):

```markdown
### Before Merge

Send Telegram message asking for confirmation. Only proceed after user approves.
```

## Telegram Integration

Send updates via curl:

```bash
curl -s -F chat_id=<CHAT_ID> -F text="<message>" "https://api.telegram.org/bot<TOKEN>/sendMessage"
```

## Best Practices

1. **Always present plans before code changes** — Never modify code without user approval
2. **Use claude -p for code generation** — Flat-rate Max subscription
3. **Send Telegram updates at milestones** — Keep user informed
4. **Triage critically** — Not every reviewer comment is a real bug
5. **Write tests, not coverage hacks** — Never lower thresholds

## Skill Directory

Place skills in `.claude/skills/` or `docs/skills/`:

```
.claude/skills/
├── SKILL.md           # Your skill
└── references/        # Optional reference docs
```

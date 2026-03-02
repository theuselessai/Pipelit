# Skills

Skills are structured Claude Code workflows that automate repeatable engineering tasks. Each skill is a `SKILL.md` file that tells Claude Code exactly how to handle a specific scenario — what steps to take, in what order, and where to pause for human approval.

## What is a skill?

A skill is not a script. It is a prompt-based workflow definition that Claude Code loads and executes as an agent. Skills encode:

- **The trigger condition** — when to invoke this workflow (e.g., "user mentions a PR number")
- **The step sequence** — what to do and in what order
- **Approval gates** — where to pause and send a plan to the user before proceeding
- **Tool invocations** — which CLI tools and commands to run at each step

Skills are stored as `.md` files with YAML frontmatter that describes the skill's name and trigger conditions. Claude Code reads the frontmatter to decide when to invoke a skill, then follows the body as procedural instructions.

## Invoking a skill

Skills are invoked through Claude Code's `/` command syntax. Type the skill name prefixed with `/` in any Claude Code session:

```
/pr-workflow
```

You can also pass arguments:

```
/pr-workflow 42
```

Claude Code matches the command against available skills in the `.claude/skills/` directory and loads the corresponding `SKILL.md` file as the active workflow context.

!!! note "Automatic invocation"
    Skills with well-defined trigger descriptions in their frontmatter may be invoked automatically by Claude Code when the user's message matches the trigger condition — without requiring an explicit `/` command.

## Skills repository

Skills are maintained in a standalone repository:

**[github.com/theuselessai/skills](https://github.com/theuselessai/skills)**

See the repository for the full catalog of available skills, usage instructions, and how to write your own.

# Skill Backend Architecture

## Context

Deep agents use `StateBackend` (in-memory) by default. `SkillsMiddleware` reads
skill definitions via the agent's backend — so with `StateBackend`, it looks for
skills in ephemeral state rather than on the real filesystem. Skills on disk are
never found.

## Problem

Three bugs prevented skill loading:

1. **StateBackend for skills** — `create_deep_agent` defaults `backend=StateBackend`.
   `SkillsMiddleware(backend=StateBackend, sources=[...])` tries `ls_info()` and
   `download_files()` against in-memory state, not the filesystem.

2. **Tilde not expanded** — `_resolve_skills()` passed `~/...` paths as-is.
   `FilesystemBackend._resolve_path()` treated `~` as a relative directory name.

3. **No `skills/` subdir detection** — Users point to a skill repo root (e.g.
   `~/.config/pipelit/claude_skills`) which contains a `skills/` subdirectory.
   The middleware expects the source path to directly contain skill folders.

## Solution: SkillAwareBackend

A lightweight wrapper that routes file-read operations to the real filesystem
when the path falls under a known skill directory. Everything else delegates to
the agent's default backend unchanged.

```
                    SkillAwareBackend
                   /                 \
    _is_skill_path()?              NO → default backend
          |                              (StateBackend / FilesystemBackend)
         YES
          |
          v
    FilesystemBackend(root_dir=None)
    (absolute paths, real disk)
```

### Request Flow

```
SkillsMiddleware.before_agent()
    |
    v
backend.ls_info("/home/user/.config/pipelit/skills")
    |
    v
SkillAwareBackend._is_skill_path() → YES
    |
    v
FilesystemBackend.ls_info("/home/user/.config/pipelit/skills")
    → returns [{path: "web-research", is_dir: True}, ...]
    |
    v
backend.download_files([".../web-research/SKILL.md", ...])
    |
    v
SkillAwareBackend._is_skill_path() → YES (each path)
    |
    v
FilesystemBackend.download_files([...])
    → returns SKILL.md file contents from disk
    |
    v
SkillsMiddleware parses YAML frontmatter, caches skill metadata in state
```

### Why This Approach

**Alternatives considered:**

| Approach | Problem |
|----------|---------|
| Force `FilesystemBackend` globally | Breaks `StateBackend` features (todos, filesystem tools with virtual files) |
| `CompositeBackend` | Requires knowing skill paths at backend construction time; doesn't integrate cleanly with `create_deep_agent`'s middleware setup |
| Separate middleware for loading | Duplicates `SkillsMiddleware` logic; fragile coupling |
| Patch `StateBackend.ls_info` | Monkey-patching; affects all state operations |

**`SkillAwareBackend` wins because:**
- Minimal surface area — only `ls_info`, `read`, `download_files` are routed
- Works with any default backend (State, Filesystem, Store)
- Passed as `backend=` param to `create_deep_agent`, so both the main agent
  AND the general-purpose subagent receive it automatically
- No changes needed inside the `deepagents` library

### Skill Loading Lifecycle

1. **Workflow build time** — `_resolve_skills(node)` queries skill edges,
   expands `~`, auto-detects `skills/` subdirectory, returns absolute paths
2. **Agent construction** — `_make_skill_aware_backend(default, skill_paths)`
   creates a factory; passed as `backend=` to `create_deep_agent`
3. **First invocation** — `SkillsMiddleware.before_agent()` calls
   `ls_info(source)` + `download_files([...SKILL.md...])` via the backend
4. **Skill caching** — Middleware caches parsed skill metadata in agent state;
   subsequent invocations skip re-loading unless sources change

### Files Modified

| File | Change |
|------|--------|
| `platform/components/_agent_shared.py` | `SkillAwareBackend` class, `_make_skill_aware_backend()` factory, tilde expansion + subdir detection in `_resolve_skills()` |
| `platform/components/deep_agent.py` | Wraps backend with `_make_skill_aware_backend` when skills are present |
| `platform/tests/test_skill_node.py` | Tests for all three fixes + backend routing + factory |

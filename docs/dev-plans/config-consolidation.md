# Config Consolidation Plan

## Context

The skill nodes feature introduced `SKILLS_DIR` with a default of `~/.config/pipelit/skills/`. This is the first platform config to use the XDG-style `~/.config/pipelit/` directory.

This document tracks the deferred scope of consolidating all platform configs under `~/.config/pipelit/`.

## Topics to Address

1. **`.env` file location** - Currently in repo root; consider `~/.config/pipelit/.env` as alternative
2. **Database path** - Currently `platform/db.sqlite3`; consider `~/.config/pipelit/db.sqlite3`
3. **LOG_FILE** - Currently relative; consider `~/.config/pipelit/logs/`
4. **SKILLS_DIR** - Already defaults to `~/.config/pipelit/skills/` (implemented)
5. **Checkpoints DB** - Currently `platform/checkpoints.db`; consider `~/.config/pipelit/checkpoints.db`
6. **Settings page** - Add a "Default config path" display/override in the frontend Settings page

## Trigger

This discussion was triggered by the skill nodes implementation (feat/skill-nodes branch).

## Status

Deferred - not blocking any current work.

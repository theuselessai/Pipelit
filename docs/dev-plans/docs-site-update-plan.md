# Master Docs-Site Update Plan

## Overview

Combined analysis from:
1. Current docs-site gap analysis
2. Git commits since v0.1.0 (92 commits)

**Total work:**
- 10 new files
- 12 updated files
- 1 removed file
- 1 new directory

---

## Priority 0 — Critical (14 items)

### New Files
| File | Description |
|------|-------------|
| `docs-site/docs/concepts/sandbox.md` | Sandbox architecture (bwrap/rootfs/container mode) |
| `docs-site/docs/concepts/providers.md` | Multi-LLM provider guide (OpenAI, Anthropic, MiniMax, GLM) |
| `docs-site/docs/skills/index.md` | Skills concept & catalog |
| `docs-site/docs/skills/pr-workflow.md` | PR Workflow skill user docs |
| `docs-site/docs/skills/writing-skills.md` | Custom skill authoring guide |
| `docs-site/docs/components/triggers/webhook.md` | Webhook trigger reference |

### Updated Files
| File | Change |
|------|--------|
| `docs-site/docs/components/sub-components/code-execute.md` | Rewrite for bwrap/rootfs sandbox |
| `docs-site/docs/components/ai/deep-agent.md` | Add network access toggle |
| `docs-site/docs/components/triggers/telegram.md` | Add polling mode section |
| `docs-site/docs/getting-started/configuration.md` | Add conf.json layer + LLM providers |
| `docs-site/docs/getting-started/first-run.md` | Update for multi-step wizard with env detection |
| `docs-site/docs/concepts/execution.md` | Add max_execution_seconds |
| `docs-site/docs/frontend/settings-ui.md` | Document 4-tab layout |
| `docs-site/mkdocs.yml` | Add Skills nav, Providers nav, Webhook nav, remove Aggregator |

---

## Priority 1 — Important (4 items)

### New Files
| File | Description |
|------|-------------|
| `docs-site/docs/api/health.md` | Health check endpoint reference |
| `docs-site/docs/tutorials/pr-workflow-skill.md` | End-to-end skill tutorial |

### Updated Files
| File | Change |
|------|--------|
| `docs-site/docs/concepts/index.md` | Add Providers + Skills links |
| `docs-site/docs/deployment/production.md` | Add health endpoint for monitoring |

---

## Priority 2 — Polish (4 items)

### Updated Files
| File | Change |
|------|--------|
| `docs-site/docs/index.md` | Update homepage features (skills, multi-provider) |
| `docs-site/docs/concepts/security.md` | Update sandbox section |
| `docs-site/docs/faq.md` | Add skills & provider FAQ entries |

### Removed Files
| File | Reason |
|------|--------|
| `docs-site/docs/components/logic/aggregator.md` | Component removed in v0.2.0 |

---

## File Tree Summary

```
docs-site/docs/
├── index.md                                  [UPDATE]
├── getting-started/
│   ├── configuration.md                      [UPDATE] +conf.json +providers
│   └── first-run.md                          [UPDATE] multi-step wizard
├── concepts/
│   ├── index.md                              [UPDATE] +links
│   ├── sandbox.md                            [NEW]
│   ├── providers.md                          [NEW]
│   ├── execution.md                          [UPDATE] +max_execution_seconds
│   └── security.md                           [UPDATE] sandbox section
├── components/
│   ├── ai/deep-agent.md                      [UPDATE] +network toggle
│   ├── triggers/
│   │   ├── webhook.md                        [NEW]
│   │   └── telegram.md                       [UPDATE] +polling mode
│   ├── sub-components/code-execute.md        [UPDATE] rewrite sandbox
│   └── logic/
│       └── aggregator.md                     [DELETE]
├── frontend/
│   └── settings-ui.md                        [UPDATE] 4-tab layout
├── api/
│   └── health.md                             [NEW]
├── tutorials/
│   └── pr-workflow-skill.md                  [NEW]
├── skills/                                   [NEW DIR]
│   ├── index.md                              [NEW]
│   ├── pr-workflow.md                        [NEW]
│   └── writing-skills.md                     [NEW]
├── deployment/
│   └── production.md                         [UPDATE] +health endpoint
└── faq.md                                    [UPDATE] +FAQs

docs-site/mkdocs.yml                          [UPDATE] nav changes
```

---

## mkdocs.yml Nav Changes

```yaml
# ADD to Concepts:
- Sandbox: concepts/sandbox.md
- Providers: concepts/providers.md

# ADD to Components > Triggers:
- Webhook: components/triggers/webhook.md

# ADD to API:
- Health: api/health.md

# ADD new section under Contributing:
- Skills:
    - Overview: skills/index.md
    - PR Workflow: skills/pr-workflow.md
    - Writing Skills: skills/writing-skills.md

# REMOVE from Components > Logic:
- Aggregator: components/logic/aggregator.md  # DELETE
```

---

## Summary

| Priority | New Files | Updated Files | Deleted Files |
|----------|-----------|---------------|---------------|
| P0 | 6 | 8 | 0 |
| P1 | 2 | 2 | 0 |
| P2 | 0 | 3 | 1 |
| **Total** | **8** | **13** | **1** |

Plus 1 new directory: `docs-site/docs/skills/`

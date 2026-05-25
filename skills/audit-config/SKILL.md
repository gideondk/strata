---
name: strata:audit-config
description: Audit the project's Claude Code config (CLAUDE.md, .claude/settings.json, .claude/skills/, .claude/agents/, .claudeignore) for staleness per Anthropic's 3-6 month review cadence. Read-only. Invoke autonomously when the user asks about config drift, performance plateaus after a new model release, or when onboarding a new team to the codebase.
---

# strata:audit-config

[Anthropic's 2026 guidance](https://claude.com/blog/how-claude-code-works-in-large-codebases-best-practices-and-where-to-start)
on Claude Code in large codebases:

> Teams should expect to do a meaningful configuration review every three to
> six months, but it's also worth doing one whenever performance feels like
> it's plateaued after major model releases.

> Instructions optimized for older models can work against a future one.

This skill is the operational reminder. It walks your project's Claude Code
Config and reports items that haven't been touched in `--stale-days` (180 by
Default), so you can revisit them deliberately.

## When to run

- **Every 3–6 months** as a scheduled habit
- After a major Claude model release (Anthropic-recommended)
- Before onboarding a new team to the codebase
- When Claude's behaviour starts feeling sluggish or off

## How

```bash
# Default: 180-day staleness threshold
"${CLAUDE_PLUGIN_ROOT}/bin/run-python.sh" \
  "${CLAUDE_PLUGIN_ROOT}/scripts/audit-config.py"

# Tighter cadence
"${CLAUDE_PLUGIN_ROOT}/bin/run-python.sh" \
  "${CLAUDE_PLUGIN_ROOT}/scripts/audit-config.py" --stale-days 90
```

## What it covers

| File / dir | Why it matters |
|---|---|
| `CLAUDE.md` | Loaded every session; conventions drift |
| `.claude/settings.json` | Team config; check enabled plugins are still relevant |
| `.claudeignore` | Exclusion rules go stale as the repo evolves |
| `.claude/skills/` | Project-local skills — same drift risk |
| `.claude/agents/` | Sub-agent definitions — same |

Read-only, never modifies. Output is a markdown report you can paste into a
Review meeting.

## Pairs well with

- `/strata:review` — audits the **vault** (decisions, lessons, domain notes)
- `/strata:audit-config` — audits the **project's Claude Code setup**

Different surfaces. Run both on the same cadence.

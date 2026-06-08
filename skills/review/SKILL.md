---
name: strata:review
description: Vault health report, stale-proposed ADRs, stale durable notes (decayed + rarely recalled), orphan domain notes, missing frontmatter, unresolved wikilinks, stale PR-context dirs, stale Graphify code-graph. Read-only. Invoke autonomously when the user asks about vault hygiene, after a period of inactivity, or when starting a planning/cleanup session.
---

# strata:review

ADR practices die in two years because nobody comes back to maintain them.
This skill is the antidote: a monthly (or whenever) pass that surfaces the
Notes that need attention.

Read-only by design, flags issues, never auto-fixes.

## When to run

- **Monthly**, as a recurring habit. 30 minutes of cleanup.
- Before a release, to leave a clean snapshot in the vault.
- When the vault search starts feeling noisy.

## How

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/strata" review

# Tune the staleness thresholds
"${CLAUDE_PLUGIN_ROOT}/bin/strata" review \
  --stale-days 7 --pr-stale-days 14
```

## What it surfaces

| Signal | What to do |
|---|---|
| Stale-proposed ADRs | Either accept, reject, or `/strata:decide --supersedes` |
| Orphan domain notes | Add wikilinks, or merge into a neighbour |
| Missing frontmatter | Add `status:` (decisions/lessons) so the index can find them |
| Unresolved wikilinks | Typo — fix the target or create the missing note |
| Stale PR-context dirs | Run `/strata:archive` if the branch is merged |

## What backs this

`review.py` reads these signals from internal db helpers — `stale_decisions`
and `orphan_notes`. They aren't callable MCP tools; `/strata:review` is how you
surface them. For ad-hoc triage outside the full report, use the `recall` MCP
tool.

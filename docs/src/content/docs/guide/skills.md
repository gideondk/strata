---
title: Skills
description: "Every slash command Strata ships. Some are auto-invokable: when you describe a matching situation, Claude triggers them without you typing the command. Others are user-only."
---

Every slash command Strata ships. Some are auto-invokable: when you describe a situation that matches the skill's description, Claude triggers it without you typing the command. Others are user-only. They take destructive or audit-sensitive actions.

## Writes (auto-invokable)

| Command | When it fires | Output |
|---|---|---|
| `/strata:save <topic>` | "Save this", "capture what we just discussed", Stop hook nudge | `pr-context/<branch>/...md` |
| `/strata:decide <title>` | "We've decided X", "Let's commit to Y" | `decisions/YYYY-MM-DD-<slug>.md` |
| `/strata:domain <concept>` | A domain term is defined or refined ("an Order always belongs to one Customer") | `domain/<slug>.md` |
| `/strata:correct <note>` | "Fix the part about X", "Stop using <note>", "Y is no longer true" — handles edit, invalidate, and field-update paths | Updates note + audit log |
| `/strata:lint` | Before commit, automatic via pre-push hook | Scans for secrets / PII |
| `/strata:review` | Asked to audit vault health | Surfaces stale-proposed ADRs, decayed durable notes (rarely recalled), orphans, drift |
| `/strata:doctor` | "Is Strata working?", "did the install work?", after `/strata:init` | Health check: runtime deps, vault, index, semantic search, MCP server, git |
| `/strata:audit-config` | Asked about plugin config | Reports active settings |

## Reads (auto-invokable)

| Command | When it fires |
|---|---|
| `/strata:find <terms>` | "Search for…", "do we have notes about…" |
| `/strata:resume` | New session, surfaces last branch + latest notes |

Most reads happen via MCP rather than skill invocation. Claude calls `recall` (the memory-recall path) automatically when conversation overlaps known topics. See [MCP tools](../mcp-tools/).

## User-only (high stakes)

| Command | What it does |
|---|---|
| `/strata:forget <note>` | Move note to `.trash/` with audit log. Reason required. |
| `/strata:archive` | Move merged-PR context to archive folder |
| `/strata:export-to-repo` | Copy vault notes into a repo for committing |
| `/strata:promote-to-pr` | Surface vault context in PR description |

These never auto-invoke. The audit trail must reflect the user's explicit intent.

## Setup / lifecycle

| Command | Use |
|---|---|
| `/strata:init` | One-time vault setup for a repo |
| `/strata:bootstrap` | One-time migration of existing planning docs ([bootstrap guide](../bootstrap/)) |
| `/strata:graphify` | Build / refresh the code graph |

## Auto-invocation rules

A skill auto-fires when:
1. Its `description:` frontmatter matches the user's intent pattern
2. The action is safe and reversible (writes to new files; not destructive to existing data)
3. The user hasn't explicitly typed a slash command for a different skill

If you want Claude to STOP auto-invoking a skill for a turn, prefix your message with "don't save this" or similar. Claude respects opt-out phrasing.

## Composability

Skills call each other through skill instructions, not Python imports. `/strata:bootstrap` dispatches `strata:bootstrap-worker` subagents that invoke `/strata:decide` / `/strata:domain` / save scripts internally. Each layer stays composable.

---

Next: [Bootstrap](../bootstrap/) — the one-time migration that pulls existing planning docs into the vault.

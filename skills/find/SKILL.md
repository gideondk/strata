---
name: strata:find
description: Plain-text grep across the Strata vault for terms. Use when the user asks to "find", "search for", "look up", "do we have notes about", or wants to locate decisions/lessons/domain notes by literal text. For ranked / paginated results prefer the `memory_search` MCP tool; this skill is the human-friendly fallback when you want grep-style line-numbered hits.
---

# strata:find

A no-frills full-text walk over the current repo's vault namespace. For
Ranked structured queries, use the `memory_search` MCP tool instead, it uses
FTS5 and is much faster on large vaults.

## How

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/find.py" <term1> [<term2> ...] [--scope decisions|lessons|domain|pr-context|all]
```

All terms must appear in a file (AND, not OR). Use the MCP `memory_search`
Tool for phrase queries.

## Output

```
### `decisions/2026-05-20-use-postgres.md` — Use Postgres for the X store  (3 hits)
  L7: Postgres chosen over SQLite for …
  L14: …
```

Results are grouped by file, ranked by hit count.

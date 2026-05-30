---
name: strata:find
description: Grep-style line-numbered text search across the vault — the human-friendly fallback to the `memory_search` MCP tool. Prefer `memory_search` for ranked/semantic recall; use /strata:find when the user explicitly wants literal grep hits with line numbers, or asks to "grep the vault" / "find the exact line that mentions X".
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

---
name: strata:find
description: Grep-style line-numbered text search across the vault — the literal-string fallback to the `recall` MCP tool. Prefer `recall` for ranked/semantic recall; use /strata:find after recall when the user explicitly wants literal grep hits with line numbers, or asks to "grep the vault" / "find the exact line that mentions X".
---

# strata:find

A no-frills full-text walk over the current repo's vault namespace. For
Ranked or semantic queries, use the `recall` MCP tool first — it fuses FTS5
and semantic search and is much faster on large vaults. Reach for /strata:find
once recall has run and you need exact literal-string hits with line numbers.

## How

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/strata" find <term1> [<term2> ...] [--scope decisions|lessons|domain|pr-context|all]
```

All terms must appear in a file (AND, not OR). Use the `recall` MCP tool for
phrase and ranked queries.

## Output

```
### `decisions/2026-05-20-use-postgres.md` — Use Postgres for the X store  (3 hits)
  L7: Postgres chosen over SQLite for …
  L14: …
```

Results are grouped by file, ranked by hit count.

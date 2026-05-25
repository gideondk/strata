---
name: strata:graphify
description: Run Graphify (incremental update by default) to rebuild the code-structure graph. Defaults --obsidian-dir to your Strata vault so code nodes appear in Obsidian's graph view alongside decisions. Use when /strata:review reports the graph is stale, after major refactors, or to bootstrap the graph for the first time.
---

# strata:graphify

Orchestration wrapper. Doesn't bundle Graphify, shells out to whatever
`graphify` is on PATH (install separately: `pip install graphifyy`).

## What it does

- **Default**: `graphify update . --obsidian --obsidian-dir <vault>/<repo>/graphify`
  Incremental rebuild + write per-node markdown into the vault's graphify
  subfolder so Obsidian's graph view shows code structure alongside
  decisions / domain notes.
- **`--rebuild`**: full rebuild instead of incremental (slower, deterministic).
- **`--status`**: just report graph status (delegates to `code_graph` helpers).
- **`--no-obsidian`**: skip vault wiring (graph.json still produced).
- **`--deep`**: use semantic-edge LLM mode. Costs tokens AND sends content
  to an external LLM API, **do not use for regulated content**.

## How

```bash
# Default — incremental update + vault wiring
"${CLAUDE_PLUGIN_ROOT}/bin/run-python.sh" \
  "${CLAUDE_PLUGIN_ROOT}/scripts/graphify-orchestrate.py"

# Full rebuild
"${CLAUDE_PLUGIN_ROOT}/bin/run-python.sh" \
  "${CLAUDE_PLUGIN_ROOT}/scripts/graphify-orchestrate.py" --rebuild

# Status only
"${CLAUDE_PLUGIN_ROOT}/bin/run-python.sh" \
  "${CLAUDE_PLUGIN_ROOT}/scripts/graphify-orchestrate.py" --status
```

## When to invoke

- First time: bootstrap the graph for the repo.
- After major refactors (new modules, renames).
- When `/strata:review` flags the graph as stale.
- Before a session that needs code-structure context (god nodes etc.).

## Result

After running, Strata's SessionStart primer will show updated counts +
Top god nodes; `code_graph_status` MCP tool returns the fresh summary;
`memory_graph` MCP tool can cross-link decisions referencing code symbols
Back to graph nodes.

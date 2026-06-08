---
name: strata:resume
description: Re-print the Strata primer for the current branch (recent decisions, domain notes, PR-context, code-graph status). Invoke autonomously whenever the user asks "where did I leave off", "what's the current state", "pick up where we left off", "what's in flight on this branch", or when context has been compacted and you need fresh primer data. Cheap to run, preferred over re-reading raw files.
---

# strata:resume

A manual re-prime. The SessionStart hook already prints a primer at session
Launch and on every `git checkout`/`switch`, but if it has scrolled off or
Context was compacted, call this.

## How

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/prime-context.py" </dev/null
```

(The trailing `</dev/null` substitutes for the JSON-RPC payload that the hook
Runner would normally send on stdin, the script tolerates an empty stdin.)

## Tip

For *targeted* lookups, prefer the `recall` MCP tool:
- `recall(query="...", layer=1)` for ranked + semantic recall
- add `scope="decisions|domain|lessons|procedural|propositions|pr-context|all"`
  to narrow the search

`/strata:resume` is a wide net; `recall` is the tweezers.

---
name: strata:dashboard
description: Show the current state of the Strata vault, scope counts, recent activity, drifted notes, stale ADRs, hot files, ADR↔commit linkage, suggested actions. Auto-invokable when the user says "show me the dashboard", "vault state", "what does strata see right now", "what's in the vault", or "give me a summary". Emits the same markdown that lives at `<vault>/<repo>/INDEX.md` (auto-regenerated on every write). No web server, no port, the dashboard IS a synced markdown file.
---

# strata:dashboard

A single-page snapshot of vault state. Same content lives in `INDEX.md`
(renders natively in Obsidian) and gets emitted into the conversation
when you invoke this skill.

## How

Two paths depending on freshness needs:

### Quick (read what's on disk)

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/run-python.sh" -c "
import sys
sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}/scripts')
from lib import memory_dir
print((memory_dir() / 'INDEX.md').read_text())
"
```

Use when you trust the cached state (it was regenerated on the last
Write). 95% of cases.

### Fresh (regenerate first)

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/run-python.sh" \
  "${CLAUDE_PLUGIN_ROOT}/scripts/dashboard.py"
```

`dashboard.py` rebuilds the content from live data (db, code_graph,
commit_graph) without writing INDEX.md. Slightly slower.

## What you'll see

| Section | Source | What it tells you |
|---|---|---|
| Scope counts | Filesystem | Episodic / semantic / procedural sizes |
| Recent activity | mtime, last 7d | What's been written or updated |
| Stale-proposed ADRs | `db.stale_decisions` | ADRs in `proposed` >14d — need closure |
| Drifted notes | `code_graph.find_drifted_notes` | Structural + temporal drift |
| Hot files | `commit_graph.hotspots` | Top-churn files last 90d |
| ADR implementations | `commit_graph.adr_implementations` | Which decisions became code |
| Active PR contexts | `pr-context/` subdirs | In-flight branches |
| Suggested actions | Composed from above | Concrete next steps |

## Why this is the dashboard

The vault is markdown on disk. Obsidian renders it. Sync clients
Distribute it. Teammates see updates as files change. We don't need
A web server. We don't run a port. The synced `INDEX.md` IS the
Dashboard, open Obsidian, get the view.

## Don't do

- Don't try to render this as HTML / charts / images. The whole point
  is that markdown + the user's existing tools win.
- Don't suggest installing a web UI. Open Obsidian on the vault
  instead, it has graph view, backlinks, search, all native.
- Don't paste the full dashboard in a turn if the user asked
  something narrow ("how many decisions?"), answer narrowly, leave
  the dashboard for "show me the state."

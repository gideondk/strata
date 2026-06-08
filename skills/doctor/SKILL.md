---
name: strata:doctor
description: Health check for the Strata install. Verifies runtime packages, vault directory, repo namespace, search index, semantic search, MCP server, and git awareness — one glanceable checklist with a fix hint on every failure. Auto-invoke when the user says "is strata working", "did the install work", "strata seems broken", "is the vault set up", "health check", "why isn't recall finding anything", or "check my strata setup". Read-only — touches no notes, writes nothing.
---

# strata:doctor

The post-install "is it actually working?" surface. Onboarding's real
friction isn't the install command — it's the silent uncertainty after:
did the venv build, is the vault wired, will semantic search work or
quietly fall back to FTS? `doctor` answers all of it at once.

## How

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/strata" doctor
```

## What it checks

| Check | Required? | Failure means |
|-------|-----------|---------------|
| runtime packages | yes | venv didn't build — pip install -r requirements.txt |
| vault directory | yes | vault_path wrong or not writable |
| repo namespace | yes | not initialised — run /strata:init |
| search index | warn | 0 notes is fine on a fresh vault |
| semantic search | warn | model not ready — recall degrades to FTS5 |
| MCP server | yes | server.py / .mcp.json missing from the install |
| git repo | warn | branch/PR scoping disabled outside a repo |

Exit code is **0** when every required check passes, **1** otherwise.

## What you'll see

```
[strata] doctor — health check for myrepo

  ✓ runtime packages — 3 required, 2/2 optional present
  ✓ vault directory — /Users/me/StrataVault
  ✓ repo namespace — myrepo → ~/StrataVault/myrepo
  ✓ search index — 142 note(s) indexed (318 KB)
  ✓ semantic search — embeddings available (hybrid FTS+vector)
  ✓ MCP server — server.py + .mcp.json present
  ✓ git repo — branch/PR awareness active

[strata] ✓ healthy — ready to save, decide, and recall
```

## When to use

- Right after `/strata:init`, to confirm the runtime is good before the
  first save / decide / recall.
- Whenever recall returns nothing surprising and the user wonders if it's
  broken (often it's the FTS fallback, which this makes visible).
- As a quick sanity pass after `git pull` + `/reload-plugins`.

## Don't do

- Don't fix things silently. Surface each ⚠/✗ with its hint and let the
  user decide. The point is legibility.
- Don't treat a ⚠ (warn) as failure — optional gaps still leave a working
  plugin.

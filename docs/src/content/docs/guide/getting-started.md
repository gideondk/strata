---
title: Getting started
description: "Five minutes to a working vault. We'll install Strata, initialise a project, save the first note, and watch it surface in the next session"
---

Five minutes to a working vault. We'll install Strata, initialise a project, save the first note, and watch it surface in the next session.

## Install

In Claude Code:

```bash
/plugin marketplace add https://github.com/ceracare/strata
/plugin install strata@strata
/plugin reload
```

The plugin ships a small Python wrapper that auto-creates a `.venv/` and installs runtime deps on first run. No global Python state, no system packages touched.

## Initialise the vault

From any git repo:

```bash
/strata:init
```

You'll be prompted for a vault path (default `~/StrataVault`). The plugin creates `<vault>/<repo-name>/` with the four scopes (`domain/`, `decisions/`, `lessons/`, `pr-context/`). Each gets a brief README for human browsing.

```text
~/StrataVault/myrepo/
├── decisions/
│   └── README.md
├── domain/
│   └── README.md
├── lessons/
│   └── README.md
├── pr-context/
└── INDEX.md
```

The repo name comes from `git remote.origin.url` (or the directory name as fallback). Multiple repos share one vault, namespaced by folder.

## Save your first note

Make a branch and start work. After ~30 minutes Strata's Stop hook will nudge you:

```text
💭 Strata: 30+ min on `feat/auth-rewrite` without a saved note.
   Consider `strata:save` with a short topic + 3-5 bullets covering
   what was done, decided, and left open.
```

Or invoke directly:

```text
/strata:save token-rotation-design
```

Claude will draft a note based on what you've been working on and ask you to confirm. The result lands in `<vault>/myrepo/pr-context/feat-auth-rewrite/YYYY-MM-DD-HHMM--<initials>--token-rotation-design.md` with structured frontmatter:

```yaml
---
branch: feat/auth-rewrite
kind: session
author: Gideon de Kok
topic: token-rotation-design
created: 2026-05-24-1030
---
```

## Watch it come back

Start a new Claude Code session. The SessionStart primer surfaces what Strata knows:

```text
### Strata memory
_5 decisions  ·  12 domain notes  ·  3 lessons  ·  2 pr-context (feat-auth-rewrite)_
_recent: token-rotation-design (today), ...

### Code graph (Graphify)
_built 2h ago  ·  348 nodes  ·  1,204 edges_
_top hubs: OrderAggregate, OrderRouter, ServiceBase, ...
```

When you ask a question that overlaps the vault (*"what's the token rotation approach?"*), Claude calls `memory_search` via MCP and finds the note. No `/find` invocation needed.

## What to do next

- Capture **decisions** as you make them: `/strata:decide "Use Postgres for tenant data"`
- Define **domain terms** when conventions crystallise: `/strata:domain order-aggregate`
- Run `/strata:bootstrap` once if you have existing planning docs to migrate ([bootstrap guide](/guide/bootstrap/))
- Install [Graphify](https://graphifylabs.ai) for code-graph awareness ([code graph guide](/guide/code-graph/))

The vault grows as you work. There's no upfront ceremony. Write when something deserves to survive the conversation.

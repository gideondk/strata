---
title: Strata for teams
description: Strata is useful for a single developer first; the team layer adds shared, branch-aware, auditable memory. What it is, and honestly what it isn't yet.
---

Strata earns its keep for a **single developer** first — it remembers your
decisions, domain rules, and runbooks so you stop re-explaining them every
session. You do not need a team to get value. Everything on this page is the
*layer on top* for when more than one person shares a codebase.

## What the team layer adds

- **A shared vault.** Point everyone's plugin at the same synced folder and the
  same decisions, domain notes, and lessons are there for every teammate's
  Claude session. No copy-paste, no "ask the person who knows".
- **Branch- and PR-aware context.** Per-branch working notes travel with the
  branch; when a teammate switches to it, their session primes on what was in
  flight. Notes archive when the PR merges.
- **Provenance on every note.** Author and timestamps land in frontmatter;
  decisions carry their chosen option and rejected alternatives; supersession is
  an explicit, walkable chain. Six weeks later "why did we *not* do X?" has an
  answer with a file path, not a Slack search.
- **A trust boundary that matters more with a team.** Durable memory changes
  only through a human-typed command — never silently over MCP (a CI test keeps
  it that way). At team scale that's the difference between one wrong note and
  *everyone's* next session inheriting it. See the repo's
  [`SECURITY.md`](https://github.com/gideondk/strata/blob/main/SECURITY.md) for
  the regulated-codebase story.
- **Supersession-aware recall, benchmarked.** When a current decision and the
  one it replaced both match a query, recall puts the current one on top. The
  repo ships the benchmark that shows it (`eval/temporal/`: paired McNemar,
  exact p ≈ 0.0005 on a 19-case set). It proves the mechanism works; how often
  that clash comes up in a real vault is still an open question.

## Team-scoped distribution

The marketplace repo is meant to be forked and pinned, so a team installs a
known version:

```text
/plugin marketplace add https://github.com/<your-org>/strata
/plugin install strata@strata
```

Commit a shared `.claude/settings.json` (see `examples/`) so everyone on the
repo gets the plugin enabled with the same vault path and lint presets.

## What it is NOT (yet)

Being straight about the edges, because a team tool that overpromises here is
worse than one that doesn't:

- **Sync is bring-your-own.** Strata does not ship a multi-writer merge engine.
  It is sync-mechanism agnostic — point the vault at Obsidian Sync, Syncthing,
  iCloud, Dropbox, or a private git repo and use that tool's conflict handling.
  Plain markdown keeps conflicts human-readable, but concurrent edits to the
  *same note* are resolved by your sync layer, not by Strata.
- **Recall telemetry is per-machine.** The usage ledger is local, so
  "dead-weight" detection reflects *your* recalls, not the team's. That's a
  deliberate privacy choice, not a synced feature.
- **No accounts, no server, no presence.** There is nothing to log into. The
  "team" is whoever shares the folder.

If your team needs hard multi-writer guarantees or a hosted control plane,
Strata isn't that today, and won't pretend to be.

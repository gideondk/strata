<p align="center">
  <img src="docs/public/favicon.svg" width="56" alt="Strata">
</p>

<h1 align="center">Strata</h1>

<p align="center"><em>Local-first memory for Claude Code.</em></p>

<p align="center">
  <a href="https://github.com/gideondk/strata/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/gideondk/strata/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://github.com/gideondk/strata/blob/main/LICENSE"><img alt="License: MPL-2.0" src="https://img.shields.io/badge/license-MPL--2.0-blue"></a>
  <img alt="Python ≥ 3.10" src="https://img.shields.io/badge/python-3.10%2B-blue">
  <img alt="No network" src="https://img.shields.io/badge/network-zero%20calls-success">
</p>

<p align="center">
  <a href="https://gideondk.github.io/strata/">Documentation</a> ·
  <a href="https://gideondk.github.io/strata/guide/getting-started/">Getting started</a> ·
  <a href="https://gideondk.github.io/strata/guide/faq/">FAQ</a>
</p>

---

Every Claude Code session starts cold.

You sit down on Monday, open a branch, and find yourself explaining the same things you explained on Friday. The decision your team made about Postgres last quarter. The reason `OrderPriced` fires before `OrderConfirmed`. The convention that domain events are named in the past tense. The bug you almost shipped two weeks ago and how you caught it.

If you're lucky, you remember to copy-paste a context dump. If you're not, Claude guesses, and sometimes the guess is wrong in a way that looks confidently right. By Wednesday, you've re-explained the same constraints three times across three different sessions.

We built Strata because the loss compounds. The decisions, the domain vocabulary, the post-incident lessons, they're all sitting in your head, in old Slack threads, in PR descriptions nobody re-reads. None of it reaches Claude unless you carry it there by hand.

## Why one big context file doesn't work

The obvious fix is a single context file you prepend to every prompt. It breaks down fast. It grows until it eats the context window, and it answers in the wrong shape: you ask how to add a new service and get a paragraph defining what a service is.

A vector database doesn't really fix that. Semantic search ranks by embedding distance, so it tends to return whatever pattern-matches most recently — often a stale note that's since been corrected, handed back with complete confidence.

The deeper issue is that memory isn't one kind of thing. A decision you make once and a recipe you follow every week age at different rates and need to be looked up in different ways. Put them in the same bucket and recall gets worse, not better.

## What Strata does

Strata splits memory into three kinds and keeps them on separate retrieval paths, all in plain markdown on your disk:

- **Episodic** — what happened on this branch. Per-PR working notes. Archives when the PR merges.
- **Semantic** — what things mean and what you've chosen. Vocabulary, invariants, ADRs. Long-lived; superseded explicitly when it changes.
- **Procedural** — how you do things here. Recipes, runbooks. Stable until the recipe changes.

When you ask Claude something, the read path that matches the *shape* of your question runs. Ask "what's our token rotation approach?" and you get the ADR, not a Slack screenshot from April. Ask "how do I add a new service?" and you get the recipe, not the definition.

You don't have to remember any of this. You write notes when something deserves to survive the conversation, and Claude finds them on its own through the MCP layer. The mechanism is invisible until you want to look at it; then the citations are right there in the answer.

## How it feels in practice

You make a decision in conversation. You say "let's go with the section-at-once edit pattern". Claude offers to record it; you accept. A 40-line ADR lands in `decisions/` with the context, the chosen option, the alternatives you rejected, and the consequences.

Six weeks later a teammate switches to your branch. Their Claude session reads the per-branch notes you saved and primes itself with what you were in the middle of. They ask "why didn't we use per-field PUTs?" and Claude pulls the rejected-alternatives section straight from your ADR, file path included. Nobody digs through Slack, and nobody has to interrupt you to ask.

A month after that, your team refactors and a new ADR supersedes the old one. The old file stays in the vault, marked `status: superseded`, with a forward link to its replacement. You can still walk the chain — the old reasoning is preserved without pretending to be current.

## Local-first, by design

The vault lives on your disk. Default location is `~/StrataVault`. Inside, one subfolder per repo, namespaced by your git remote. Inside that, one subfolder per scope. Plain markdown with YAML frontmatter.

The search index is a local SQLite FTS5 database plus an on-device fastembed model for semantic recall. Nothing in the runtime path touches the network, there's no telemetry, and you can grep the source to check.

Sync your vault however you already sync things: Obsidian Sync, Syncthing, iCloud, Dropbox, a private git repo. Strata doesn't care. The format is text; everything else is your choice.

## Install

In any Claude Code session:

```text
/plugin marketplace add https://github.com/gideondk/strata
/plugin install strata@strata
/strata:init
```

Requirements: Python 3.10 or newer on `PATH`. A `.venv/` is created inside the plugin directory on first run with two pinned dependencies (`mcp`, `python-frontmatter`). Nothing global, nothing system-wide.

Full setup notes, team-config patterns, pre-push lint hook: [`INSTALL.md`](./INSTALL.md).

## Read the docs

The site at **[gideondk.github.io/strata](https://gideondk.github.io/strata/)** covers:

- [What is Strata](https://gideondk.github.io/strata/guide/what-is-strata/) — plain-English intro, no jargon
- [Getting started](https://gideondk.github.io/strata/guide/getting-started/) — five-minute walkthrough
- [Memory architecture](https://gideondk.github.io/strata/guide/memory-architecture/) — why three kinds
- [Skills](https://gideondk.github.io/strata/guide/skills/) — every slash command
- [MCP tools](https://gideondk.github.io/strata/guide/mcp-tools/) — every read tool exposed to Claude
- [Bootstrap](https://gideondk.github.io/strata/guide/bootstrap/) — one-shot migration of existing planning docs
- [Correcting the vault](https://gideondk.github.io/strata/guide/correcting/) — fix, invalidate, supersede, forget
- [Architecture](https://gideondk.github.io/strata/guide/architecture/) — how the pieces fit
- [FAQ](https://gideondk.github.io/strata/guide/faq/)

## What's intentionally not here

- **No write tools over MCP.** Writes go through user-typed slash commands. Prompt injection can't mutate memory silently.
- **No bundled Obsidian MCP.** The vault is plain markdown; pair with whichever Obsidian server you prefer. See [`OBSIDIAN.md`](./OBSIDIAN.md).
- **No background monitors.** Hooks fire on explicit events; everything else is on-demand.
- **No chat-history import.** Bulk-importing chats into shared memory is a PII risk and a search-noise multiplier.
- **No telemetry, no network.** Greppable in the source.

## License

[MPL-2.0](./LICENSE). You can use Strata in commercial and proprietary products without licensing your own code, but any modifications you make to Strata's source files must be shared back under the same license.

## Contributing

Issues and PRs welcome. Keep it stdlib-leaning, keep the threat model intact, and put new functionality behind opt-in flags rather than enabling it by default.

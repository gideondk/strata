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

## The shape of the problem

The first instinct is to dump everything into one long context file and prepend it to every prompt. That fails for two reasons. The file gets too big and burns the context window. And it returns the wrong shape when you ask a question: you wanted a recipe for adding a new service, you got a definition of what a service is.

The second instinct is to use a vector database and hope semantic search figures it out. That fails differently. Vector search collapses everything to "similar by embedding distance" and gives you the most recent thing that pattern-matches, which is often a stale snapshot of something that has since been corrected.

The real problem is that memory isn't one kind of thing. Cognitive science has names for the kinds, and the kinds have different lifetimes, different retrieval shapes, and different audit rules. Cramming them into one bucket makes recall worse, not better.

## What Strata does

Strata splits memory into three kinds and keeps them on separate retrieval paths, all in plain markdown on your disk:

- **Episodic** — what happened on this branch. Per-PR working notes. Archives when the PR merges.
- **Semantic** — what things mean and what you've chosen. Vocabulary, invariants, ADRs. Long-lived; superseded explicitly when it changes.
- **Procedural** — how you do things here. Recipes, runbooks. Stable until the recipe changes.

When you ask Claude something, the read path that matches the *shape* of your question runs. Ask "what's our token rotation approach?" and you get the ADR, not a Slack screenshot from April. Ask "how do I add a new service?" and you get the recipe, not the definition.

You don't have to remember any of this. You write notes when something deserves to survive the conversation, and Claude finds them on its own through the MCP layer. The mechanism is invisible until you want to look at it; then the citations are right there in the answer.

## How it feels in practice

You make a decision in conversation. You say "let's go with the section-at-once edit pattern". Claude offers to record it; you accept. A 40-line ADR lands in `decisions/` with the context, the chosen option, the alternatives you rejected, and the consequences.

Six weeks later a teammate switches to your branch. Their Claude session reads the per-branch notes you saved and primes itself with what you were in the middle of. They ask "why didn't we use per-field PUTs?" and Claude pulls the alternatives section from your ADR, with the file path. No archaeology, no Slack scrolling, no asking you.

A month after that, your team refactors. The old ADR gets superseded by a new one. The old file stays in the vault, marked `status: superseded`, with a forward link to its replacement. The chain is queryable. Nothing gets lost; nothing gets repeated.

## Local-first, by design

The vault lives on your disk. Default location is `~/StrataVault`. Inside, one subfolder per repo, namespaced by your git remote. Inside that, one subfolder per scope. Plain markdown with YAML frontmatter.

The search index is a local SQLite FTS5 database plus an on-device fastembed model for semantic recall. No network calls in the runtime path. No telemetry. No analytics. Greppable in the source.

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

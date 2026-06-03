<p align="center">
  <img src="docs/public/favicon.svg" width="56" alt="Strata">
</p>

<h1 align="center">Strata</h1>

<p align="center"><em>Typed, local-first memory for Claude Code.</em></p>

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

Strata gives Claude Code structured memory: the decisions you've made, the domain rules you follow, the runbooks you reach for. They're kept as plain markdown on your disk, each on its own retrieval path. Claude reads them on its own through the MCP layer, so you stop pasting context dumps and you stop hand-maintaining a giant prompt file.

The usual alternatives make recall worse. One big context file blows the window and answers in the wrong shape: you ask how to add a service and get a paragraph defining what a service is. A vector database returns whatever pattern-matches most recently, which is often a stale note that's since been corrected, handed back with full confidence. Strata writes only what you confirm and retires old notes explicitly, so what comes back is current.

## Three kinds of memory

Recall works because memory isn't one thing. A decision you make once ages differently from a runbook you follow every week, so Strata keeps them apart:

- **Episodic** — what happened on this branch. Per-PR working notes, archived when the PR merges.
- **Semantic** — what things mean and what you've chosen. Vocabulary, invariants, ADRs. Long-lived; superseded explicitly when it changes.
- **Procedural** — how you do things here. Recipes and runbooks. Stable until the recipe changes.

The path that matches the *shape* of your question runs. Ask "what's our token-rotation approach?" and you get the ADR, not a Slack screenshot from April. Ask "how do I add a service?" and you get the runbook, not the definition. You write a note when something deserves to outlive the conversation; Claude finds it later, file path right there in the answer.

## How it feels in practice

You make a decision in conversation. You say "let's go with the section-at-once edit pattern". Claude offers to record it; you accept. A 40-line ADR lands in `decisions/` with the context, the chosen option, the alternatives you rejected, and the consequences.

Six weeks later a teammate switches to your branch. Their Claude session reads the per-branch notes you saved and primes itself with what you were in the middle of. They ask "why didn't we use per-field PUTs?" and Claude pulls the rejected-alternatives section straight from your ADR, file path included. Nobody digs through Slack, and nobody has to interrupt you to ask.

A month after that, your team refactors and a new ADR supersedes the old one. The old file stays in the vault, marked `status: superseded`, with a forward link to its replacement. You can still walk the chain: the old reasoning is preserved without pretending to be current.

## Does the supersession actually work?

Plenty of tools claim the current note beats the stale one. Here's Strata's, measured. `scripts/eval_temporal.py` builds a throwaway vault and runs recall over the same cases twice: once with supersession demotion off, once with it on. It checks whether the current note outranks the superseded twin that a query also matches.

```
stale-suppression:  off  7/19   →   on  19/19      (paired McNemar: 12–0, exact p ≈ 0.0005)
current-recall@k:   19/19 either way; demoting the stale note costs nothing
```

Each case runs both ways, so it's a paired test you can rerun, not a number you have to take on faith:

```text
bin/run-python.sh scripts/eval_temporal.py
```

It proves the mechanism on a hand-built, leakage-checked set of 19 cases. What it doesn't prove: how often the stale-versus-current clash actually shows up in a real vault, and 19 is a small set. The cases, the leakage check, and the caveats are in [`eval/temporal/`](./eval/temporal/). No "beats a vector database" line here, and there won't be one until I can measure how common that clash really is.

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

Requirements: Python 3.10 or newer on `PATH`. A `.venv/` is created inside the plugin directory on first run with its pinned runtime dependencies (`mcp`, `python-frontmatter`, `pathspec`; `fastembed` is optional and only adds semantic search). Nothing global, nothing system-wide.

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

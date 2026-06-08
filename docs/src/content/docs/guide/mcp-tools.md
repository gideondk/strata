---
title: MCP tools
description: "Strata ships an MCP server (stdio transport) that exposes the vault and code graph as structured tools to Claude. Claude calls these automatically during conversations; you rarely invoke them yourself."
---

Strata ships an MCP server (stdio transport) that exposes the vault and code graph as structured tools to Claude. Claude calls these automatically during conversations. You rarely invoke them yourself.

All tools are **read-only**. Writes happen through visible bash invocations (skills running scripts) so the user sees state changes. The MCP surface is consultation only.

## The registered surface: seven tools

The server registers exactly seven tools, and every one of them is always present in Claude's palette. There is no second tier of hidden tools to "fall back" to. Retrieval used to be spread across a dozen entry points (`memory_search`, `memory_get`, `memory_semantic_search`, `memory_insights`, `domain_lookup`, `recent_decisions`, `recent_lessons`, `decision_chain`, and friends). Those have all been folded into one tool, `recall`. They are no longer registered and cannot be called directly.

- `recall` — the single retrieval entry point. Search, lookup, neighbour walks, and synthesis-ready context all come out of here.
- `memory_status` — vault scope counts and the FTS database path.
- `current_pr` — the current branch's PR via `gh`.
- `code_graph_status` — code-graph node/edge counts and age.
- `plan_status` — cross-check a planning subdir against git and the graph.
- `code_map` — a token-budgeted projection of the code graph.
- `bootstrap_scan` — enumerate migration candidates.

For heavy synthesis there's also the `strata:memory-recall` subagent, which calls `recall` for you in its own context window and hands back only a summary. More on that below.

## recall: the one retrieval tool

`recall(query, layer?, budget?, scope?, since?, limit?)`

One call answers "what does the vault know about X". It ranks matches, then expands them according to the layer you ask for.

```text
recall(query="token rotation", scope="decisions")
```

### Layers

The `layer` argument controls how much you get back, so you can pay only for the depth you need:

- **Layer 1** — a compact ranked index. Titles, scopes, and short snippets. The default starting point.
- **Layer 2** — layer 1 plus the wikilink neighbours of the top hits, so you see what each note connects to without a second call.
- **Layer 3** — the full body of the top hit, for when you've found the note you want and need to read it.

A typical path is layer 1 to see what's there, then layer 3 on the note that matters.

### Scopes

`scope` narrows the search to one slice of the vault. The enum is `all` (the default), `decisions`, `domain`, `lessons`, `procedural`, `propositions`, and `pr-context`.

```text
recall(query="how do we handle authentication", scope="domain")
```

### Filters and ranking

- `since` filters to notes touched after a date, which is how you ask "what changed recently" without a separate recency tool.
- `budget` caps the token spend of the result.
- `limit` caps the number of hits.
- Invalidated notes and machine-generated `auto` notes are excluded by default; you're reading curated memory, not raw capture.
- Superseded and deprecated notes are demoted rather than dropped, so a current decision outranks the one it replaced but the old one is still findable.

## Heavy synthesis: the memory-recall subagent

When a question needs several reads stitched together, Claude can hand it to the `strata:memory-recall` subagent instead of running everything in the main conversation. The subagent has only `recall` and `Read` available to it. It works the query in its own isolated context and returns a curated summary, so the main session window doesn't fill up with raw tool-result text.

Use `recall` directly for a one-shot lookup. Let the subagent take over for cross-note synthesis.

## Internal helpers, not MCP tools

A few capabilities from the old surface still exist, but as internal machinery rather than tools an MCP client can call:

- **Stale decisions and orphan notes** — surfaced by `/strata:review`, which reports proposed ADRs that have gone stale and notes that link to nothing. There's no `stale_decisions` or `orphan_notes` tool to invoke.
- **Supersession chains and the wikilink graph** — reachable through `recall` at layer 2, which walks a note's neighbours. There's no separate `decision_chain` or `memory_graph` tool.

## current_pr

`current_pr()`

Resolves the current branch's PR via `gh pr view`. Returns title, body, author, and review state when available. Skipped when `gh` isn't installed or there's no PR for the branch.

## memory_status

`memory_status()`

Vault scope counts plus the FTS database path and which repo namespace is active. Skills lean on it internally; for example bootstrap reads `vault_dir` from here before dispatching workers.

## plan_status

`plan_status(subdir)`

Cross-check a planning subdir's claims against git history and the code graph. For every path or symbol mentioned, it reports commits, existence, and resolution, then outputs a completion percentage and a verdict hint.

The bootstrap worker uses it to classify: high-evidence plans become accepted ADRs, low-evidence ones become lessons.

## bootstrap_scan

`bootstrap_scan(unprocessed?, bucket?, verify?, min_freshness?, max_size?, max_age_days?)`

Enumerate markdown candidates for migration. Returns metadata (size, age bucket, freshness score) and a `dispatch_groups` map keyed by parent directory. `/strata:bootstrap` uses it to dispatch one worker per group.

Read-only. The actual marking step (`--mark <path>`) stays a visible bash call.

## Code graph

### `code_graph_status()`

Summary of the graph: node/edge counts, languages, age. Returns "not available" if Graphify hasn't been run.

### `code_map(focus?, budget?, include_docs?)`

Token-budgeted projection of the graph. The top tier carries full signatures, the middle tier carries file context, the low tier carries the label only.

```text
code_map(focus=["OrderAggregate"], budget=1500)
```

See [code graph guide](../code-graph/) for the full design.

## Resources surface

Beyond tools, Strata registers the vault as MCP **resources** with URIs like `strata://decisions/2026-05-24-foo.md`. Clients that support resources get a browseable view. Clients that only use tools reach the same notes through `recall`.

## Read-only discipline

The server's header says it plainly:

> All tools are READ-ONLY. Writes happen through user-typed slash commands so that the Bash invocations are visible to the user.

The boundary is firm. Even `bootstrap_scan` (which enumerates) is read-only; the `--mark` write that updates state runs as a visible bash call from the worker, not through the MCP. This keeps the surface honest: anything that changes the vault appears in your terminal log.

---

Next: [Architecture](../architecture/) — how the pieces fit, and what to read when you want to extend.

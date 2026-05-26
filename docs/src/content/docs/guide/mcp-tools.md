---
title: MCP tools
description: "Strata ships an MCP server (stdio transport) that exposes the vault and code graph as structured tools to Claude. Claude calls these automatically during conver"
---

Strata ships an MCP server (stdio transport) that exposes the vault and code graph as structured tools to Claude. Claude calls these automatically during conversations. You rarely invoke them yourself.

All tools are **read-only**. Writes happen through visible bash invocations (skills running scripts) so the user sees state changes. The MCP surface is consultation only.

## Two surfaces: ambient vs. on-demand

Strata splits its tools across two layers to keep every conversation cheap:

- **Ambient surface (7 tools)** — always present in Claude's tool palette. Small set, low context cost. Includes `recall` (the unified search entry point), `memory_status`, `current_pr`, `code_graph_status`, `code_map`, `plan_status`, `bootstrap_scan`.
- **On-demand surface (12 tools)** — only invoked through the `strata:memory-recall` subagent. Heavier reads (`memory_search`, `memory_get`, `decision_chain`, `memory_insights`, etc.) happen in isolated subagent context; only a curated summary returns to the main conversation. This keeps the main session window from filling with tool-result text.

The tools documented below are the **full catalogue** — both surfaces. Anything not in the ambient seven is reachable via the recall agent (Claude dispatches it automatically when you ask synthesis questions). For one-shot lookups, prefer `recall` directly; for cross-note synthesis, the agent.

## Search & retrieve

### `memory_search(query, scope?, branch?, limit?, cursor?)`

FTS5 search across the vault. Supports paginated cursors and scope filters.

```text
memory_search(query="token rotation", scope="decisions")
```

Filters invalidated notes by default. Pass `include_invalidated=true` to see them (rarely needed).

### `memory_semantic_search(query, scope?, limit?)`

Vector search via local CPU embeddings (fastembed, BAAI/bge-small-en-v1.5). Finds conceptually similar notes when FTS misses keyword matches.

```text
memory_semantic_search(query="how do we handle authentication")
# Finds OAuth + JWT notes even when they don't share the word "authentication"
```

Optional layer. If fastembed isn't installed, the tool reports unavailable and falls back to FTS for `memory_insights`.

### `memory_get(path)`

Retrieve one note's full body + frontmatter. Path is vault-relative.

### `memory_insights(topic, limit_per_section?)`

Aggregate query. Combines FTS matches, recent decisions, domain notes, and (if Graphify is installed) code-graph symbols into a single ranked answer.

Best for open-ended "what does the vault know about X" questions where you want everything relevant in one call.

## Navigation

### `recent_decisions(limit?)`

List the N most recently created ADRs.

### `recent_lessons(limit?)`

List the N most recently created lessons.

### `domain_lookup(term)`

Find domain notes matching a term. Lighter than `memory_search` for "what does X mean here?" questions.

### `current_pr()`

Resolve the current branch's PR via `gh pr view`. Returns PR title, body, author, and review state when available. Skipped when `gh` isn't installed or no PR exists.

### `pr_context_for_branch(branch?)`

List notes in `pr-context/<branch-slug>/`. Defaults to current branch.

## Lifecycle / structure

### `memory_status()`

Vault paths + scope counts + which repo namespace is active. Used internally by skills (e.g. bootstrap dispatches workers with `vault_dir` from this).

### `decision_chain(path)`

Walks the supersession chain for an ADR. Both directions: predecessors and successors. Returns the full lineage.

### `memory_graph(path)`

Returns the wikilink graph for one note: what it references, what references it, and (when Graphify is installed) which unresolved wikilinks bridge to code-graph nodes.

### `stale_decisions(threshold_days?)`

ADRs with `status: proposed` older than N days. The vault's "your homework" list.

### `orphan_notes()`

Notes nothing links to and which link to nothing. Often correction candidates.

## Bootstrap

### `bootstrap_scan(unprocessed?, bucket?, verify?, min_freshness?, max_size?, max_age_days?)`

Enumerate markdown candidates for migration. Returns metadata (size, age bucket, freshness score) and a `dispatch_groups` map keyed by parent directory. Used by `/strata:bootstrap` to dispatch one worker per group.

Read-only; the actual marking step (`--mark <path>`) is still a visible bash call.

### `plan_status(subdir)`

Cross-check a planning subdir's claims against git history + code graph. For every path / symbol mentioned, reports commits, existence, resolution. Outputs completion % + verdict hint.

Used by `bootstrap-worker` to classify (high-evidence plans become accepted ADRs; low-evidence become lessons).

## Code graph

### `code_graph_status()`

Summary of the graph: node/edge counts, languages, age. Returns "not available" if Graphify hasn't been run.

### `code_map(focus?, budget?, include_docs?)`

The headline tool. Token-budgeted projection of the graph. Top tier carries full signatures. Middle tier carries file context. Low tier carries label only.

```text
code_map(focus=["OrderAggregate"], budget=1500)
```

See [code graph guide](/guide/code-graph/) for the full design.

## Resources surface

Beyond tools, Strata registers the vault as MCP **resources** with URIs like `strata://decisions/2026-05-24-foo.md`. Clients that support resources get a browseable view; clients that only use tools fall back to `memory_search` / `memory_get`.

## Read-only discipline

The server's header says it plainly:

> All tools are READ-ONLY. Writes happen through user-typed slash commands so that the Bash invocations are visible to the user.

The boundary is firm. Even `bootstrap_scan` (which enumerates) is read-only; the `--mark` write that updates state runs as a visible bash call from the worker, not through the MCP. This keeps the surface honest: anything that changes the vault appears in your terminal log.

---

Next: [Architecture](/guide/architecture/) — how the pieces fit, and what to read when you want to extend.

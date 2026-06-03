---
title: Code graph
description: "Graphify integration. The vault becomes code-aware: notes verify symbols, recall projects compressed structure, drift detection flags stale claims."
---

[Graphify](https://graphifylabs.ai) builds an AST graph of your repo.
Install it alongside Strata and the vault becomes code-aware. Notes
verify their symbol references. Recall returns ranked structure
projections. Claude answers *"what does this aggregate emit"* from a
500-token compressed view, not by grepping 200 files.

This is where the token economy pays off, not just documentation.

## Install Graphify

```bash
brew install graphifylabs/tap/graphify
# or the official installer
```

Strata doesn't depend on Graphify's Python. We parse the JSON it emits.

## Build the graph

```bash
/strata:graphify
```

Wraps `graphify update .`. AST-only path. No LLM key needed. Output
lands at `<repo>/graphify-out/graph.json`. Rebuild after material
code changes; the SessionStart primer tells you when it's stale.

## What Strata does with the graph

Nine integration points.

### Build and refresh

- `/strata:graphify` builds or refreshes the graph.

### Session start

- The primer surfaces top god nodes plus graph age. When stale, it
  leads with a directive rebuild prompt. `code_map` and freshness
  scores both read the graph, so outdated cascades.

### Bootstrap

- `bootstrap-scan --verify` extracts backtick symbols from each
  candidate, resolves them against the graph, contributes to the
  freshness percentage.
- `plan_correlate` checks every symbol in a planning subdir against
  the graph. Resolution count drives the completion estimate.
- `bootstrap-worker` calls `code_map` on top symbols in its group
  before classifying. Informs wikilink choices.

### On-demand

- `code_map` (MCP tool): aider-style token-budgeted projection. Top
  tier carries file and line and refs count. Middle tier carries file
  only. Bottom tier carries label only. The `focus` parameter
  promotes one-hop neighbours of named symbols into the top tier.
- `memory_graph` (MCP tool): when a vault wikilink doesn't resolve to
  another note, attempts to bridge to a graph node. Surfaces as
  `graphify:NodeName`.

### Write protection

- `new-decision.py --strict-symbols` refuses to write an ADR when
  backtick identifiers don't resolve. Catches typos and stale
  references before they enter the vault.

### Durable cross-reference

- `code_refs:` frontmatter convention. Each note lists the verified
  symbols it touches. Names only, no projection embedded. Future
  queries call `code_map(focus=code_refs)` fresh so the projection
  stays current as code moves.

### Health check

- `/strata:review` flags 🔴 STALE when `graph.json` is more than 7
  days old or 20 commits behind HEAD.

## `code_map` in practice

The dynamic projection is what Claude actually calls during a
conversation. From any session:

```text
code_map(focus=["OrderAggregate"], budget=1500)

→ # Code map — focus: OrderAggregate
  _★ = focus symbol; neighbours of focus promoted into top tier._

  - `OrderAggregate`   — services/orders/OrderAggregate.cs:L7  (refs:14) ★
  - `.Place()`         — services/orders/OrderAggregate.cs:L42 (refs:3) ★
  - `.Confirm()`       — services/orders/OrderAggregate.cs:L67 (refs:3) ★
  - `.Cancel()`        — services/orders/OrderAggregate.cs:L91 (refs:2) ★
  - `OrderPlaced`      — services/orders/Events.cs:L8          (refs:9) ★
  - `OrderConfirmed`   — services/orders/Events.cs:L12         (refs:7) ★
  - `OrderRouter`      — services/orders/OrderRouter.cs:L18    (refs:4)
  - `IOrderRepository` — services/orders/Storage.cs:L11        (refs:6)
  ...
```

About 1.5KB of compressed structure. Without it, Claude greps every
`.cs` file mentioning `OrderAggregate`: easily 5 to 10KB of source.
With it, the answer fits in one tool call.

### Ranking

In-degree (how many things reference a node) as the PageRank proxy.
Cheap. As effective as full PageRank at the *find the hubs* job, per
[aider's empirical results](https://aider.chat/2023/10/22/repomap.html).
When `focus` is set, matched nodes and their one-hop neighbours rank
into the top tier regardless of global degree.

### Tier budget

- Top 10% of ranked nodes: full detail (file:line, refs count).
- Next 20%: file only.
- Bottom: label only.
- Cut at the token budget. Default 1000 tokens, roughly 4KB.

Pass `budget=2000` to widen or `budget=500` to tighten.

### Focus matching

Exact label match wins. Substring-on-id is the fallback. Only
triggers when nothing matched exactly. Without that gating, a focus
on `OrderAggregate` would drown in `OrderAggregateTests` and every
test fixture sharing the substring.

When focus matches nothing, output leads with `_no nodes matched
focus: ..._` and falls back to global hubs. You'll see the warning
and can retry with a different spelling.

## Staleness is a first-class signal

The code map is only as good as the graph it reads. When the graph
drifts behind HEAD:

```text
### Code graph (Graphify)
**⚠ graph is stale (47 commits since last build).**
Run `/strata:graphify` to refresh.
code_map / symbol resolution / freshness scores all read this graph.
```

Appears in the SessionStart primer before the regular stats. The
Stop hook also appends the staleness signal when relevant. Rebuild
is one command. Typically takes seconds.

---

Next: [Correcting the vault](../correcting/). Fix notes, mark them
invalidated, supersede ADRs.

---
title: Code graph
description: "Code-aware vault: notes verify symbols, recall projects compressed structure, drift detection flags stale claims. Works out of the box via tree-sitter; deeper with Graphify."
---

Strata's code-graph features work out of the box, then get deeper with
[Graphify](https://graphifylabs.ai) installed. Two tiers:

- **Coarse (tree-sitter)** — always available. Definitions (functions,
  classes, methods, structs, enums, interfaces) plus best-effort
  within-file call edges. Enough for `code_map`, symbol resolution, and
  `--strict-symbols` with zero setup.
- **Graphify (deep)** — cross-file and cross-service call resolution,
  complexity properties, LSP-resolved calls with confidence. Install it
  for the full projection quality.

Either way, the vault becomes code-aware: notes verify their symbol
references, recall returns ranked structure projections, and Claude
answers *"what does this aggregate emit"* from a 500-token compressed
view instead of grepping 200 files.

This is where the token economy pays off, not just documentation.

## Install Graphify (optional, deeper tier)

```bash
brew install graphifylabs/tap/graphify
# or the official installer
```

Strata doesn't depend on Graphify's Python. We parse the JSON it emits.
Without it, the coarse tree-sitter tier handles everything below — just
with flatter ranking (see [Coarse fallback](#coarse-fallback-tree-sitter)).

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
- `bootstrap-worker` has no MCP grant. It shells the bundled Strata
  scripts via `bin/run-python.sh` to project top symbols in its group
  before classifying. Informs wikilink choices.

### On-demand

- `code_map` (MCP tool): aider-style token-budgeted projection. Top
  tier carries file and line and refs count. Middle tier carries file
  only. Bottom tier carries label only. The `focus` parameter
  promotes one-hop neighbours of named symbols into the top tier.
- Wikilink-to-code bridging (internal, surfaced via `recall` layer 2):
  when a vault wikilink doesn't resolve to another note, Strata
  attempts to bridge to a graph node. Surfaces as `graphify:NodeName`.

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

## Coarse fallback (tree-sitter)

When Graphify isn't installed, Strata builds a coarse index from
[tree-sitter-language-pack](https://pypi.org/project/tree-sitter-language-pack/).
This is the default state on a fresh install — no extra setup required
for the features above to work.

**What you get:**

- Definitions across Python, C#, TypeScript/TSX, JavaScript, Go, Rust,
  Java, Kotlin, Ruby, Swift.
- Best-effort *within-file* call edges (a call resolves to an edge only
  when the callee is defined in the same file).
- `code_map` projection, symbol resolution, and `--strict-symbols`
  enforcement — all functional.
- Incremental rebuilds via per-file sha256, cached under
  `plugin_data_dir()/code_index.json`.

**What you don't get (Graphify's job):**

- Cross-file and cross-service call resolution. `code_map` ranking is
  flatter — in-degree reflects within-file calls only, not the true
  reference graph. Hubs still surface, but the signal is weaker.
- Complexity / hot-path properties (cyclomatic, loop depth).
- LSP-resolved calls with confidence scores.

The provenance is explicit. A coarse `code_map` leads with:

```text
_coarse (tree-sitter) — cross-file ranking limited.
Install Graphify for the full graph._
```

…and the SessionStart primer shows `Code graph (coarse, tree-sitter)`
instead of `Code graph (Graphify)` when serving from the fallback.

Grammars download on first use for each language (one-time, cached in
`~/.cache`). If the pack isn't installed at all, `doctor` warns and the
features need Graphify — same as before the fallback existed.

---

Next: [Correcting the vault](../correcting/). Fix notes, mark them
invalidated, supersede ADRs.

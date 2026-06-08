---
title: Concepts
description: "A short tour of the model. Two ideas drive everything: scopes (different kinds of knowledge live in different places) and branch awareness (PR-context separates from durable truth)."
---

A short tour of the model. Two ideas drive everything: **scopes** (different kinds of knowledge live in different places) and **branch awareness** (PR-context separates from durable truth).

## The vault

A folder on disk holding markdown notes. One vault may serve many repos:

```text
~/StrataVault/
├── myrepo/
│   ├── decisions/
│   ├── domain/
│   ├── lessons/
│   └── pr-context/
├── other-repo/
│   └── ...
└── _shared/
    └── domain/         # cross-repo conventions
```

The vault is plain markdown. Readable in any editor. Syncable with any tool. Durable when the plugin isn't running. Strata itself adds:

- A `.strata/` directory (per repo, in the project, not the vault) holding the SQLite FTS index and bootstrap state
- YAML frontmatter on every note (machine-readable metadata)
- Wikilink resolution between notes

## Scopes

### `domain/` — what is X here

Long-lived definitions. Vocabulary, invariants, conventions that survive multiple sprints.

```markdown
---
title: Order Aggregate
status: stable
code_refs: [OrderAggregate, OrderPlaced]
---

# Order Aggregate

One concept per file. An Order belongs to exactly one Customer. State
transitions: pending → confirmed → shipped → delivered (or cancelled
from any of the first three). Idempotency key: order ID + command type.
```

One concept per file, kebab-case filename. Use `[[wikilinks]]` to cross-reference.

### `decisions/` — chosen options with reasoning

ADRs in MADR-light format. Each file has Context, Decision, Alternatives, Consequences.

```markdown
---
title: Use Postgres for tenant data
status: accepted
date: 2026-05-24
supersedes: []
superseded_by: []
---

## Context
Multi-tenant data with row-level filtering. Read-heavy.

## Decision
Postgres with RLS. Rejected MySQL (weaker RLS), Cosmos (cost).

## Consequences
RLS performance ceiling is the constraint to watch.
```

Decisions support bidirectional supersession: a new ADR can `--supersedes` an older one, and the chain stays intact through re-indexing.

### `lessons/` — retrospective facts

Past-tense knowledge. "We tried X and it didn't work because Y." "After two weeks the rollout settled at Z." Date-prefixed filenames; not branch-scoped.

```markdown
---
title: Build velocity audit
kind: lesson
date: 2026-04-29
---

# Build velocity audit

What happened, root cause, what we'd do differently. Framed as
history, not as authoritative current truth.
```

### `pr-context/<branch-slug>/` — in-flight working notes

Branch-scoped. Investigation notes, design sketches, handoff summaries for the *current* PR. When the PR merges, `/strata:archive` moves these to an archive subfolder.

```text
pr-context/
└── feat-auth-rewrite/
    ├── 2026-05-24-1030--gd--token-rotation-design.md
    ├── 2026-05-24-1430--gd--integration-test-plan.md
    └── 2026-05-24-1700--gd--handoff-to-review.md
```

The filename carries timestamp + author initials so multiple people can save in parallel without collision.

## Branch awareness

The current branch is derived from `git rev-parse --abbrev-ref HEAD`. Skills that write branch-scoped notes use it automatically:

- `/strata:save` → `pr-context/<branch-slug>/...`
- The Stop hook checks if you're on a non-trunk branch before nudging
- `recall(scope="pr-context")` surfaces branch-scoped notes for the current branch

Trunk branches (`main`, `master`, `develop`, `trunk`, `default`) are excluded from the Stop nudge. You shouldn't be doing feature work on trunk anyway.

## What Strata isn't

It's not a wiki replacement. Notes are scoped and structured for the specific job of feeding Claude useful context. They're terse, frontmatter-rich, optimised for machine retrieval.

It's not a documentation generator. The notes are *consulted* by Claude during conversations, not exported into a public-facing site.

It's not a code analyser. When Graphify is installed alongside, Strata reads the graph for verification and projection. Strata itself never parses source code.

It's not networked. No telemetry, no LLM calls from Strata code, no external services. The fastembed semantic-search dep is CPU-only ONNX, downloaded once at install.

---

Next: [Skills](../skills/) — every slash command and when each one auto-invokes.

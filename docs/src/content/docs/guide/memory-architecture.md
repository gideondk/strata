---
title: Memory architecture
description: "Strata organises the vault the way agent memory actually works in 2026. Three scopes for three kinds of knowledge"
---

Strata organises the vault the way agent memory actually works in 2026. Three scopes for three kinds of knowledge.

## The triad

Strata organises memory into three kinds, each with its own lifetime and retrieval pattern. The names come from cognitive science: **episodic**, **semantic**, **procedural**. Each kind sits on its own path through the vault.

| Type | Holds | Strata scope |
|---|---|---|
| **Episodic** | Specific past interactions ("on this branch we tried X") | `pr-context/<branch>/` |
| **Semantic** | Facts, vocabulary, decisions ("Postgres for tenant data"; "an Order has one Customer") | `domain/` + `decisions/` |
| **Procedural** | Recipes, workflows, "how we do things here" | `procedural/` |

`lessons/` bridges episodic and procedural. Retrospectives that capture *what happened* and what we'd do differently next time.

## Why this matters

Different memory types have different retrieval shapes:

- **Episodic recall** is time-bounded and narrow ("what did I do last Tuesday on `feat/auth`"). It belongs in `pr-context/` and aggressively decays. Old branches archive after merge.
- **Semantic recall** is broad and stable ("what does our system know about tokens"). It belongs in `domain/` and `decisions/` and never decays unless the underlying fact changes (then: `strata:invalidate` or `strata:decide --supersedes`).
- **Procedural recall** is when-needed ("how do I add a new service") and step-by-step. It belongs in `procedural/` as numbered recipes with verification steps.

Mixing them causes recall to return the wrong shape: retrieving an episodic note when you wanted semantic gives you a stale snapshot; retrieving semantic when you wanted procedural gives you a definition where you needed steps.

## What this means in practice

When you ask Claude *"how do we handle tenant data"*, the recall layer prefers:
- `domain/` notes (the answer is semantic)
- with high `relevance` (recent + linked + not superseded)
- excluding `procedural/` unless the question is shaped as "how do I..."
- excluding `pr-context/` unless filtered by branch

The progressive-disclosure pattern (Layer 1 → 2 → 3) means you almost always get Layer 1 (compact index) and only escalate to Layer 3 (full body) when needed. Token economy by default.

## What the model commits to

The triad isn't a marketing carve-out. It's a design choice with real consequences for how the vault behaves:

| Commitment | What it gets you |
|---|---|
| **Separate retrieval paths per memory type** | The right shape comes back when you ask, not a stale snapshot when you wanted a definition. |
| **Per-scope lifetimes and decay** | Episodic notes archive when their branch merges; semantic notes outlive every branch; procedural notes only change when the recipe changes. |
| **Type-aware indexing** | Domain notes get embedded for semantic recall; decisions get versioned for supersession; pr-context gets filtered by branch. |
| **An explicit cost** | You have to learn the model. Five scopes plus the bridge isn't free to internalise. The payoff is that recall stays accurate as the vault grows. |

## When the model breaks down

The triad is a guide, not a law. Edge cases:

- A `domain/` note that's actually a recipe → move to `procedural/` via `strata:correct`
- A `procedural/` note that's actually a one-off → archive (it's not durable)
- A `decisions/` ADR that's really a retrospective → it might belong in `lessons/`

`/strata:review` surfaces notes whose `kind:` frontmatter disagrees with their scope.

## Reading order

If you're new: [Getting started](/guide/getting-started/) → [Concepts](/guide/concepts/) → this page (you're here) → [Skills](/guide/skills/).

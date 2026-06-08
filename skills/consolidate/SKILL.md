---
name: strata:consolidate
disable-model-invocation: true
description: Promote durable notes out of aging per-branch pr-context dirs into the branch-agnostic lessons/ scope (rule-based, no LLM). Use when the user says "clean up old branch notes", "graduate these to lessons", "tidy pr-context", or after a wave of merged PRs. Dry-run by default; --apply to perform. Command-only — run it explicitly as /strata:consolidate.
---

# strata:consolidate

The "graduate durable content out of pr-context" step. Branch dirs that
Have aged past a threshold are scanned for notes worth keeping; those
Get moved to `lessons/` with a `consolidated_from:` breadcrumb.

## What gets promoted

A pr-context note is promoted when:

1. Its branch dir is older than `--age-days` (default 60)
2. Its `kind:` frontmatter is one of `handoff`, `decision-draft`, `review`

Other kinds (`session`, `investigation`) stay branch-scoped, they're
Transient. Use `/strata:archive` to retire the whole branch dir when
the PR merged.

## How

```bash
# Dry-run (default)
"${CLAUDE_PLUGIN_ROOT}/bin/strata" consolidate

# With a different age threshold
"${CLAUDE_PLUGIN_ROOT}/bin/strata" consolidate --age-days 30

# Perform
"${CLAUDE_PLUGIN_ROOT}/bin/strata" consolidate --apply
```

## What it does

For each promoted note:
1. Computes `lessons/YYYY-MM-DD-<topic>.md` as the target
2. Copies the frontmatter forward, adds `consolidated_from:` (audit) +
   `consolidated_at:` (date)
3. Deletes the source from pr-context
4. Refreshes the FTS index

## When to use

- After a wave of PR merges, run dry-run to see what's accumulated
- Monthly hygiene, alongside `/strata:review`
- Before `/strata:archive` on an old branch — consolidate first,
  then archive what remains

## Don't do

- Don't run on a branch you're still actively working on
- Don't promote `session` or `investigation` notes — they're inherently
  branch-scoped and become noise in lessons/. The script already filters
  these.
- Don't auto-invoke. This is a maintenance action — user-initiated.

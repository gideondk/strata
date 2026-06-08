---
name: strata:archive
disable-model-invocation: true
description: Move merged branches' pr-context dirs into archive/. User-only — run when the user explicitly asks to "clean up old branches", "archive merged work", or "tidy the vault". Never deletes, only moves, but it mutates the vault and changes what recall returns, so it does not auto-invoke (matching forget / export-to-repo / promote-to-pr). Detects merged branches via `gh pr list --state merged` or `git branch --merged main` fallback.
---

# strata:archive

PR-context notes accumulate as branches merge. This skill moves stale
Working notes out of `pr-context/` and into `archive/<merge-date>--<branch>/`
so the search/index reflects active work.

## When to use

- Periodically (weekly is fine).
- Before a release, to leave a clean snapshot.

## How

```bash
# See what would happen, no mutation
"${CLAUDE_PLUGIN_ROOT}/bin/strata" archive --dry-run

# Apply
"${CLAUDE_PLUGIN_ROOT}/bin/strata" archive
```

Strategies (auto-selected, override with `--strategy`):

- **`gh`** — queries `gh pr list --state merged` and matches by `headRefName`.
  Most accurate (uses real merge dates).
- **`git`** — `git branch --merged <main>`. Works without `gh`; uses today's
  date as the archive date.

Pass `--main-branch develop` if your trunk isn't `main`.

## What it doesn't do

- Doesn't delete anything — moves only.
- Doesn't archive `decisions/`, `lessons/`, or `domain/` — those are durable.
- Doesn't unwind itself; restore by moving back from `archive/`.

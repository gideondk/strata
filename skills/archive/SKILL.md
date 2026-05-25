---
name: strata:archive
description: Move merged branches' pr-context dirs into archive/. Use when the user asks to "clean up old branches", "archive merged work", "tidy the vault", after a release, or whenever the pr-context directory has gotten visibly stale. Read-only on archive/ and merged branches' notes, never deletes, only moves. Detects merged branches via `gh pr list --state merged` or `git branch --merged main` fallback.
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
"${CLAUDE_PLUGIN_ROOT}/bin/run-python.sh" \
  "${CLAUDE_PLUGIN_ROOT}/scripts/archive-merged.py" --dry-run

# Apply
"${CLAUDE_PLUGIN_ROOT}/bin/run-python.sh" \
  "${CLAUDE_PLUGIN_ROOT}/scripts/archive-merged.py"
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

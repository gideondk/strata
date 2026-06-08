---
name: strata:archive-planning
disable-model-invocation: true
description: Retire a `.planning/<initiative>/` subdir after its content has been migrated to the vault via `/strata:bootstrap`. Runs `git mv .planning/<initiative> .attic/<initiative>` and commits. Refuses to archive subdirs that aren't fully bootstrap-processed (to avoid losing knowledge). NEVER auto-invokes, always require explicit user request, since the operation rewrites the working tree.
---

# strata:archive-planning

The "retire after migrate" step in the per-initiative planning
Workflow. Use after `/strata:bootstrap` over a shipped initiative's
Planning dir has pulled the durable knowledge into the vault.

## The full workflow

```text
.planning/auth-rewrite/PLAN.md     ← humans write here while live
.planning/auth-rewrite/CONTEXT.md
.planning/auth-rewrite/SPEC.md
        │
        │  /strata:bootstrap
        ▼
vault/<repo>/decisions/2026-05-24-token-rotation.md
vault/<repo>/domain/auth-tokens.md
vault/<repo>/lessons/2026-05-24-auth-rewrite.md
        │
        │  /strata:archive-planning .planning/auth-rewrite/
        ▼
.attic/auth-rewrite/PLAN.md        ← gone from active tree, still in git
.attic/auth-rewrite/CONTEXT.md     ← reachable via `git log --follow`
.attic/auth-rewrite/SPEC.md
```

## How

Dry-run first:

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/strata" archive-planning \
  .planning/auth-rewrite
```

If every file is bootstrap-processed, you'll see the proposed `git
Mv` + commit. Otherwise the script lists the unprocessed files and
Refuses, telling you to bootstrap them first.

Then apply:

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/strata" archive-planning \
  .planning/auth-rewrite --apply
```

The script:

1. Verifies every `.md` in the subdir is in `.bootstrap-state.json`
   with a current SHA (i.e. processed AND unchanged since)
2. `git mv .planning/auth-rewrite .attic/auth-rewrite`
3. `git commit -m "chore: archive planning .planning/auth-rewrite → .attic/auth-rewrite"`

## When to use `--force`

You can pass `--force` to archive a subdir with unprocessed files,
but understand the consequence: **the knowledge in those files
Doesn't make it into the vault**. They'll still exist in git history
Under `.attic/`, but Strata won't surface them in searches.

Reasonable cases:

- The subdir has scratch / TODO files you intentionally didn't
  bootstrap (e.g. `BRAINSTORM.md`, `TEMP.md`)
- You're archiving stale planning you specifically don't want in
  the vault

In every other case, run `/strata:bootstrap` over the subdir first.

## Don't do

- Don't run this on directories outside `.planning/` / `.scratch/`
  unless you know what you're doing, there's no scope check beyond
  "must be inside the project tree."
- Don't auto-invoke. The user must explicitly ask. The Stop hook
  doesn't suggest this, the SessionStart primer doesn't suggest this.
  Archive is a deliberate, end-of-initiative action.
- Don't archive when the bootstrap migration produced lots of
  `proposed` ADRs you haven't reviewed yet. The whole point of the
  workflow is settling state before retiring source.

---
name: strata:bootstrap
disable-model-invocation: true
description: One-time onboarding pass to seed the Strata vault from an existing codebase's docs. Scans CLAUDE.md, docs/, .planning/, and similar for candidates, then dispatches each one to a `strata:bootstrap-worker` subagent in parallel batches, the worker reads its file, classifies, writes the right kind of vault note, and returns one line. Idempotent, tracks processed files by SHA256. Use this once when first installing Strata on a repo with substantial existing documentation.
---

# strata:bootstrap

Onboarding pass. Walk existing docs, dispatch each one to a worker
Subagent, aggregate the results.

## Posture: act, don't narrate

- **No upfront questions about scope** unless the candidate count is > 50.
- **No tables, no recommendations, no "two-step plan" prose** before
  starting work.
- **Source file content stays out of your context** — that's the whole
  point of the workers. You see only the scan listing and the one-line
  worker summaries.
- **Final summary: one line plus counts.** The user can `/strata:review`
  for detail.

## Workflow

### 1. Scan

```
bootstrap_scan(unprocessed=true, bucket="fresh", verify=true,
               min_freshness=0.6, max_group_size=12)
```

Default pass: fresh docs only (<90d), claims verified, freshness ≥ 60%,
dense parent dirs split into sub-groups of at most 12 files
(by date prefix when filenames are dated). For a wider net, drop
`min_freshness` to 0.4, or omit `bucket` so aging + old appear too.

`max_group_size` is what stops dense planning folders (a `docs/plans/`
with 40+ unrelated initiatives) from collapsing into 3-6 consolidated
Notes. Pass `max_group_size=12` for typical mixed-initiative folders;
Omit it for folders where siblings genuinely describe one thing.

If after filtering the candidate count is > 50, ask the user once to
Narrow scope (e.g. by directory). Otherwise proceed.

### 2. Get the vault dir

```
memory_status()
```

Note the `vault_dir` path printed in the response. You'll pass it to
Each worker.

### 3. Dispatch by parent-dir GROUP, not by single file

The scan's JSON output (when `--json` is on) includes a
`dispatch_groups` map keyed by **parent directory**. Sibling files in
the same folder (e.g. `.planning/auth-rewrite/PLAN.md` +
`.../CONTEXT.md` + `.../SPEC.md`) almost always describe the same
Initiative, dispatch them to ONE worker that handles the set together
and writes one consolidated note, not three near-duplicates. (Previous
"one worker per file" dispatch produced the duplicate ADRs we saw on
the earliest bootstrap runs.)

Batch the groups into runs of **5 groups at a time**. For each batch,
invoke `strata:bootstrap-worker` once per group **in a single
Message with multiple Agent tool calls** so they run concurrently.

Per worker, the prompt to send:

```
file_paths:
  .planning/auth-rewrite/PLAN.md
  .planning/auth-rewrite/CONTEXT.md
  .planning/auth-rewrite/SPEC.md

vault_dir: /Users/gd/StrataVault/myrepo
plugin_root: ${CLAUDE_PLUGIN_ROOT}

Group freshness: <average freshness% across the group, when verify was on>
Group age: <oldest bucket across the group>

Follow your standard procedure. Return one line per note written + one
per skipped file.
```

Hand the worker only **metadata**, never paste source file content
into the prompt. The worker reads each file itself.

When verify was on and any file in the group had paths_missing,
mention that in the prompt so the worker downgrades the status
(`proposed` instead of `accepted` for decisions; framed as a lesson
when group freshness < 50%).

### 4. Aggregate and continue

Each worker returns 1-3 lines (one per write + one per skipped sibling
in the group). Collect and print them grouped by kind, no commentary:

```
DECIDE decisions/2026-05-24-use-postgres-tenant-data.md from .planning/auth/PLAN.md,.planning/auth/SPEC.md
SKIP - from .planning/auth/CONTEXT.md (generic preamble)
DOMAIN domain/auth-tokens.md from .planning/auth/TOKENS.md
DOMAIN domain/scheduling-tenant.md from .planning/scheduling/PLAN.md
SAVE pr-context/feat-x/...handoff.md from .planning/x/HANDOFF.md
ERROR .planning/oversized/PLAN.md — write failed: ...
```

Then dispatch the next batch of groups. Stop when the group list is
Exhausted or you've processed ~20 groups (then ask the user whether
to continue, not because of context pressure, but to let them
Eyeball quality mid-flight).

### 5. Final report

```
Bootstrapped N files. D domain, A decisions, L lessons. Skipped S. E errors.
State: <vault_dir>/.bootstrap-state.json
```

That's the whole report.

## Why subagents (and why grouped)

Each worker has its own context window, your context stays clean.
Five parallel workers cut wall time by ~5x. A bad file fails one
Worker without poisoning the run.

Grouping by parent dir is the **dedup mechanism**: workers see all
Siblings together, so the three-files-of-the-same-initiative case
(`PLAN.md` + `CONTEXT.md` + `SPEC.md`) produces one consolidated note
Instead of three near-duplicates. Early bootstrap runs exposed
this when un-grouped dispatch wrote 3 near-identical "extract visit
Aggregate" ADRs from PLAN/CONTEXT/SPEC.

Trade-off that remains: no shared context **across** workers, so
Wikilinks between notes written in the same batch may be unresolved.
That's fine, `/strata:review` surfaces them later and the user can
`[[link]]` them by hand.

## Don't do

- Don't read source files yourself. Dispatch to a worker.
- Don't dispatch one worker per file. Use `dispatch_groups` from the
  scan output and dispatch one worker per parent-dir group.
- Don't ask the user to confirm each file. Dispatch the batch.
- Don't expand a batch beyond 5 groups in flight — concurrency past
  that starts costing more than it saves and risks rate limits.
- Don't auto-invoke `forget` / `promote-to-pr` / `export-to-repo` /
  `archive` during bootstrap, those are user-driven only.

## Idempotency

`<vault>/<repo>/.bootstrap-state.json` tracks `{path: {sha256,
processed_at}}`. A file resurfaces if its SHA changes. To re-process
A file manually, edit it or delete its entry from the state file.
The worker handles the mark step itself; you don't need to.

## Tuning what gets scanned

Out of the box, the scan skips build dirs, plugin meta-config
(`.claude/`, `.github/`, etc.), our own outputs, and common AI-tool
Configs at root. To tune per repo, drop a `.strataignore` at the
Project root using gitignore syntax, see `examples/.strataignore`
in the plugin for a starter. `.ignore` (the ripgrep/fd cross-tool
Convention) is also honoured. Precedence, low → high: defaults →
`.ignore` → `.strataignore`. Negate a default with `!pattern`.

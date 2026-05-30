---
name: strata:export-to-repo
disable-model-invocation: true
description: Promote a vault file (typically an ADR) into the host repo for git-blameable audit history. Use when the user asks to "make this ADR part of the codebase", "commit this decision to the repo", "promote to docs/adr/", "make this auditable", or for regulatory/compliance work that needs PR review. Lints with --strict before copy; never auto-commits, user runs git add / git commit themselves. Two-step with mandatory --dry-run for visibility.
---

# strata:export-to-repo

The vault is the working store. The repo is the audit anchor. Most decisions
Live happily in the vault, fast capture, no PR overhead. But some need to
Become part of the codebase's permanent record: regulatory ADRs, decisions
Referenced by code, anything that should ship with the repo.

This skill copies one file from the vault into the repo, with a `--strict`
Lint pass first, so PHI/secrets can't slip across the boundary unnoticed.

## Workflow

User runs `/strata:export-to-repo decisions/<slug>.md`. You:

1. Confirm the file path is right (use `memory_search` if unsure).
2. Run with `--dry-run` first so the user sees the destination + lint:

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/run-python.sh" \
  "${CLAUDE_PLUGIN_ROOT}/scripts/export-to-repo.py" \
  --source decisions/2026-05-20-use-postgres.md \
  --preset secrets,pii \
  --dry-run
```

3. If clean, re-run without `--dry-run`.
4. The script prints the `git add`/`git commit` commands. You suggest them
   to the user; they confirm and run them.

## Configuration

- `--source` — required, vault-relative path
- `--dest` — repo-relative directory (default `docs/adr/`)
- `--preset` — lint presets (default `secrets,pii`; add `phi-uk`/`phi-us`
  for regulated content)
- `--dry-run` — show what would happen, don't copy

## What it intentionally doesn't do

- Doesn't run `git add` / `commit` / `push` — those are user decisions.
- Doesn't rewrite the file (frontmatter stays as-is).
- Doesn't delete the vault copy. The vault keeps the source of truth; the
  repo gets a synchronised audit copy.

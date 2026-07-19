---
name: strata-domain
description: Add or update a domain note in the vault's domain/ scope, vocabulary, invariants, conventions. Invoke autonomously when a domain term is defined or refined in conversation (e.g. "a Visit always belongs to exactly one Run", "events are past tense"). One concept per file, kebab-case filename, wikilink to related notes.
---

# strata:domain

Domain notes are the long-lived part of team memory. They define vocabulary
(what does "Tenant" mean here?), encode invariants (an Order always belongs
to exactly one Customer), and pin conventions (event names use past tense).

## Rules

- **One concept per file.** Split rather than expand.
- Filename in kebab-case: `medication-administration-windows.md`.
- Frontmatter required (see `templates/domain.md`).
- Use Obsidian-style `[[wikilinks]]` to cross-reference other domain notes
  and ADRs by filename without extension.

## How

User runs `/strata:domain <concept-name>`. You:

1. **Recall first.** Call `recall(query="<concept>", scope="domain", layer=1)`
   to find an existing note for this concept, possibly under a different slug.
   If one exists, UPDATE it instead of forking a second definition; if two
   notes would conflict, reconcile through `/strata:correct`. Only create a
   new note when recall shows nothing close.
2. Compose the body using `templates/domain.md` as the shape (Definition,
   Invariants, Where it appears — skip the frontmatter block; the script
   generates it).
3. Save through the strata command, body on stdin:

   ```bash
   strata domain --topic "<Concept>" <<'EOF'
   # <Concept>

   ## Definition
   ...
   EOF
   ```

   To update the existing note recall found, add `--overwrite` (the original
   `created` date is preserved, `updated` is stamped). Without the flag an
   existing note is refused, so you can't clobber one by accident.

The script writes `domain/<slug>.md`, refreshes the index, and auto-commits
when the vault is git-backed — no separate `strata reindex` step. Don't write
domain notes with the raw Write tool; that bypasses the index, the lint
pre-step, and git-mode auto-commit.

## Cross-repo (shared) domain notes

For vocabulary that applies across multiple repos (e.g. a company-wide
convention), target the `_shared` namespace by overriding the repo name:

```bash
STRATA_REPO_NAME=_shared strata domain --topic "<Concept>" <<'EOF'
...
EOF
```

The note lands at `<vault>/_shared/domain/<slug>.md`; the MCP search
includes shared notes by default.

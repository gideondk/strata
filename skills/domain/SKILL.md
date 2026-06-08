---
name: strata:domain
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
2. If new, write the body using `templates/domain.md` as the shape.
3. Save it directly to `<vault>/<repo>/domain/<slug>.md` via the standard
   Write tool. Use the absolute path printed by `/strata:init` or read it
   from `strata.memory_status` via MCP.

After saving, regenerate the index so the MCP search picks it up:

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/refresh-index.py"
```

## Cross-repo (shared) domain notes

For vocabulary that applies across multiple repos (e.g. a company-wide
Convention), put the note at `<vault>/_shared/domain/<slug>.md`. The MCP
Search includes shared notes by default.

---
name: strata:correct
description: Edit or retire a vault note. Three paths, fix wrong text (default), mark invalidated (no longer current), or update a frontmatter field. Invoke autonomously when the user says "X note is wrong", "fix the part about Y", "update the status of <note>", "that's no longer true", "stop using <note>", or "deprecate <note>". For ADR retirement prefer `/strata:decide --supersedes` (bidirectional link). For full deletion (PHI / secrets) use `/strata:forget`.
---

# strata:correct

The unified correction surface. One skill, three operations distinguished
by intent and flags.

## Decide the operation

| Situation | Path |
|---|---|
| One paragraph is wrong, note overall still useful | **edit** (default) |
| Whole note no longer current, keep history visible | **invalidate** |
| ADR replaced by new decision | use `/strata:decide --supersedes` |
| Note must disappear (PHI, secrets) | use `/strata:forget` |

## Edit (default)

### Replace body

```bash
cat <<'EOF' | "${CLAUDE_PLUGIN_ROOT}/bin/run-python.sh" \
    "${CLAUDE_PLUGIN_ROOT}/scripts/correct-note.py" \
    domain/order-aggregate.md \
    --reason "OrderPriced now emitted before OrderConfirmed, not after."
# Order Aggregate

<new content here>
EOF
```

### Update one field

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/run-python.sh" \
  "${CLAUDE_PLUGIN_ROOT}/scripts/correct-note.py" \
  domain/order-aggregate.md \
  --set status=stable \
  --reason "Adopted in production after two-week rollout."
```

`--set` is repeatable. `--reason` strongly recommended, appears in the
`corrections:` audit list.

## Invalidate

The note stays readable but drops out of default search. Required `--reason`,
optional `--replaced-by`:

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/run-python.sh" \
  "${CLAUDE_PLUGIN_ROOT}/scripts/invalidate-note.py" \
  domain/old-aggregate-pattern.md \
  --reason "Aggregate split into Order + Payment in 2026-05-24 refactor." \
  --replaced-by "domain/order-aggregate.md"
```

## What's recorded

**Edits** append to `corrections: [{at, by, reason}]` and bump `updated:`.
**Invalidations** set `status: invalidated`, `invalidated_at`,
`invalidated_by`, `invalidation_reason`, and optional `replaced_by`.

Both refresh the FTS index.

## Don't do

- Don't invalidate when you should edit. Editing keeps the note searchable;
  invalidating drops it out of default results.
- Don't edit a status to `invalidated` directly — use the invalidate path
  so the audit fields land properly.
- Don't invalidate ADRs through here — `/strata:decide --supersedes`
  carries the reasoning forward.
- Cosmetic fixes (typo, link) can omit `--reason`. Semantic changes need it.

---
name: strata:correct
description: Edit, retire, or learn-from a vault note. Invoke autonomously when the user says "X note is wrong", "fix the part about Y", "update the status of <note>", "that's no longer true", "stop using <note>", "deprecate <note>" — OR corrects something Claude proposed ("no, X is actually Y", "that's wrong because Z", "we don't do it that way", "you got it backwards"). Finds the related note and applies the fix with conversation provenance (correction_source); if the corrected fact isn't in the vault yet, creates the right note instead. For ADR retirement prefer /strata:decide --supersedes; for deletion (PHI/secrets) use /strata:forget.
---

# strata:correct

The unified correction surface. One skill, three operations distinguished
by intent and flags.

## Decide the operation

| Situation | Path |
|---|---|
| One paragraph is wrong, note overall still useful | **edit** (default) |
| User corrects something Claude proposed in conversation | **learn-from** (see below) |
| Whole note no longer current, keep history visible | **invalidate** |
| ADR replaced by new decision | use `/strata:decide --supersedes` |
| Note must disappear (PHI, secrets) | use `/strata:forget` |

## Edit (default)

### Replace body

```bash
cat <<'EOF' | "${CLAUDE_PLUGIN_ROOT}/bin/strata" correct \
    domain/order-aggregate.md \
    --reason "OrderPriced now emitted before OrderConfirmed, not after."
# Order Aggregate

<new content here>
EOF
```

### Update one field

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/strata" correct \
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
"${CLAUDE_PLUGIN_ROOT}/bin/strata" invalidate \
  domain/old-aggregate-pattern.md \
  --reason "Aggregate split into Order + Payment in 2026-05-24 refactor." \
  --replaced-by "domain/order-aggregate.md"
```

## Correcting something Claude proposed (from a conversation)

When the user corrects an idea Claude just gave ("no, X is actually Y",
"that's wrong because Z", "we don't do it that way", "you got it backwards"),
that's signal worth keeping. Flow:

1. **Recall the topic** — `recall(query="<topic>", layer=1)`.
2. **One match** → correct that note (above), adding
   `--set correction_source=claude-session` so the audit trail shows the
   correction came from a session, not a manual edit. **Several matches** → ask
   which one. **No match** → the vault didn't know this yet; create the right
   note instead: a chosen approach → `/strata:decide`, a vocabulary/invariant →
   `/strata:domain`, a newly-surfaced contested point → `/strata:propose
   --status contested`. Include in the body: "Claude proposed: <wrong>; actual:
   <correction>" so future readers see the genesis.
3. **Confirm in one line** with the path edited/created.

Skip when the correction is about Claude's local reasoning ("run that without
the flag") rather than durable vault knowledge; and don't fire while the user is
still arguing the point — wait until the correction is stated definitively.

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

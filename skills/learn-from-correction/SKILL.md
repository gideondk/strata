---
name: strata:learn-from-correction
description: When the user corrects an idea Claude proposed, "no, X is actually Y" / "that's wrong because Z" / "we don't do it that way", find the related vault note(s) and apply the correction with conversation provenance. Auto-invoke on correction-signal phrases. If the correction touches a fact NOT yet in the vault but worth keeping, create the right note (decision / domain / proposition) instead of editing. Records `correction_source: claude-session` in the audit trail.
---

# strata:learn-from-correction

The user just told Claude that something Claude proposed is wrong.
That's signal worth keeping, both as a correction to whatever vault
Note led Claude to the wrong answer, and as a record so the next
Session doesn't make the same mistake.

## When this fires

Auto-invoke on patterns like:

- "no, X is actually Y"
- "that's wrong because Z"
- "we don't do it that way"
- "you suggested X but actually we use Y"
- "actually it's Z, not what you said"
- "you got it backwards — Y, not X"

Skip when the correction is about Claude's local reasoning that
Doesn't touch durable knowledge ("no, run that command without the
Flag", not vault material).

## Procedure

### 1. Identify what's wrong

From the conversation, extract:

- **Original claim** Claude made (the wrong thing)
- **Correction** the user provided (the right thing)
- **Reason** the user gave, if any
- **Topic** — what concept/decision/domain term this touches

### 2. Find the source

Recall the vault for the topic:

```text
recall(query="<topic>", layer=1)
```

Three outcomes:

| Recall result | What to do |
|---|---|
| Found one matching note | Correct that note (step 3a) |
| Found several plausible matches | Ask user which one, then correct |
| Nothing matches | Create a new note (step 3b) |

### 3a. Correct an existing note

Pipe a focused edit through `correct-note.py` with the conversation
Context as the reason:

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/run-python.sh" \
  "${CLAUDE_PLUGIN_ROOT}/scripts/correct-note.py" \
  <vault-relative-path> \
  --reason "<concise summary of what was wrong + the correction>" \
  --set correction_source=claude-session
```

If the correction is a body change (not just a field), pipe the
Revised body on stdin:

```bash
cat <<'EOF' | "${CLAUDE_PLUGIN_ROOT}/bin/run-python.sh" \
    "${CLAUDE_PLUGIN_ROOT}/scripts/correct-note.py" \
    domain/order-aggregate.md \
    --reason "User: 'OrderPriced fires before OrderConfirmed, not after.'"
# Order Aggregate

<revised body with the correction applied>
EOF
```

The `corrections:` frontmatter list grows with the new entry —
audit trail of every correction the vault has absorbed.

### 3b. Create a new note from the correction

When the correction is about something the vault didn't yet know:

- **A chosen approach** the team uses → `/strata:decide` with the
  correction as the body
- **A vocabulary / invariant** the team enforces → `/strata:domain`
- **An open question Claude hadn't realised was contested** →
  `/strata:propose --status contested`

In all three cases, include in the body:

```
> Note: this captures a correction made in conversation.
> Claude proposed: <original wrong claim>
> Actual: <correction>
```

So future readers see the genesis of the note.

### 4. Confirm with the user

Show the file path that was edited or created. One line:

```
✓ updated domain/order-aggregate.md — recorded your correction about
  OrderPriced ordering.
```

No multi-line confirmation. The user already knows what they said.

## Don't do

- Don't apply corrections about Claude's local reasoning — only
  things that touch durable vault knowledge.
- Don't blindly edit when several notes match — ask which one.
- Don't strip the original audit trail. The whole point of
  `corrections:` is to keep the history of what changed and why.
- Don't auto-invoke on disagreement that's still in progress —
  wait until the user has stated the correction definitively, not
  while they're still arguing.

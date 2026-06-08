---
name: strata:forget
disable-model-invocation: true
description: Move a vault file to .trash/ + JSONL audit-log entry (who/when/why/SHA256). Recoverable, not destructive. Use when the user asks to "forget", "delete", "remove", "retract", "erase", "GDPR delete", "redact" a memory file, or when PHI/secrets accidentally landed in a note. Mandatory --reason argument captured in audit log. NEVER auto-invoke, always require explicit user request; the audit trail must reflect the user's intent.
---

# strata:forget

Moving > deleting. Files go to `<vault>/<repo>/.trash/` with a timestamped
Filename and a JSONL audit-log entry. The vault search stops returning them;
they're still on disk if you need them back.

## When to use

- A note holds PHI/secrets that can't safely be scrubbed in place.
- GDPR / right-to-erasure request from a data subject.
- A domain note was wrong and you don't want it showing up in search.
- Cleanup after a hasty `/strata:save`.

## How

Two-step with `--dry-run` for safety.

```bash
# 1. Preview
"${CLAUDE_PLUGIN_ROOT}/bin/strata" forget \
  --path decisions/2026-05-20-mistake.md \
  --reason "Erasure request — ticket #1234" \
  --dry-run

# 2. Apply
"${CLAUDE_PLUGIN_ROOT}/bin/strata" forget \
  --path decisions/2026-05-20-mistake.md \
  --reason "Erasure request — ticket #1234"
```

`--reason` is required and is recorded in the audit log. Be specific —
"cleanup" is fine for trivial cases, but for regulatory erasure include the
Ticket / request reference.

## Audit log

Each forget writes a line to `<vault>/<repo>/.audit.log`:

```json
{"ts":"2026-05-21T13:42:11Z","action":"forget","src":"decisions/...","dest":".trash/2026-05-21-1342--decisions__...","size":1842,"sha256":"abc…","by":"<git user.name>","reason":"<your reason>"}
```

Fields: ISO-8601 timestamp, action, source path, trash path, byte size,
sHA-256 of the file contents at forget time, author, reason.

The log is **append-only** (no script deletes from it). If you sync the
Vault via git, commit the log to give the deletion a blameable history.

## Recovery

Just move the file back:

```bash
mv ~/StrataVault/myrepo/.trash/2026-05-21-1342--decisions__... \
   ~/StrataVault/myrepo/decisions/2026-05-20-mistake.md
```

(The flattened filename in trash uses `__` for `/` so it's recoverable
Unambiguously.)

## What it doesn't do

- Doesn't redact other notes that wikilink to the forgotten one — those
  become unresolved links, which `/strata:review` will surface.
- Doesn't propagate the deletion to other team members' vaults — sync
  mechanism handles that.
- Doesn't `shred` the file. If your threat model requires actual deletion
  (not "moved to trash"), follow up with `rm` and a `git filter-branch` if
  applicable.

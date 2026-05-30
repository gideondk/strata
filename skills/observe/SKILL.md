---
name: strata:observe
description: Auto-capture a grounded, low-stakes OBSERVATION into the staging lane without interrupting the user — a breadcrumb anchored to a commit or file, written with status:auto. Use autonomously when you notice something worth a durable trace but NOT worth a decision or a confirmation prompt (e.g. "commit abc bumped the retry budget 3→5", "this module owns rate limiting"). NEVER use for decisions, contested questions, or domain definitions — those are human-ratified. The note is quarantined from recall until a human reviews it.
---

# strata:observe

The safe **autonomous-write** lane (see the autonomy-line ADR: gate on
reversibility + grounding, never on confidence). An agent may write a
**grounded, reversible observation** without asking — because markdown+git make
it trivially revertible and it never ratifies anything.

## When to use

- A durable breadcrumb anchored to a real artifact: "commit `abc` changed the
  token-bucket policy", "`billing/` owns invoice retries".
- Worth keeping, but **not** worth interrupting the user for, and **not** a
  decision.

**Never** use for: decisions (`/strata:decide`), contested questions
(`/strata:propose`), or domain definitions (`/strata:domain`). Those are
human-ratified — that's the moat. This script structurally cannot write them.

## How

Grounding is **required** — pass `--source-file` (project-relative, repeatable)
and/or `--commit`. Ungrounded auto-writes are refused.

```bash
echo "Commit bumped the HTTP retry budget 3→5; see the client." | \
  "${CLAUDE_PLUGIN_ROOT}/bin/run-python.sh" \
  "${CLAUDE_PLUGIN_ROOT}/scripts/observe.py" \
  --topic "retry budget bumped" \
  --source-file "src/http/client.py" --commit "$(git rev-parse --short HEAD)"
```

The note lands in `pr-context/<branch>/` with `status: auto` +
`source: git-derived`. It **announces itself** and is **quarantined from
recall** (it won't surface in `/strata:find`, the recall tool, or the primer)
until a human reviews it.

## The review lifecycle (keep or discard)

Auto-notes pile up in the **"Awaiting your input"** section of
`/strata:dashboard`. For each:

- **Keep / promote** — edit the note and remove the `status: auto` line (or
  change it to a normal status). It then enters recall like any other note.
- **Discard** — `/strata:forget <path>` (or just delete the file).

This is "machine proposes, human disposes": capture is automatic, but nothing
unreviewed is ever served as canonical memory.

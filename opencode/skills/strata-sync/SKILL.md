---
name: strata-sync
description: Pull and push the git-backed Strata vault. This is the ONLY Strata command that touches the network — everything else is local. Use when the user says "sync the vault", "pull the latest memory", "push my notes", "share these decisions with the team", or at the start/end of a session on a shared vault. Only works when the vault is git-backed (vault_sync=git, set up via /strata:init --git); for iCloud/Dropbox/Obsidian-Sync vaults there's nothing to run.
---

# strata:sync

Bring the git-backed vault level with its remote: commit anything pending,
`git pull --rebase`, then `git push`. The "pull before writing" rule is the
best defense against conflicts on a shared vault, so run this at the **start**
of a session (to get teammates' notes) and again at the **end** (to publish
yours).

This is the one place Strata opens a network connection, and only because you
asked. It never runs from a hook or on a timer.

## When it applies

Only when the vault is git-backed. Check quickly:

```bash
strata audit-config
```

If `vault_sync` is `manual` (the default), there's nothing to sync here — the
user's vault rides on iCloud / Dropbox / Syncthing / Obsidian Sync, which sync
themselves. Say so and stop. To turn the vault into a git repo, that's
`/strata:init --git` (one time), then set `vault_sync: git` in the plugin
config.

## Run it

```bash
strata sync
```

That commits pending changes, pulls with rebase, and pushes. Report the
one-line result back to the user.

Variants:

```bash
strata sync --no-push    # pull the team's latest, don't publish yours yet
strata sync --dry-run    # show what would happen; touch no remote
strata sync --strict     # block the push if the secret/PII lint flags a note
strata sync --no-lint    # skip the pre-push lint pass entirely
```

Before pushing, sync lints the outgoing notes for secrets and PII. By default
findings are warnings (it pushes anyway and tells you); `--strict` turns them
into a hard stop. Suggest `--strict` when the user works in a regulated
codebase or the vault is shared beyond their team.

## If it stops on a conflict

A rebase conflict means two people edited the same note. `strata sync` stops
before pushing and prints the resolution steps — it never auto-resolves, so no
one's writing is silently dropped. Relay those steps to the user; the fix is
ordinary git (`git add -A && git rebase --continue`, or `git rebase --abort`
to back out). Most note types avoid this entirely: pr-context filenames carry a
timestamp + author initials, `.jsonl` audit logs union-merge, and superseded
decisions are demoted rather than overwritten.

## Don't do

- Don't run `strata sync` on a `manual` vault — there's no remote to reach.
- Don't run it from a loop or "just in case." It's a deliberate, user-facing
  action.
- Don't try to resolve a rebase conflict by force-pushing or discarding the
  remote. Hand the conflict to the user with the printed steps.

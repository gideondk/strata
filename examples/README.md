# Examples

Drop-in starter files for adopting Strata.

## `.claude/settings.json`

A minimal team-scoped settings file. Commit this in your repo's `.claude/`
directory to share the Strata enablement + a sensible `gh`/`git` read-only
permission allowlist with the whole team.

```bash
cp examples/.claude/settings.json /path/to/your/repo/.claude/settings.json
```

The shape follows [Anthropic's settings reference](https://code.claude.com/docs/en/settings).
The permissions allowlist covers the read-only `git` and `gh` commands
Strata's hooks and skills invoke, so engineers don't get permission
prompts on every SessionStart.

## What's not in here

We don't ship a starter `CLAUDE.md` — that should reflect *your* project's
conventions, not a generic template. The Anthropic guidance is to keep the
root one as "pointers and critical gotchas only," with per-subdirectory
files for local conventions. Compose yours from scratch.

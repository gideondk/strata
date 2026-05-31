# Installing Strata

Strata ships as a Claude Code plugin from a self-referential marketplace —
the same repo is both the marketplace catalog (`.claude-plugin/marketplace.json`)
and the plugin (`.claude-plugin/plugin.json`).

## Quickest install (recommended)

In a Claude Code session, inside any repo:

```
/plugin marketplace add ~/strata
/plugin install strata@strata
```

That's it. Claude Code copies the plugin into its cache, prompts for the
UserConfig values (vault path, repo namespace, lint presets), and registers
the hooks + MCP server.

To remove later:

```
/plugin uninstall strata@strata
/plugin marketplace remove strata
```

## What's happening

- **`.claude-plugin/marketplace.json`** declares this repo as a marketplace
  called `strata` that publishes a single plugin (also called `strata`).
- **`.claude-plugin/plugin.json`** is the plugin manifest (hooks, MCP, skills,
  userConfig).
- The fully-qualified install id is `strata@strata` — `<plugin-name>@<marketplace-name>`.

## Common install pitfall

If you put `"enabledPlugins": ["strata@local"]` in `.claude/settings.json`
without first running `/plugin marketplace add`, you'll see:

```
strata @ local (user)
Plugin "strata" not found in marketplace "local"
```

`local` isn't a magic keyword, it has to be a marketplace you registered.
Either register one (with the `add` command above) or use the matching
`@<marketplace>` name.

## Project-scoped install (testing against a single repo)

For testing against a specific repo without polluting global config:

```bash
cd /path/to/test-repo

# Register Strata's marketplace once
claude /plugin marketplace add ~/strata
claude /plugin install strata@strata
```

Or commit the team config so everyone on the repo gets it:

```bash
cp ~/strata/examples/.claude/settings.json \
   .claude/settings.json
```

Then engineers run `/plugin marketplace add ...` once on their machine and
the `enabledPlugins` entry in the committed `settings.json` does the rest.

## First-run setup

Claude Code prompts for these userConfig values when the plugin is enabled:

- **vault_path** (default `~/StrataVault`) — where the shared memory vault
  lives on disk. Sync it however you like (Obsidian Sync, Syncthing, iCloud, git).
- **repo_name** (optional) — override the auto-detected namespace. Leave blank
  to derive from `git remote.origin.url` (preferred) or the directory name.
- **lint_presets** (default `secrets`) — comma-separated. Add `pii`, `phi-uk`,
  `phi-us`, `financial-iban` as needed.

After install, in a Claude Code session inside the repo:

```
/strata:init
```

That creates `<vault>/<repo>/{decisions,lessons,domain,pr-context}/` and
seeds `INDEX.md`.

## Venv bootstrap

The first time a Strata hook fires (typically SessionStart), it runs
`bin/bootstrap-venv.sh`, which creates `.venv/` inside the plugin install
directory and pip-installs the runtime deps (`mcp`, `python-frontmatter`,
`pathspec`; `fastembed` is optional, for semantic search).

Takes ~30 seconds on a typical connection. Subsequent sessions are
zero-overhead.

You can pre-warm it manually:

```bash
~/strata/bin/bootstrap-venv.sh
```

Requires Python 3.10+ on PATH. The script searches for `python3.14`,
`3.13`, `3.12`, `3.11`, `3.10` in that order before falling back to
`python3`. On macOS, system `python3` is often 3.9, install a newer one
via `brew install python@3.13` if needed.

## Verify

```
/plugin                  # strata should be "enabled", v0.12.1
/mcp                     # strata server should be listed with 13 tools
```

Functional check inside Claude:

- Ask: *"List the recent decisions"* — Claude should call the
  `recent_decisions` MCP tool autonomously.
- Ask: *"What's in the open PR?"* — calls `current_pr` (requires `gh` auth).
- Run `/strata:save smoke-test` with a few bullet points — writes to
  `<vault>/<repo>/pr-context/<branch>/`.

## Pre-push lint hook (recommended for shared repos)

If your team occasionally promotes vault content into the repo via
`/strata:export-to-repo`, wire `memory-lint --strict` into a `pre-push`
git hook so PHI/secrets can't slip past review:

```bash
# In your repo
cat > .githooks/pre-push <<'EOF'
#!/usr/bin/env bash
~/strata/bin/run-python.sh \
  ~/strata/scripts/memory-lint.py \
  --scope staged --preset secrets,pii --strict
EOF
chmod +x .githooks/pre-push
git config core.hooksPath .githooks
```

## Updating

The marketplace serves the plugin from the local directory, so `git pull`
in `~/strata/` is enough to get new code on
disk. Then in a Claude Code session:

```
/reload-plugins
```

This picks up hook + MCP changes without restarting the session. Skills
reload automatically. If the venv requirements changed, the bootstrap
script will re-resolve them on next session start.

## Uninstall

```
/plugin uninstall strata@strata
/plugin marketplace remove strata
```

Optionally:

- Delete the vault directory at `vault_path` if you no longer want the data
- Delete `~/.claude/plugins/data/strata*` (the FTS index)
- Delete `.venv/` inside the plugin source

The plugin has no entries anywhere else on the system.

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
- **vault_sync** (default `manual`) — set to `git` to make the vault its own
  git repo: every confirmed write is committed locally with a readable message,
  and `/strata:sync` (the only network command in Strata) pulls + pushes.
- **git_remote** (optional, git mode only) — remote for `/strata:sync`. Leave
  blank to use the vault repo's own upstream.

After install, in a Claude Code session inside the repo:

```
/strata:init
```

That creates `<vault>/<repo>/{decisions,lessons,domain,pr-context}/` and
seeds `INDEX.md`.

## Git-backed vault (teams)

For a shared team vault, back it with git instead of a file-sync service:

```bash
strata init --git --remote git@github.com:yourorg/knowledge.git
```

Then set `vault_sync: git` in the plugin config. From that point every
confirmed note lands as a local commit (`strata: decide "…"`, `strata: save
"…"`), and nothing reaches the remote until someone runs `/strata:sync` —
which commits pending changes, pulls with rebase, lints outgoing notes for
secrets (add `--strict` to block on findings), and pushes.

Teammates clone the same repo to their `vault_path` and run `/strata:sync` at
the start and end of a session. `strata init --git` also scaffolds a
`.gitignore` (regenerable artifacts like `INDEX.md` stay out of history) and a
`.gitattributes` (append-only audit logs union-merge, so concurrent writes
never conflict). One vault repo serves all your projects — each repo gets its
own subfolder, `_shared/` holds cross-repo vocabulary.

Prefer iCloud/Dropbox/Obsidian Sync? Keep `vault_sync: manual` (the default)
and skip all of this — plain files, no commits, no sync command.

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
/plugin                  # strata should be "enabled", v0.13.0
/mcp                     # strata server should be listed with 7 tools
```

Functional check inside Claude:

- Ask: *"What do we know about this repo?"* — Claude should call the
  `recall` MCP tool autonomously and return a ranked index of notes.
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

## Installing for opencode

Strata works with [opencode](https://opencode.ai) alongside Claude Code —
both read and write the same vault. The MCP server (read/recall path) and
the skill layer (write path) are fully supported.

### Setup

The `bootstrap-venv.sh` script auto-installs a `~/.local/bin/strata` symlink
on first run, so bare `strata` works on PATH. To bootstrap manually:

```bash
~/strata/bin/bootstrap-venv.sh    # or ~/Development/bigbrain/bin/bootstrap-venv.sh
```

Then generate the opencode config snippet:

```bash
strata opencode-setup
```

This prints a JSON fragment to merge into `~/.config/opencode/opencode.json`.
It wires the MCP server (7 read tools) and points `skills.paths` at the
generated `opencode/skills/` layer (24 skills with opencode-legal names).

After saving the config, **restart opencode** — it loads config once at startup.

### What works

| Feature | Claude Code | opencode |
|---|---|---|
| MCP read tools (`recall`, `code_map`, …) | Yes | Yes |
| Skills (save, decide, domain, …) | `/strata:save` | auto-invoked via description |
| `strata` CLI on PATH | Yes (via `${CLAUDE_PLUGIN_ROOT}`) | Yes (via `~/.local/bin/strata`) |
| Hooks (SessionStart, Stop draft, …) | Yes | Not yet (different event model) |

**Git-backed vault outside Claude Code:** opencode and zcode have no
`userConfig` auto-export, so `vault_sync`/`git_remote` come from the
environment instead. Export them in your shell profile so the `strata`
commands the skills run pick them up:

```bash
export STRATA_VAULT_SYNC=git
export STRATA_GIT_REMOTE=origin   # optional
```

(Claude Code users on the same vault don't need this — the plugin config
covers it there.)

### How skills are shared

The Claude Code skills live in `skills/<name>/SKILL.md` with `name: strata:<name>`.
The opencode layer at `opencode/skills/strata-<name>/SKILL.md` is generated from
those by `strata generate-opencode-skills` — it rewrites the frontmatter name to
`strata-<name>` (opencode rejects colons) and strips Claude-Code-only keys. Skill
bodies are identical and use bare `strata` commands.

### Regenerating the opencode skills layer

After changing skills, regenerate:

```bash
strata generate-opencode-skills
```

The output is deterministic and idempotent. Commit the result so users don't
need to run the generator themselves.

## Installing for zcode

[zcode](https://z.ai) (Z.ai's CLI agent) runs an opencode-schema config at
`~/.zcode/v2/config.json`, so Strata lands there the same way it lands in
opencode — the MCP server (read/recall path) and the skill layer (write path)
are identical. zcode has no third-party plugin install flow (its official
plugins are baked into the app bundle), so the config-merge path below is the
supported route.

### Setup

Bootstrap the venv (same as opencode — creates `~/.local/bin/strata`):

```bash
~/Development/bigbrain/bin/bootstrap-venv.sh
```

Then merge the Strata snippet into zcode's config:

```bash
strata zcode-setup --apply
```

This deep-merges `mcp.strata` + `skills.paths` into `~/.zcode/v2/config.json`,
leaving the existing `provider` block untouched. To preview the snippet without
writing, run `strata zcode-setup` bare. After applying, **restart zcode** — it
loads config once at startup, like opencode.

### What works

| Feature | Claude Code | zcode |
|---|---|---|
| MCP read tools (`recall`, `code_map`, …) | Yes | Yes |
| Skills (save, decide, domain, …) | `/strata:save` | auto-invoked via description |
| `strata` CLI on PATH | Yes (via `${CLAUDE_PLUGIN_ROOT}`) | Yes (via `~/.local/bin/strata`) |
| Hooks (SessionStart, Stop draft, …) | Yes | No (opencode/v2 layer has no hook system) |

The hook gap is the one functional difference. Without SessionStart priming,
zcode sessions don't auto-load vault context at startup — call `strata prime`
manually when you want it. The Stop-hook save-draft and PreCompact flush are
also absent; saves stay explicit (`strata save …`), which is the security model
anyway (writes are never automatic). Recall and the full skill set are
unaffected.

### Skills are shared with opencode

zcode reads the same `opencode/skills/` layer (the `strata-<name>` frontmatter
is legal in both). After changing skills, regenerate and both targets pick it
up:

```bash
strata generate-opencode-skills
```

## Installing for Kimi Code and other agents (`~/.agents/skills`)

Kimi Code, OpenCode, and Codex all scan a shared, tool-neutral skills
directory — `~/.agents/skills/` at user level (Kimi Code additionally reads
`~/.kimi-code/skills/` and `.agents/skills/` at project level). The generated
`strata-<name>` layer is already in the common SKILL.md shape, so one
installer covers every agent that follows the convention:

```bash
~/Development/bigbrain/bin/bootstrap-venv.sh   # venv + ~/.local/bin/strata
strata agents-setup
```

`agents-setup` symlinks each generated skill from `opencode/skills/` into
`~/.agents/skills/` — symlinks, not copies, so a later `git pull` refreshes
every agent at once. It's idempotent, never overwrites a real directory it
didn't create, and `strata agents-setup --uninstall` removes only its own
links.

The command also prints a snippet for Kimi Code's MCP config — deep-merge it
into `~/.kimi-code/mcp.json` (or run `/mcp-config` in the Kimi TUI) to get
the read/recall tools. Restart the agent afterwards; skills and MCP servers
are both picked up at startup.

### What works

| Feature | Claude Code | Kimi Code / generic agents |
|---|---|---|
| MCP read tools (`recall`, `code_map`, …) | Yes | Yes (via `mcp.json`) |
| Skills (save, decide, domain, …) | `/strata:save` | `/skill:strata-save` or auto-invoked |
| `strata` CLI on PATH | Yes (via `${CLAUDE_PLUGIN_ROOT}`) | Yes (via `~/.local/bin/strata`) |
| Hooks (SessionStart, Stop draft, …) | Yes | No — run `strata prime` manually |

As with opencode/zcode, `vault_sync`/`git_remote` come from the environment
(`STRATA_VAULT_SYNC`, `STRATA_GIT_REMOTE`) — there's no plugin userConfig
outside Claude Code.

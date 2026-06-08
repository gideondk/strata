---
name: strata:init
disable-model-invocation: true
description: One-time setup. Creates the vault namespace, then guides the user through the two optional add-ons that unlock the differentiated features. Installing Graphify (for code-graph awareness) and running bootstrap (to migrate existing planning docs). Interactive. Invoke when the user says "set up strata", "initialise the vault", "first install", or when a session starts in a repo where `<vault>/<repo>/` is empty.
---

# strata:init

Three-step onboarding. Always step 1; step 2 and 3 are user-chosen.

## Step 1 · create the vault namespace

Always do this. Idempotent.

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/strata" init
```

Creates `<vault>/<repo>/{decisions,domain,lessons,procedural,propositions,pr-context}/`
Plus `INDEX.md`. Vault path defaults to `~/StrataVault`, overridable
via `STRATA_VAULT_PATH` or plugin `userConfig.vault_path`.

`init-memory.py` also runs an inline venv health check at the end —
imports every required package and reports any missing required or
Optional deps. The bootstrap-venv.sh wrapper auto-installs from
`requirements.txt` on first run, so this is usually green, but it
Makes the state legible to the user before they invoke their first
Save / decide / recall.

Show the user the resulting layout in one line:

```
✓ Strata initialised at ~/StrataVault/<repo>/
  scopes: decisions/ domain/ lessons/ procedural/ propositions/ pr-context/
```

## Step 2 · ask about Graphify

Graphify is a separate tool that builds a code structure graph from
your repo. With it, Strata unlocks **code_map**, drift detection,
aDR↔commit linkage, hot-file ranking, and verified `code_refs:` on
Notes. Without it, Strata still works. Minus code-graph awareness.

Ask the user (yes / no / later):

> Want to install Graphify now? It unlocks code-graph features
> (`code_map`, drift detection, ADR verification). Separate binary,
> runs locally. Skip if you're just trying Strata out.

### If yes

Show the install command. Don't run it yourself. Paths vary,
they may want sudo, they may already have it:

```text
# macOS via Homebrew
brew install graphifylabs/tap/graphify

# Or use the installer at https://graphifylabs.ai/install
```

Then offer to build the first graph:

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/strata" graphify
```

### If no / later

Acknowledge briefly. Mention `/strata:graphify` runs the build
Whenever they're ready. Continue to step 3.

## Step 3 · ask about bootstrap

If the repo has an existing `.planning/`, `docs/`, or similar
directory of markdown that predates Strata, the bootstrap pipeline
Can migrate that content into the vault. Cross-references claims
Against git history + the code graph; classifies into ADR / domain /
Lesson; writes notes with provenance.

Check first whether there's anything to bootstrap:

```bash
ls -la .planning docs 2>/dev/null | head -20
```

If there's substantial markdown content (>5 files), ask:

> I see existing planning docs at `<paths>`. Want to run
> `/strata:bootstrap` to migrate the durable content into the vault?
> It groups sibling files, dispatches workers in parallel, respects
> `.gitignore` + `.strataignore`. Takes a few minutes.

If they say yes, invoke `/strata:bootstrap`.

If there's nothing substantial, skip this step entirely. Don't ask.

## Final message

Single line summary:

```
Strata is ready. Three commands cover the common workflows:
  /strata:save     — capture branch context
  /strata:decide   — record a chosen option
  /strata:propose  — track an open question

Everything else auto-invokes on intent.
```

## Don't do

- Don't run the Graphify install yourself. Show the command, let the
  user run it.
- Don't run `/strata:bootstrap` unprompted. Even when planning docs
  exist, opt-in only. Bootstrap writes a lot of notes and should be
  a deliberate choice.
- Don't repeat the setup if the vault already exists. The prompts in
  steps 2 and 3 only fire on first init.
- Don't auto-invoke this skill if `<vault>/<repo>/INDEX.md` already
  exists. The SessionStart auto-init handles the silent path; this
  skill is for the explicit / first-time UX.

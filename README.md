# Strata

Branch- and PR-aware shared memory for engineering teams using Claude Code.

- **Vault outside the repo** — sync with whatever you already use (Obsidian
  Sync, Syncthing, iCloud, git).
- **Read-only MCP** built on the official Anthropic [`mcp` Python SDK](https://github.com/modelcontextprotocol/python-sdk).
  Writes go through user-typed slash commands; prompt injection can't
  silently mutate memory.
- **Pluggable secret/PHI lint** — patterns live in JSON preset packs
  (`secrets`, `phi-uk`, `pii-generic`). Easy to fork for your jurisdiction.
- **Private venv** — deps install into `.venv/` inside the plugin dir.
  Nothing leaks into the user's site-packages.
- **MIT licensed.** Open source. Contributions welcome.

## Why

Every Claude Code session starts cold. You re-explain the project, the
Decisions, the constraints. Strata persists that context to a shared vault
Keyed by **branch** and **repo**, so:

- The next session on the same branch starts warm.
- A teammate switching to your branch reads the same notes you did.
- ADRs live next to (but not inside) the code, reviewable in PRs only when
  they need to be auditable.
- Claude searches the vault via a fast SQLite FTS5 index instead of
  re-reading source files.

## Architecture

```
~/StrataVault/                # vault root — sync however you want
├── <repo-a>/                   # one namespace per repo
│   ├── decisions/              # ADRs (MADR format)
│   ├── lessons/                # post-incident / post-PR retrospectives
│   ├── domain/                 # vocabulary + invariants
│   ├── pr-context/<branch>/    # per-branch working notes
│   └── INDEX.md                # auto-generated
├── <repo-b>/
└── _shared/                    # cross-repo notes
```

| Capability | How |
|---|---|
| Branch-aware context | `SessionStart` + `PostToolUse(Bash)` hooks re-prime on `git checkout/switch` |
| Token-efficient recall | SQLite FTS5 via MCP — Claude pulls 1–3 KB per query |
| Survives compaction | `PreCompact` hook drops a breadcrumb |
| Save-before-you-leave nudge | `Stop` hook reminds you to `/strata:save` after 30+ min on a feature branch (cooldown'd, only nudges once per window) |
| Cross-repo knowledge | One vault, repo-namespaced subfolders + a `_shared/` scope |
| Sync flexibility | Vault is plain markdown — any sync mechanism works |

## Sharing the vault — pick a sync mechanism

| Mechanism | Pros | Cons |
|---|---|---|
| **Obsidian Sync** | E2E encrypted, fluid edits, no conflicts | Paid; data through Obsidian Inc. servers |
| **Syncthing** | Free, P2P, no third party | Per-device setup; weaker conflict semantics |
| **iCloud / Dropbox** | Built in for most users | No conflict semantics; vendor lock |
| **git** | Reviewable, blameable, free | Pull/push overhead; merge conflicts on heavy edits |

For regulated content (clinical, financial, legal), see [`SECURITY.md`](./SECURITY.md)
for hardening recommendations, short version: prefer git on private
Infrastructure, enable opt-in PHI/PII lint presets, wire a pre-push hook.

## Use it as an Obsidian vault (recommended)

The vault is plain markdown with YAML frontmatter and wikilinks. Point
Obsidian at the vault root and you get graph view, backlinks, Bases queries,
plugins, for free. Strata doesn't require Obsidian; it just plays well
with it. See [`OBSIDIAN.md`](./OBSIDIAN.md) for pairing with the public
Obsidian MCP servers.

### Obsidian vs SQLite FTS5

- **Obsidian is the human UI.**
- **SQLite FTS5 is Claude's index.** It lives in `${CLAUDE_PLUGIN_DATA}/index.db`,
  is never synced, and is rebuilt from disk on demand.

## Slash commands

- `/strata:init` — bootstrap this repo's vault namespace
- `/strata:bootstrap` — one-time onboarding: walk existing docs
  (CLAUDE.md, docs/, .planning/, .scratch/) and extract them as domain
  notes / ADRs / lessons. Idempotent via SHA256 state tracking.
- `/strata:resume` — re-prime context for the current branch
- `/strata:save <topic>` — write a session note
- `/strata:decide <title>` — create a new ADR (with `--supersedes`)
- `/strata:domain <concept>` — add a domain note
- `/strata:find <terms>` — grep the vault
- `/strata:lint [--preset ...]` — scan for secrets / PHI / PII
- `/strata:review` — vault health: stale ADRs, orphans, missing
  frontmatter, unresolved wikilinks
- `/strata:audit-config` — audit your project's CLAUDE.md / .claude/
  config for staleness (Anthropic's 3–6 month review cadence)
- `/strata:archive` — move merged branches' pr-context to `archive/`
- `/strata:export-to-repo` — copy a vault file into the host repo
- `/strata:forget` — move a file to `.trash/` with audit log
- `/strata:promote-to-pr` — post a session summary as a comment on the
  open PR (requires `gh` CLI; two-step with dry-run for safety)

## MCP tools (read-only)

| Tool | Purpose |
|---|---|
| `memory_search` | Paginated FTS5 (keyword) search |
| `memory_semantic_search` | Local CPU semantic search (fastembed); finds notes that mean similar things even when the words differ |
| `memory_insights` | Aggregate "what does the vault know about X" — combines FTS, decisions, domain notes, code symbols |
| `memory_get` | Read one file by path (sandboxed, symlink-rejected) |
| `pr_context_for_branch` | List vault notes for a branch (default: current) |
| `recent_decisions` | Last N ADRs (excludes superseded) |
| `recent_lessons` | Last N lessons |
| `domain_lookup` | Find domain notes by title term |
| `memory_status` | Index counts + db path |
| `current_pr` | Open PR for the current branch via `gh` |
| `decision_chain` | Walk the supersession chain for an ADR |
| `memory_graph` | Wikilink edges in/out of a note |
| `stale_decisions` | ADRs stuck in `proposed` longer than N days |
| `orphan_notes` | Notes with no wikilinks in or out |
| `code_graph_status` | Graphify graph.json metadata if present |

Plus **MCP resources** (additive): every indexed file is addressable as
`strata://<scope>/<filename>` for clients that browse resources.

No write tools, see [`SECURITY.md`](./SECURITY.md) for why. The
`current_pr` tool reads from GitHub via `gh` (the user's existing auth) and
is path-isolated from the vault.

## Lint presets

Patterns live in `presets/*.json`. Bundled:

- **`secrets`** (default) — AWS, GitHub, Slack, OpenAI, Anthropic tokens,
  JWTs, PEM private keys, connection-string passwords, GCP service accounts.
- **`pii`** (opt-in, jurisdiction-neutral) — credit cards (Luhn-validated),
  client/user-id literals, emails.
- **`phi-uk`** (opt-in) — NHS numbers (Mod-11 verified), UK postcodes.
- **`phi-us`** (opt-in) — SSN (with structural validation), DEA numbers
  (checksum-verified).
- **`financial-iban`** (opt-in) — IBAN account numbers (mod-97 verified
  with per-country length checks for the 70 IBAN-issuing countries).

Presets are forkable JSON. Add `phi-eu`, `phi-au`, `financial-pci`, or
Whatever your jurisdiction needs, see [`presets/phi-us.json`](./presets/phi-us.json)
for the format. PRs welcome.

Compose presets at the command line:

```bash
/strata:lint                                       # secrets only (default)
/strata:lint --preset secrets,pii                  # add generic PII
/strata:lint --preset secrets,pii,phi-uk           # UK healthcare team
/strata:lint --preset secrets,pii,phi-us           # US healthcare team
/strata:lint --preset secrets,my-org               # your fork
```

## Dependencies

Two pinned runtime deps, both small and widely audited:

- [`mcp`](https://pypi.org/project/mcp/) — the official Anthropic MCP SDK
- [`python-frontmatter`](https://pypi.org/project/python-frontmatter/) — YAML
  frontmatter parsing

Both install into `.venv/` inside the plugin directory on first session.
The user's system Python is untouched.

## Adopting Strata on a team

Anthropic's research found that successful Claude Code rollouts have
*"a dedicated infrastructure investment before broad access"* and
Explicit ownership, typically under developer-experience teams or a
New hybrid **"agent manager"** role. *"Without centralized DRI
Authority, knowledge will stay tribal and adoption will plateau."*

A pragmatic adoption path for Strata:

1. **One engineer (DRI) sets up the vault** — picks the sync mechanism
   (Obsidian Sync, Syncthing, git, …), runs `/strata:init` once per repo.
2. **Commit the team config** — drop [`examples/.claude/settings.json`](./examples/.claude/settings.json)
   into your repo's `.claude/` so the plugin is enabled the same way for
   everyone. Vault paths stay in `.claude/settings.local.json` (gitignored).
3. **Establish lint posture** — pick preset combos per data-sensitivity
   profile, wire `memory-lint.py --strict` into a `pre-push` hook.
4. **Quarterly audit** — `/strata:audit-config` + `/strata:review`
   on a shared cadence.
5. **For regulated industries** — cross-functional governance: approved
   skills list, required code review of new ADRs, limited initial access
   that expands as confidence builds.

## Install

See [`INSTALL.md`](./INSTALL.md).

## Security

See [`SECURITY.md`](./SECURITY.md) for the threat model, guarantees,
non-guarantees, and hardening recommendations for regulated data.

## Plays well with

Strata is one layer of [Anthropic's recommended five-layer harness](https://claude.com/blog/how-claude-code-works-in-large-codebases-best-practices-and-where-to-start)
(CLAUDE.md, hooks, skills, plugins, MCP). It composes with these companions:

### Graphify (code-structure graph)

[Graphify](https://graphifylabs.ai) builds a code-structure graph
(functions, modules, imports via tree-sitter) at `graphify-out/graph.json`.
It's a **different graph** from Strata's wikilink graph (notes → notes) —
they're complementary, not overlapping.

If Graphify has been run in the project, Strata detects
`graphify-out/graph.json` and:

- Surfaces it in the SessionStart primer (one line: nodes / edges / age)
- Exposes a `code_graph_status` MCP tool so Claude can sanity-check the
  graph (size, languages, build age) before querying it

We **do not** depend on Graphify's Python package, just the JSON it
Emits. If it's missing or unreadable, the primer and MCP tool silently
Report "not available". Install Graphify separately if you want it; pin
the version and use AST-only mode for regulated content.

### LSP servers (via `lsp-tools`)

Anthropic calls LSP *"one of the highest-value investments"* for
Multi-language codebases, with it, Claude follows calls to definitions
and traces references across files instead of pattern-matching on text.

Use the community [`lsp-tools`](https://github.com/Piebald-AI/claude-code-lsps)
Plugin: `/lsp-tools:lsp-setup` auto-detects your project's languages and
Wires up the official Anthropic LSP plugins (Python, TypeScript, Go, Rust,
java, C/C++, C#, PHP, Kotlin, Ruby, HTML/CSS, 11 languages as of late 2025).

We don't ship our own LSP setup — `lsp-tools` already does it well. Strata
+ `lsp-tools` + Graphify covers semantic code understanding (LSP), structural
Code map (Graphify), and team decision memory (Strata) without overlap.

### Obsidian MCPs

See [`OBSIDIAN.md`](./OBSIDIAN.md) for pairing notes on the two main
Public Obsidian MCP servers if you want Obsidian-specific operations
(linking, daily notes, canvas) on top of Strata's structured memory.

### Sub-agent patterns

Anthropic recommends *"split exploration from editing"* — read-only
Sub-agents map a subsystem and write findings to a file, then the main
Agent edits with the full picture. Strata's `/strata:save --kind
Investigation` is the natural sink for those findings: scoped to the
Current branch, indexed in FTS5, queryable later via `memory_search`.

## What's intentionally NOT here

- **No bundled Obsidian MCP.** Pick one yourself — see [`OBSIDIAN.md`](./OBSIDIAN.md).
- **No write tools over MCP.** Writes are user-confirmable by design.
- **No background monitors.** Hooks and explicit skills only.
- **No chat-history import.** Bulk-importing chats into shared memory is a
  PII risk and a search-noise multiplier.
- **No telemetry, no network calls.** Greppable in the source.

## Roadmap

- Wikilink graph via [`obsidianmd-parser`](https://pypi.org/project/obsidianmd-parser/)
  + new `memory_graph(slug)` MCP tool
- Decision lifecycle — parse `supersedes`/`superseded_by`; new
  `decision_chain` MCP tool; INDEX shows live decisions only
- `strata:export-to-repo` — promote a vault decision into the host repo's
  `docs/adr/` for audit trails
- Optional confirmation-gated MCP write tools once Claude Code core supports
  the UI for it
- Per-branch context TTL (auto-archive merged branches' notes)
- More lint presets — `phi-eu` (GDPR Article 9 special-category data),
  `phi-au` (Medicare numbers), `financial-pci`, `tax-ids`
- pytest suite + GitHub Actions matrix across Python 3.10–3.14

## Contributing

Issues and PRs welcome. Keep it stdlib-leaning, keep the threat model intact,
and add new functionality behind opt-in flags rather than enabling by default.

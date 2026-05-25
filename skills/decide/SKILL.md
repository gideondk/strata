---
name: strata:decide
description: Create a Markdown ADR in the vault's decisions/ scope. Invoke this autonomously the moment a non-trivial choice is made, a trade-off that locks something in, a constraint discovered the hard way, a choice between two reasonable options where future readers will wonder why. Don't wait for the user to ask. Pair with --supersedes when replacing an earlier decision. Skip for routine implementation choices fully explained by the code itself.
---

# strata:decide

ADRs (Architectural Decision Records) capture **why** something is the way it
is. They're durable team memory, code rots, ADRs explain it.

## When to use

- A choice between two reasonable options where future readers will wonder why.
- A constraint discovered the hard way that should be remembered.
- A trade-off that locks something in.

Not for: routine implementation choices, style preferences, or anything fully
Explained by the code itself.

## How

User runs `/strata:decide <title>`. You:

1. Draft the body using the MADR sections: **Context**, **Decision**,
   **Consequences**, **Alternatives considered**. Be concrete. No fluff.
2. Pick the status: `proposed` (default, opens a discussion), `accepted`
   (the team has agreed), or `superseded`/`rejected`/`deprecated`.
3. Run:

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/run-python.sh" \
  "${CLAUDE_PLUGIN_ROOT}/scripts/new-decision.py" \
  --title "<title>" --status proposed <<'STRATA_ADR'
<body — Context / Decision / Consequences / Alternatives>
STRATA_ADR
```

If no body is provided on stdin, the script writes the template from
`templates/decision.md` so the user can fill it in.

## Superseding a prior decision

If this ADR replaces an earlier one, pass `--supersedes` (repeatable). The
Predecessor's `superseded_by` frontmatter is updated automatically, its
Status flips to `superseded`, and the INDEX hides it from the "live" list.
The chain is queryable via the `decision_chain` MCP tool.

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/run-python.sh" \
  "${CLAUDE_PLUGIN_ROOT}/scripts/new-decision.py" \
  --title "Adopt SQLiteData" --status accepted \
  --supersedes "2026-05-15-use-core-data" \
  --supersedes "2026-04-02-swift-data-migration" <<'EOF'
<body>
EOF
```

Predecessor refs accept any of: slug (`2026-05-15-use-core-data`), bare
Filename (`2026-05-15-use-core-data.md`), or vault-relative path
(`decisions/2026-05-15-use-core-data.md`).

## Promoting to the repo (optional)

For decisions that should be reviewable in code (regulatory, clinical, or any
Audit-relevant), copy the ADR into the host repo's `docs/adr/` and open a PR.
The vault keeps the canonical version; the repo copy is the audit anchor.

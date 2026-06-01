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
3. **Recall before you write — check for an existing decision first.** Run the
   dedup precheck so you don't fork a parallel ADR for a choice that's already
   recorded (the "agents battling on ADRs" failure):

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/run-python.sh" \
  "${CLAUDE_PLUGIN_ROOT}/scripts/new-decision.py" \
  --title "<title>" --check-only <<'STRATA_ADR'
<the body you drafted>
STRATA_ADR
```

   It prints JSON `{recommendation, candidates}` and writes nothing to the
   vault (it may refresh the disposable index cache). Run it on its own —
   `--check-only` is a no-op alongside `--supersedes`/`--no-dedup`. Adjudicate:

   - **`clear`** → no overlap; proceed to step 4 (ADD).
   - **`warn` / `block`** → read the candidate(s) and decide, surfacing it to
     the user:
     - **UPDATE** — same decision, just refined → *edit that note*, don't create
       a new one.
     - **SUPERSEDE** — this replaces an earlier decision → write with
       `--supersedes <slug>` (see below).
     - **NO-OP** — already captured → write nothing; tell the user.
     - **ADD** — genuinely distinct despite the overlap → write with `--ack-new`
       (a `block` refuses to write without it).

   **Use the candidates to ground the draft.** Even on `clear`, the precheck
   returns the nearest existing notes. Before writing, skim the top 2-3: match
   their section structure, reuse house terminology, and `[[wikilink]]` the
   genuinely related ones in your body. A well-linked draft beats an orphan.

4. Write it (ADD):

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/run-python.sh" \
  "${CLAUDE_PLUGIN_ROOT}/scripts/new-decision.py" \
  --title "<title>" --status proposed <<'STRATA_ADR'
<body — Context / Decision / Consequences / Alternatives>
STRATA_ADR
```

If no body is provided on stdin, the script writes the template from
`templates/decision.md` so the user can fill it in. If the dedup gate refuses
(`block`), its message names the flag that resolves it — never blindly bypass
with `--no-dedup`; that escape hatch is for batch flows, not interactive use.

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

### Expire-and-rewrite, don't delete

Strata never deletes a superseded decision — supersession flips status and
hides it from the live list, but the note stays as history. Two refinements
borrowed from temporal knowledge-graph systems (Graphiti/Zep):

- **Rewrite the predecessor's lead to past tense** when you supersede it, so a
  future reader who lands on the old ADR isn't misled into thinking it's
  current. One line is enough: prepend *"Superseded by [new] on <date> — we
  used to ... ."* via `/strata:correct <old> --reason "superseded"`. Don't
  rewrite the whole body; the original reasoning is the point of keeping it.
- **Capture when a fact stopped being TRUE, not just when you recorded it.**
  For an `/strata:invalidate`, pass `--invalid-since YYYY-MM-DD` if the
  decision was actually wrong from an earlier date — bi-temporal validity
  answers "how long were we operating on a false assumption?", which a single
  `invalidated_at` (the bookkeeping timestamp) can't.

Do NOT add a write-time consistency gate that *rejects* a contradicting
decision — contested/contradictory decisions are allowed to coexist (that's
what the proposition debate substrate is for); resolve them by superseding,
not by blocking the write.

## Promoting to the repo (optional)

For decisions that should be reviewable in code (regulatory, clinical, or any
Audit-relevant), copy the ADR into the host repo's `docs/adr/` and open a PR.
The vault keeps the canonical version; the repo copy is the audit anchor.

## Keep it quiet

The `--check-only` JSON is for you to adjudicate ADD/UPDATE/SUPERSEDE/NO-OP —
read it, don't recite it back. Once the ADR is written, the one-line receipt
(`✓ Strata: recorded decision …`) is the confirmation; no step-by-step narration
and no pasting script paths or raw output to the user.

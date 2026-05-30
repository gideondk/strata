---
name: strata:propose
description: Capture an OPEN question or contested position that hasn't settled, tracking it open → contested → converging → settled. Invoke autonomously when the user says "we don't know yet whether X", "open question is Y", "we're split on Z", "I'm proposing X but not sure", "let's track this debate". Skip once a choice is locked in — for a decided option use /strata:decide; for a stable definition use /strata:domain. When it resolves, promote with --settled-as or --refuted-as.
---

# strata:propose

The "open question" scope. Closes the gap between **what we know
(domain)**, **what we've chosen (decisions)**, **what we did (pr-context)**,
and **what we did wrong (lessons)**, with a fourth: **what we're still
Figuring out**.

## When to use

| Situation | Skill |
|---|---|
| Open question, multiple positions, no choice yet | `strata:propose` |
| Chosen option with reasoning | `strata:decide` |
| Stable concept / vocabulary | `strata:domain` |
| Retrospective fact | `strata:save --scope lessons` |
| In-flight branch work | `strata:save` |

A proposition is **explicitly time-bounded**. It exists to be resolved.
A proposition that never gets settled or refuted is itself a signal.

## How

### Create

```bash
cat <<'EOF' | "${CLAUDE_PLUGIN_ROOT}/bin/run-python.sh" \
    "${CLAUDE_PLUGIN_ROOT}/scripts/new-proposition.py" \
    --title "Should we move to Postgres for tenant data?"
# Should we move to Postgres for tenant data?

## What we're trying to figure out
<context — why this is open>

## Positions on the table
- Stay on SQLite: <reasons>
- Move to Postgres: <reasons>

## What evidence would settle this
- <what we'd need to know>
EOF
```

Default status is `open`. Pass `--status contested` if multiple positions
are actively defended, or `--status converging` if one is winning.

### Add a position (the debate log)

When someone weighs in on an open proposition, append a position — don't
rewrite the note. Each entry is attributed, dated, and append-only:

```bash
cat <<'EOF' | "${CLAUDE_PLUGIN_ROOT}/bin/run-python.sh" \
    "${CLAUDE_PLUGIN_ROOT}/scripts/new-proposition.py" \
    --update propositions/2026-05-25-should-we-move-to-postgres.md \
    --position --stance against
Postgres adds an ops burden we can't staff. Evidence: our last two
incidents were both connection-pool exhaustion under the managed PG.
Critique of the "Move to Postgres" position: it assumes a DBA we don't have.
EOF
```

`--stance` is `for` | `against` | `alternative` | `refine`. An `against` or
`alternative` stance bumps an `open` proposition to `contested` automatically.

**Run a healthy debate (this matters — the research is blunt about it):**

- **Draft independently first.** Form your own position before reading the
  others, then append it. Don't anchor on the first voice.
- **Cap it at ~2 rounds.** More rounds *degrade* quality (problem drift, and
  agents converging on a confident-but-wrong consensus). If it's not
  converging in two passes, it needs a human, not another round.
- **Ground every position in evidence** — a file, a test, an incident, a
  measurement. A position that adds no new evidence is a signal to *stop*, not
  another turn.
- **Disagreement is the point.** If every position agrees, you're seeing
  sycophancy, not consensus — assign someone the critic's seat.
- **A human settles it.** Agents surface and sharpen the question; the
  `--settled-as` / `--refuted-as` promotion is a human call.

### Promote (when settled)

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/run-python.sh" \
  "${CLAUDE_PLUGIN_ROOT}/scripts/new-proposition.py" \
  --update propositions/2026-05-25-should-we-move-to-postgres.md \
  --settled-as "decisions/2026-05-30-use-postgres-tenant-data.md"
```

Bidirectional intent: the ADR has its own reasoning; the proposition
records the question that led to it. The forward link lets future
Readers walk back from "we use Postgres" to "we considered the
Alternatives in this proposition."

### Retire (when refuted)

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/run-python.sh" \
  "${CLAUDE_PLUGIN_ROOT}/scripts/new-proposition.py" \
  --update propositions/2026-05-25-foo.md \
  --refuted-as "lessons/2026-06-02-why-we-didnt.md"
```

## Status lifecycle

```
   open  ─→  contested  ─→  converging  ─→  settled-as-decision
                                       └─→  refuted-as-lesson
```

Open/contested/converging propositions older than a day surface in the
`/strata:dashboard` "Awaiting your input" section, and (batched) on the
commit/Stop nudge. A long-open proposition is a smell — usually it means the
team is avoiding the decision.

## Why this scope earned its place

Other memory plugins (smcady/Cairn, claude-mem) track decision lifecycle
via opaque graph state or compressed summaries. Propositions in `strata`
are **plain markdown files** with `status:` frontmatter, auditable,
diffable, syncable, readable in Obsidian. Same lifecycle tracking, in
Durable form.

## Don't do

- Don't propose what's already decided. Use `strata:decide` for chosen
  options.
- Don't propose what's stable. Use `strata:domain` for "what is X here."
- Don't propose what's purely branch-scoped scratch. Use `strata:save`.
- Don't leave propositions open forever — once aged, they resurface in the
  dashboard and on the nudge until you settle or refute them.

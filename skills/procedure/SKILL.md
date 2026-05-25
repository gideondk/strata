---
name: strata:procedure
description: Capture a procedural note, a recipe, workflow, checklist, or "how we do things here" template. Procedural memory is the third leg of the episodic/semantic/procedural triad; complements `domain/` (concepts) and `decisions/` (chosen options). Invoke autonomously when the user says "document this workflow", "save how we do X", "add a procedure for Y", "checklist for Z", or describes a step-by-step process worth keeping. Skip for one-off scripts, those belong in code or scratch.
---

# strata:procedure

The "how" notes. Distinct from domain (the "what") and decisions (the "why").
A procedure tells a future engineer (or future Claude) the sequence of
Steps to reproduce something.

## What goes here

- Onboarding checklists: "first day on this codebase"
- Service templates: "how to add a new bounded context"
- Release runbooks: "shipping a hotfix"
- Test patterns: "writing a new aggregate test"
- Migration recipes: "moving a service to the new pattern"
- Common debugging flows: "what to check when X breaks"

What does NOT belong:
- One-off scripts → keep in code
- Decisions WHY you do it this way → `/strata:decide`
- What a thing IS → `/strata:domain`
- "What happened on this branch" → `/strata:save`

## How

User runs `/strata:procedure <title>` or you autonomously identify a
Workflow worth capturing. You:

1. Compose the procedure as a numbered step list with prerequisites + a
   verification step.
2. Invoke:

```bash
cat <<'EOF' | "${CLAUDE_PLUGIN_ROOT}/bin/run-python.sh" \
    "${CLAUDE_PLUGIN_ROOT}/scripts/new-procedure.py" \
    --title "<title>"
# <Title>

## Prerequisites
- ...

## Steps
1. ...
2. ...

## Verify
- ...

## When to use this procedure
<one sentence>
EOF
```

Lands in `<vault>/<repo>/procedural/<slug>.md`.

## Shape

Always: title, prerequisites, numbered steps, verification, applicability.
The verification step is what makes it executable, without it, the
Procedure is just narrative.

If a step references code, use backticks (`OrderAggregate.cs`), those get
Verified against the code graph in `/strata:review`.

## Don't do

- Don't write a procedure for something that happens once. Procedures are
  for the recurring shape.
- Don't dump command transcripts. Synthesise into "do A, then B, then verify C."
- Don't write a procedure when a decision is what's needed. "We use Postgres"
  is a decision; "how to add a new Postgres-backed table" is a procedure.

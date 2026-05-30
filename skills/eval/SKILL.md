---
name: strata:eval
disable-model-invocation: true
description: Measure whether a retrieval/search change actually improved results, using a committed golden set (recall@k + MRR, fully local, no LLM judge). Use when the user says "did search get better or worse", "prove the ranking improved", "check for retrieval regressions", or "compare with and without rerank". Command-only — run it explicitly as /strata:eval.
---

# strata:eval

A regression guard + measuring stick for vault recall. It runs a small,
committed set of `query → expected notes` cases through the same retrieval the
`recall` tool uses, and reports **recall@k** and **MRR**.

## The golden set

Lives at `<vault>/<repo>/.eval/golden.json` (commit it — it's versioned with
the vault):

```json
{
  "cases": [
    {"query": "rate limiting policy",
     "expected": ["decisions/2026-05-21-token-bucket.md"],
     "scope": "decisions"}
  ]
}
```

`scope` is optional (null/omitted = all scopes). 20–50 hand-picked cases is
plenty. Seed them from queries you actually run, or from the usage ledger's
top-recalled notes.

## Run it

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/run-python.sh" \
  "${CLAUDE_PLUGIN_ROOT}/scripts/eval.py" -k 5
```

## Measure the rerank lift

Compare the pipeline with and without the cross-encoder rerank:

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/run-python.sh" \
  "${CLAUDE_PLUGIN_ROOT}/scripts/eval.py" -k 5 --sweep
```

`--sweep` runs the golden set rerank-OFF then rerank-ON and prints both rows +
the lift, so the decision is a number. If the lift is zero (or negative) on your
set, leave rerank off (it's off by default) — don't pay the per-call model load
for no gain.

## When to run

- Before/after any retrieval change (rerank, RRF weighting, a new scope).
- Periodically, as a regression guard — a drop means recall quality slipped.

---
name: strata:eval
description: Measure recall quality offline against a committed golden set (query → expected note paths). Reports recall@k + MRR through the real hybrid pipeline (incl. the cross-encoder rerank). Use to prove a retrieval change helped, guard against regressions, or compare with/without rerank. No LLM judge — pure ranking metrics, fully local.
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
  "${CLAUDE_PLUGIN_ROOT}/scripts/eval.py" -k 5 --no-rerank   # baseline
"${CLAUDE_PLUGIN_ROOT}/bin/run-python.sh" \
  "${CLAUDE_PLUGIN_ROOT}/scripts/eval.py" -k 5               # + rerank
```

If rerank doesn't move recall@k / MRR up on your set, leave it off
(`STRATA_DISABLE_RERANK=1`) — don't pay the latency for no gain.

## When to run

- Before/after any retrieval change (rerank, RRF weighting, a new scope).
- Periodically, as a regression guard — a drop means recall quality slipped.

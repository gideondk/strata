# Temporal / supersession benchmark

The move-1 proof harness. Answers the one question that defines Strata's claimed
retrieval edge: **when a current note and a lexically-similar superseded note
both match a query, does the current one win — and is it the supersession
demotion doing it, or just lexical luck?**

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/run-python.sh" \
  "${CLAUDE_PLUGIN_ROOT}/scripts/eval_temporal.py"        # human-readable
"${CLAUDE_PLUGIN_ROOT}/scripts/eval_temporal.py" --json   # machine-readable
```

It builds a throwaway vault from the committed `cases.json`, indexes it, and
runs recall twice — `_DEMOTE_SUPERSEDED` ON vs OFF — holding everything else
constant. Two metrics, each with a Wilson 95% CI:

- **stale-suppression** — does the current note outrank every superseded note
  that surfaced. The metric `recall@k` is blind to (returning the stale note
  still counts as a top-k hit). This is the moat metric.
- **current-recall@k** — does the current note make the top-k at all (guards
  against the demotion hurting findability).

The headline is the ON-vs-OFF **delta** on stale-suppression, with a
Beta-Binomial `P(ON > OFF)`.

## What it currently shows, and what it does NOT

On the committed pilot (6 hand-built cases) the demotion flips stale-suppression
from **0/6 to 6/6** with non-overlapping CIs — `P(ON>OFF) ≈ 1.0`.

Read that honestly:

- It **proves the mechanism**: whenever a stale note competes lexically with the
  current one, the demotion deterministically puts current on top, at no cost to
  recall.
- It does **not** establish **prevalence** — the cases are deliberately *hard*
  (superseded notes are term-dense on purpose to isolate the lever). How often a
  stale note actually out-competes the current one in real corpora is unmeasured.
- n=6 is **underpowered**. The CI on the ON arm is `[0.61, 1.0]`. Grow the set
  and re-run a power analysis before treating any number as established.

## To grow it (the seq-4 work this seeds)

Add cases to `cases.json` (current + superseded evidence + a query that is a
*paraphrase*, never copied from the bodies). Keep the construction leakage-clean
and label the achieved power. A smaller honest set beats a large sloppy one — a
single credible refutation of a sloppy headline number is fatal.

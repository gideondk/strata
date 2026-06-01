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

On the committed set (19 hand-built cases, leakage-checked) the demotion lifts
stale-suppression from **7/19 (OFF) to 19/19 (ON)**, with non-overlapping 95%
CIs (`OFF [0.19, 0.59]`, `ON [0.83, 1.0]`). Because it's a **paired** ablation
(every case runs both arms) the correct test is exact McNemar on the discordant
pairs: **12 ON-only wins vs 0, exact p ≈ 0.0005** — significant at n=19 without
padding the set. current-recall@k is 19/19 in both arms, so the demotion costs
nothing on findability.

Read that honestly:

- It **proves the mechanism**: whenever a stale note competes with the current
  one, the demotion deterministically puts current on top, at no cost to recall.
  The demotion changes the outcome in **12 of 19** cases.
- It does **not** establish real-world **prevalence**. The superseded notes are
  deliberately term-dense to make the contest hard; ~37% of the time the current
  note already wins without demotion. How often the contest actually arises in
  real corpora is unmeasured.
- n=19 is still **modest**. Grow the set and run a proper power analysis before
  headlining a delta. The harness prints a leakage check (longest verbatim
  query/note word-run) so contamination stays visible — keep it in the
  paraphrase range (< 4).

## To grow it (the seq-4 work this seeds)

Add cases to `cases.json` (current + superseded evidence + a query that is a
*paraphrase*, never copied from the bodies). Keep the construction leakage-clean
and label the achieved power. A smaller honest set beats a large sloppy one — a
single credible refutation of a sloppy headline number is fatal.

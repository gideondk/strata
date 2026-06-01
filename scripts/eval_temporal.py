#!/usr/bin/env python3
"""Temporal / supersession retrieval benchmark — the move-1 proof harness.

The plain eval (eval.py) asks "is the right note in the top-k?". That CANNOT
see a supersession failure: returning a *stale* note still counts as a top-k
hit. This harness asks the question that actually defines Strata's claimed edge:

    when a CURRENT note and a lexically-similar SUPERSEDED note both match a
    query, does the current one win — and is that because of our supersession
    demotion, or just lexical luck?

Construction follows LongMemEval's fact-decomposition idea (arXiv:2410.10813):
each case is one fact with timestamped current vs superseded evidence, dropped
into a shared distractor pile. The cases live in a COMMITTED json fixture and
are materialised into a throwaway vault at run time — so the whole benchmark is
reproducible from a clone, not dependent on anyone's private vault (the gap the
strategy review flagged).

Two metrics, reported per arm with Wilson 95% CIs:
  * current-recall@k  — did the current note make the top-k at all.
  * stale-suppression — did the current note rank ABOVE every superseded note
                        that surfaced (the metric recall@k is blind to).

One-factor ablation: ON = recall._DEMOTE_SUPERSEDED True, OFF = False; everything
else held constant. The headline is the ON-vs-OFF delta on stale-suppression,
with a Beta-Binomial P(ON>OFF). That is the claim a whole-system-accuracy paper
(e.g. Zep's) structurally cannot isolate.

Honest by construction: a small hand-built pilot set is UNDERPOWERED. Read the
CI widths, not the point estimates. Grow the set (and re-run a power check)
before treating any delta as established.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path


def _max_verbatim_run(cases: list[dict]) -> int:
    """Worst-case train/test leakage measured the right way for short queries:
    the longest CONTIGUOUS run of words a query shares verbatim with its own
    evidence bodies. Sharing topic nouns is fine and expected (that's how a
    query finds a note); leakage is copying a *phrase*. A paraphrase yields 1-2;
    a query lifted from a note yields 4+."""
    def words(s: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", (s or "").lower())

    def longest_run(q: list[str], b: list[str]) -> int:
        best = 0
        for i in range(len(q)):
            for j in range(len(b)):
                run = 0
                while (i + run < len(q) and j + run < len(b)
                       and q[i + run] == b[j + run]):
                    run += 1
                best = max(best, run)
        return best

    worst = 0
    for c in cases:
        q = words(c["query"])
        bodies = [c["current"]["body"]] + [o["body"] for o in c.get("superseded", [])]
        for b in bodies:
            worst = max(worst, longest_run(q, words(b)))
    return worst


def _default_cases() -> Path:
    return Path(__file__).resolve().parent.parent / "eval" / "temporal" / "cases.json"


def _materialise(mem, cases: list[dict]) -> None:
    """Write each case's current/superseded evidence + shared distractors into
    the temp vault's decisions/ scope as real notes the indexer will pick up."""
    from lib import write_text
    dec = mem / "decisions"
    dec.mkdir(parents=True, exist_ok=True)

    def note(slug: str, title: str, status: str, body: str, date: str) -> None:
        write_text(dec / f"{slug}.md",
                   f"---\ntitle: {title}\nstatus: {status}\ndate: '{date}'\n---\n\n{body}\n")

    for c in cases:
        fid = c["fact_id"]
        cur = c["current"]
        note(f"{fid}-current", cur["title"], cur.get("status", "accepted"),
             cur["body"], cur.get("date", "2026-05-01"))
        for i, old in enumerate(c.get("superseded", [])):
            note(f"{fid}-old-{i}", old["title"], old.get("status", "superseded"),
                 old["body"], old.get("date", "2025-06-01"))
    # Shared distractors (defined once at top level) pad the corpus.
    return None


def _eval_case(recall, query: str, current_path: str, superseded_paths: list[str],
               k: int) -> tuple[bool, bool]:
    """Return (current_in_topk, suppression_ok) for one query at the current
    _DEMOTE_SUPERSEDED setting."""
    rows, _ = recall._hybrid_search(query, None, k)
    paths = [r.get("path") for r in rows]
    if current_path not in paths:
        return False, False
    cur_rank = paths.index(current_path)
    sup_ranks = [paths.index(p) for p in superseded_paths if p in paths]
    # Suppression holds when the current note is present AND outranks every
    # superseded note that surfaced (a superseded note absent from top-k is,
    # trivially, suppressed).
    suppression_ok = all(cur_rank < s for s in sup_ranks)
    return True, suppression_ok


def run(cases_path: Path, k: int, as_json: bool) -> int:
    raw = json.loads(cases_path.read_text(encoding="utf-8"))
    meta = raw.get("meta", {})
    cases = raw["cases"]
    distractors = raw.get("distractors", [])

    tmp = Path(tempfile.mkdtemp(prefix="strata-eval-temporal-"))
    try:
        (tmp / "vault").mkdir()
        (tmp / "repo").mkdir()
        (tmp / "data").mkdir()
        os.environ["STRATA_VAULT_PATH"] = str(tmp / "vault")
        os.environ["CLAUDE_PROJECT_DIR"] = str(tmp / "repo")
        os.environ["CLAUDE_PLUGIN_DATA"] = str(tmp / "data")
        os.environ["STRATA_REPO_NAME"] = "evaltemporal"

        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import db
        import eval_stats as es
        import lib_loader  # noqa: F401
        import recall
        from lib import memory_dir, write_text

        mem = memory_dir()
        _materialise(mem, cases)
        for i, d in enumerate(distractors):
            (mem / "decisions").mkdir(parents=True, exist_ok=True)
            write_text(mem / "decisions" / f"distractor-{i}.md",
                       f"---\ntitle: {d.get('title', 'note')}\nstatus: accepted\n---\n\n{d['body']}\n")
        db.reindex(force=True)
        try:
            import embeddings
            if embeddings.available():
                embeddings.reindex(force=True)
        except Exception:
            pass

        results: dict[str, dict] = {"on": {"recall": 0, "supp": 0},
                                    "off": {"recall": 0, "supp": 0}}
        per_case = []
        n = len(cases)
        for c in cases:
            cur_path = f"decisions/{c['fact_id']}-current.md"
            sup_paths = [f"decisions/{c['fact_id']}-old-{i}.md"
                         for i in range(len(c.get("superseded", [])))]
            row = {"fact_id": c["fact_id"]}
            for arm, flag in (("on", True), ("off", False)):
                recall._DEMOTE_SUPERSEDED = flag
                rec, supp = _eval_case(recall, c["query"], cur_path, sup_paths, k)
                results[arm]["recall"] += int(rec)
                results[arm]["supp"] += int(supp)
                row[arm] = {"current_recall": rec, "suppression": supp}
            per_case.append(row)

        supp_delta = es.prob_improvement(results["on"]["supp"], n,
                                         results["off"]["supp"], n)
        rec_delta = es.prob_improvement(results["on"]["recall"], n,
                                        results["off"]["recall"], n)
        supp_on = es.fmt_rate(results["on"]["supp"], n)
        supp_off = es.fmt_rate(results["off"]["supp"], n)
        rec_on = es.fmt_rate(results["on"]["recall"], n)
        rec_off = es.fmt_rate(results["off"]["recall"], n)
        leak = _max_verbatim_run(cases)
        summary = {
            "k": k, "n_cases": n,
            "query_leakage_max_run_words": leak,
            "current_recall@k": {"on": rec_on, "off": rec_off,
                                 "P(on>off)": round(rec_delta, 3)},
            "stale_suppression": {"on": supp_on, "off": supp_off,
                                  "P(on>off)": round(supp_delta, 3)},
        }
        if as_json:
            print(json.dumps({"summary": summary, "per_case": per_case,
                              "meta": meta}, indent=2))
        else:
            print(f"# Temporal benchmark — {n} case(s), k={k}")
            if meta.get("note"):
                print(f"\n_{meta['note']}_\n")
            print("## stale-suppression (the moat metric)")
            print(f"- ON : {supp_on}")
            print(f"- OFF: {supp_off}")
            print(f"- P(ON beats OFF): {supp_delta:.3f}")
            print("\n## current-recall@k")
            print(f"- ON : {rec_on}")
            print(f"- OFF: {rec_off}")
            leak_flag = ("  (!) high - a query may be copied from a note"
                         if leak >= 4 else "  (paraphrase range, OK)")
            print(f"\n_leakage: longest verbatim query/note word-run = "
                  f"{leak}{leak_flag}_")
            print("_Modest set - read the CI widths, not the point estimates. "
                  "Grow further + re-check power before headlining a delta._")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases", type=Path, default=_default_cases())
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if not args.cases.exists():
        print(f"[strata] no temporal cases at {args.cases}", file=sys.stderr)
        return 2
    return run(args.cases, args.k, args.json)


if __name__ == "__main__":
    raise SystemExit(main())

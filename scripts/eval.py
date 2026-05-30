#!/usr/bin/env python3
"""Offline retrieval-quality harness for the Strata vault.

Runs a committed golden set (query → expected note paths) through the REAL
recall pipeline (`recall._hybrid_search`, incl. the cross-encoder rerank when
available) and reports recall@k + MRR. Fully local, no LLM judge — pure
ranking metrics. Use it to:
  - measure the lift from a change (e.g. the rerank stage) before/after,
  - guard against retrieval regressions,
  - calibrate thresholds against a real number instead of a guess.

Golden set lives at `<vault>/<repo>/.eval/golden.json`:
    {"cases": [
        {"query": "rate limiting policy",
         "expected": ["decisions/2026-05-21-token-bucket.md"],
         "scope": null}
    ]}
`scope` is optional (null = all scopes).
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

import lib_loader  # noqa: F401
from lib import memory_dir


def golden_path(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit)
    return memory_dir() / ".eval" / "golden.json"


def load_cases(path: Path) -> list[dict]:
    """Load + validate golden cases. Raises ValueError on a malformed file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = data.get("cases") if isinstance(data, dict) else data
    if not isinstance(cases, list):
        raise ValueError("golden set must be a list of cases (or {cases: [...]})")
    out: list[dict] = []
    for c in cases:
        if not isinstance(c, dict) or "query" not in c or "expected" not in c:
            raise ValueError(f"each case needs 'query' + 'expected': {c!r}")
        exp = c["expected"]
        out.append({
            "query": str(c["query"]),
            "expected": [exp] if isinstance(exp, str) else [str(e) for e in exp],
            "scope": c.get("scope"),
        })
    return out


def _score_case(case: dict, k: int) -> dict:
    """Run one case through the real recall pipeline and score it."""
    import recall
    rows, _ = recall._hybrid_search(case["query"], case.get("scope"), k)
    got = [r["path"] for r in rows[:k]]
    expected = set(case["expected"])
    found = expected & set(got)
    recall_at_k = len(found) / len(expected) if expected else 0.0
    rr = 0.0
    for i, p in enumerate(got):
        if p in expected:
            rr = 1.0 / (i + 1)
            break
    return {
        "query": case["query"],
        "expected": sorted(expected),
        "got": got,
        "recall_at_k": recall_at_k,
        "rr": rr,
        "miss": sorted(expected - found),
    }


def evaluate(cases: list[dict], k: int = 5) -> dict:
    results = [_score_case(c, k) for c in cases]
    n = len(results) or 1
    return {
        "k": k,
        "cases": len(results),
        "recall_at_k": sum(r["recall_at_k"] for r in results) / n,
        "mrr": sum(r["rr"] for r in results) / n,
        "per_case": results,
    }


def format_report(report: dict) -> str:
    out = [
        f"# Strata eval — {report['cases']} case(s), k={report['k']}",
        "",
        f"- **recall@{report['k']}**: {report['recall_at_k']:.3f}",
        f"- **MRR**: {report['mrr']:.3f}",
        "",
        "## Misses",
    ]
    misses = [r for r in report["per_case"] if r["miss"]]
    if not misses:
        out.append("_none — every expected note was retrieved_")
    else:
        for r in misses:
            out.append(f"- `{r['query']}` → missing {r['miss']}")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", default=None,
                    help="Path to the golden set JSON "
                         "(default <vault>/<repo>/.eval/golden.json).")
    ap.add_argument("-k", type=int, default=5, help="recall@k cutoff.")
    ap.add_argument("--rerank", action="store_true",
                    help="Measure WITH the cross-encoder rerank (off by "
                         "default) — compare against a plain run to see the lift.")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    import recall
    recall._RERANK_ENABLED = args.rerank

    # Make sure semantic embeddings exist (offline) so we measure the real
    # hybrid pipeline, not an accidental FTS-only run.
    with contextlib.suppress(Exception):
        import embeddings
        embeddings.warm()

    if not memory_dir().exists():
        print("_vault not initialised — run `/strata:init` first_",
              file=sys.stderr)
        return 2

    gp = golden_path(args.golden)
    if not gp.exists():
        print(f"_no golden set at `{gp}` — create one to measure recall "
              f"quality (see scripts/eval.py docstring for the format)._",
              file=sys.stderr)
        return 2

    try:
        cases = load_cases(gp)
    except (ValueError, json.JSONDecodeError) as e:
        print(f"[strata] error: bad golden set: {e}", file=sys.stderr)
        return 2

    if not cases:
        print(f"_golden set at `{gp}` has no cases — add some to measure "
              f"recall quality._", file=sys.stderr)
        return 2

    report = evaluate(cases, k=args.k)
    if args.json:
        print(json.dumps(report))
    else:
        print(format_report(report))
    return 0


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        sys.exit(main())

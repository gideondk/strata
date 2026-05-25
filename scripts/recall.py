#!/usr/bin/env python3
"""Unified recall — invoked by the memory-recall subagent.

Three layers of progressive disclosure:
  Layer 1 (~50-100 tokens/hit): path + title + 1-line excerpt + score
  Layer 2 (~200 tokens/hit): + adjacent notes (timeline) + nearby links
  Layer 3 (full body): top hit only, capped at 4KB

Ranks by FTS bm25 + relevance score (recency, links, supersession).
Honours --since, --scope filters. Excludes invalidated by default.
"""
from __future__ import annotations

import argparse
import json
import sys

import db
import lib_loader  # noqa: F401
from lib import memory_dir


def _budget_truncate(text: str, char_budget: int) -> str:
    if len(text) <= char_budget:
        return text
    cut = text[: char_budget - 3]
    return cut.rstrip() + "..."


_RRF_K = 60  # standard RRF constant from the original paper


def _hybrid_search(query: str, scope: str | None,
                   limit: int) -> tuple[list[dict], int]:
    """FTS5 BM25 + fastembed semantic, merged via Reciprocal Rank Fusion.

    RRF: score(d) = sum over each ranker of 1 / (k + rank_d). k=60.
    Falls back to FTS-only if semantic layer is unavailable
    (fastembed not installed, no model downloaded, etc.).
    """
    db.reindex(force=False)
    terms = query.strip().split()
    fts_rows, total = db.search(terms, scope=scope, limit=limit * 2)

    # Attempt semantic; gracefully degrade
    sem_rows: list[dict] = []
    try:
        import embeddings
        if embeddings.available():
            sem_rows = embeddings.search(query, limit=limit * 2,
                                         scope=scope or "all")
    except Exception:
        sem_rows = []

    if not sem_rows:
        return fts_rows[:limit], total

    # RRF merge — same path can appear in both lists; their inverse ranks add
    scores: dict[str, float] = {}
    payload: dict[str, dict] = {}
    for rank, row in enumerate(fts_rows):
        path = row["path"]
        scores[path] = scores.get(path, 0.0) + 1.0 / (_RRF_K + rank)
        payload[path] = row
    for rank, row in enumerate(sem_rows):
        path = row.get("path")
        if not path:
            continue
        scores[path] = scores.get(path, 0.0) + 1.0 / (_RRF_K + rank)
        # Don't overwrite FTS payload (has excerpt + bm25 rank)
        payload.setdefault(path, row)

    ranked = sorted(scores.keys(), key=lambda p: -scores[p])
    merged = [payload[p] for p in ranked[:limit]]
    # `total` stays as the FTS total — semantic adds re-ranking, not new candidates
    return merged, max(total, len(merged))


def _layer1(query: str, scope: str | None, since: str | None,
            limit: int, budget: int) -> str:
    """Compact ranked index. bm25 * relevance * semantic blended via
    Reciprocal Rank Fusion when fastembed is available; FTS-only fallback."""
    rows, total = _hybrid_search(query, scope, limit)

    if since:
        rows = [r for r in rows if r.get("indexed_at", "") >= since
                or r.get("mtime_iso", "") >= since]

    if not rows:
        return f"no relevant notes found for: {query!r}"

    out: list[str] = []
    char_budget = budget * 4
    used = 0
    for r in rows:
        excerpt = (r.get("excerpt") or "").replace("\n", " ").strip()
        line = (f"- `{r['path']}` — {r.get('title') or r['path']}"
                + (f"  · {excerpt[:80]}" if excerpt else ""))
        if used + len(line) + 1 > char_budget:
            remaining = total - rows.index(r)
            if remaining > 0:
                out.append(f"_(+{remaining} more, raise --budget to see)_")
            break
        out.append(line)
        used += len(line) + 1
    return "\n".join(out)


def _layer2(query: str, scope: str | None, since: str | None,
            limit: int, budget: int) -> str:
    """Layer 1 + chronological context: for each top hit, list neighbours
    (in/out wikilinks) so the caller can see what's connected."""
    base = _layer1(query, scope, since, max(3, limit // 2), budget // 2)
    if base.startswith("no relevant"):
        return base

    db.reindex(force=False)
    terms = query.strip().split()
    rows, _ = db.search(terms, scope=scope, limit=3)
    if not rows:
        return base

    out: list[str] = [base, "", "## Connected"]
    char_budget = budget * 4
    used = sum(len(line) + 1 for line in out)
    for r in rows[:3]:
        graph = db.link_graph(r["path"])
        bits: list[str] = []
        for ref in graph.get("references", [])[:5]:
            bits.append(f"  → `{ref['path']}`")
        for src in graph.get("referenced_by", [])[:3]:
            bits.append(f"  ← `{src}`")
        if bits:
            head = f"`{r['path']}`:"
            block = "\n".join([head, *bits])
            if used + len(block) + 1 > char_budget:
                break
            out.append(block)
            used += len(block) + 1
    return "\n".join(out)


def _layer3(query: str, scope: str | None, since: str | None,
            budget: int) -> str:
    """Full body of the top hit. Used sparingly (large token cost)."""
    db.reindex(force=False)
    terms = query.strip().split()
    rows, _ = db.search(terms, scope=scope, limit=1)
    if not rows:
        return f"no relevant notes found for: {query!r}"
    top = rows[0]
    rec = db.get_file(top["path"])
    if rec is None:
        return f"top hit unreadable: `{top['path']}`"
    body = rec["body"]
    char_budget = budget * 4
    return f"# `{top['path']}`\n\n{_budget_truncate(body, char_budget)}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", required=True)
    ap.add_argument("--layer", type=int, default=1, choices=[1, 2, 3])
    ap.add_argument("--budget", type=int, default=600,
                    help="Target token budget; ~4 chars/token soft cap.")
    ap.add_argument("--scope", default=None,
                    help="decisions | domain | lessons | procedural | pr-context")
    ap.add_argument("--since", default=None,
                    help="ISO date — restrict to notes touched after this.")
    ap.add_argument("--limit", type=int, default=10,
                    help="Max hits considered before budget truncation.")
    ap.add_argument("--json", action="store_true",
                    help="Machine-readable JSON output.")
    args = ap.parse_args()

    if not memory_dir().exists():
        print("_vault not initialised — run `/strata:init` first_",
              file=sys.stderr)
        return 2

    if args.layer == 3:
        out = _layer3(args.query, args.scope, args.since, args.budget)
    elif args.layer == 2:
        out = _layer2(args.query, args.scope, args.since,
                      args.limit, args.budget)
    else:
        out = _layer1(args.query, args.scope, args.since,
                      args.limit, args.budget)

    if args.json:
        print(json.dumps({"layer": args.layer, "query": args.query,
                          "result": out}))
    else:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

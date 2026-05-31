#!/usr/bin/env python3
"""Unified recall — invoked by the memory-recall subagent.

Three layers of progressive disclosure:
  Layer 1 (~50-100 tokens/hit): path + title + 1-line excerpt + score
  Layer 2 (~200 tokens/hit): + adjacent notes (timeline) + nearby links
  Layer 3 (full body): top hit only, capped at 4KB

Ranks by FTS bm25 + on-device semantic similarity (RRF), then demotes
superseded/deprecated notes below current ones. Honours --since, --scope
filters. Excludes invalidated by default.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import re
import sys
from pathlib import Path

import db
import lib_loader  # noqa: F401
from lib import memory_dir

# Set True only by the CLI entry (main) so importing recall (e.g. from eval.py)
# never pollutes the usage ledger with non-user recalls.
_LOG_HITS = False


_CAMEL_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")
_PATH_STOPWORDS = frozenset({
    "src", "lib", "test", "tests", "index", "main", "init", "app", "py",
    "ts", "js", "go", "rs", "java", "md", "the", "and",
})


def query_from_paths(paths: list[str]) -> str:
    """Derive a recall query from changed file paths: split stems + parent dir
    names on camelCase / snake / kebab / separators, drop short + boilerplate
    tokens, dedupe preserving order. Used by the --paths mode (pre-push hook)."""
    terms: list[str] = []
    seen: set[str] = set()
    for p in paths:
        pp = Path(p)
        chunks = [pp.stem, pp.parent.name]
        for chunk in chunks:
            for w in re.split(r"[^A-Za-z0-9]+", chunk):
                for part in (_CAMEL_RE.findall(w) or [w]):
                    t = part.lower()
                    if len(t) >= 3 and t not in _PATH_STOPWORDS and t not in seen:
                        seen.add(t)
                        terms.append(t)
    # No usable terms (every stem was boilerplate/too short) → empty, so the
    # caller short-circuits to "no notes govern…" rather than matching the
    # commonest filenames (main/index/app) across the whole corpus.
    return " ".join(terms)


def _budget_truncate(text: str, char_budget: int) -> str:
    if len(text) <= char_budget:
        return text
    cut = text[: char_budget - 3]
    return cut.rstrip() + "..."


_RRF_K = 60  # standard RRF constant from the original paper

# Cross-encoder rerank seams. Off by default — it costs a per-process model
# load and the lift is unproven on any given vault, so it's opt-in (--rerank,
# or eval --rerank to measure first). _RERANK_SCORER lets tests inject a
# deterministic scorer (no model download).
_RERANK_ENABLED = False
_RERANK_SCORER = None  # fn(query, list[str]) -> list[float] | None

# Supersession demotion: superseded/deprecated notes sink below current ones in
# recall (findable as history, never outranking the current note). The live
# supersession signal. Toggleable so the temporal benchmark can measure the
# ON-vs-OFF delta this produces.
_DEMOTE_SUPERSEDED = True


def _maybe_rerank(query: str, rows: list[dict]) -> list[dict]:
    """Reorder candidates by a cross-encoder when available; identity otherwise.
    Production scorer is embeddings.rerank_scores (offline-gated, degrades to a
    no-op when the model isn't cached). Never raises."""
    if not _RERANK_ENABLED or len(rows) < 2:
        return rows
    scorer = _RERANK_SCORER
    if scorer is None:
        try:
            import embeddings
            if not embeddings.rerank_available():
                return rows
            scorer = embeddings.rerank_scores
        except Exception:
            return rows
    docs = [
        (f"{r.get('title') or ''} {r.get('excerpt') or ''}".strip() or r["path"])
        for r in rows
    ]
    try:
        scores = scorer(query, docs)
    except Exception:
        return rows
    if not scores or len(scores) != len(rows):
        return rows
    order = sorted(range(len(rows)), key=lambda i: -scores[i])
    return [rows[i] for i in order]


def _demote_superseded(rows: list[dict]) -> list[dict]:
    """Stable-partition recall candidates so superseded/deprecated notes sink
    below current ones — findable as history, but a current note always wins.

    `invalidated` notes are already excluded upstream in db.search; this is the
    'replaced but historical' demotion. Best-effort: if the lookup fails or
    nothing is demoted, returns rows unchanged."""
    try:
        demoted = db.demoted_paths()
    except Exception:
        return rows
    if not demoted:
        return rows
    current = [r for r in rows if r.get("path") not in demoted]
    retired = [r for r in rows if r.get("path") in demoted]
    return current + retired


def _hybrid_search(query: str, scope: str | None,
                   limit: int) -> tuple[list[dict], int]:
    """FTS5 BM25 + on-device semantic similarity, merged via Reciprocal Rank
    Fusion (k=60), with superseded/deprecated notes demoted below current ones.

    Falls back to FTS-only if the semantic layer is unavailable (fastembed not
    installed, no model downloaded, etc.). Recency/link weighting is NOT applied
    here — the `relevance` column db.reindex computes is not read by this ranker.
    """
    db.reindex(force=False)
    terms = query.strip().split()
    fts_rows, total = db.search(terms, scope=scope, limit=limit * 2)

    # AND is precise but brittle on multi-term queries (a note rarely contains
    # EVERY term). If it found nothing, relax to OR so a strong partial match
    # still surfaces — semantic + rerank below re-establish precision.
    if not fts_rows and len(terms) > 1:
        fts_rows, total = db.search(terms, scope=scope, limit=limit * 2,
                                    match_all=False)

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
        candidates = fts_rows
    else:
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
        candidates = [payload[p] for p in ranked]

    # Optional cross-encoder rerank over the fused pool.
    candidates = _maybe_rerank(query, candidates)
    # Supersession signal: sink superseded/deprecated notes below current ones
    # before truncating, so a current note always wins its query.
    if _DEMOTE_SUPERSEDED:
        candidates = _demote_superseded(candidates)
    merged = candidates[:limit]
    if _LOG_HITS:
        with contextlib.suppress(Exception):
            import usage
            hits = [(r.get("path"), r.get("scope"), i)
                    for i, r in enumerate(merged)]
            mechanism = ("rrf" if sem_rows else "fts") + (
                "+rerank" if _RERANK_ENABLED else "")
            usage.log_recall_hits(hits)
            usage.log_recall(query, scope, hits, mechanism)
    # `total` stays the FTS total — rerank/semantic reorder, don't add candidates
    return merged, max(total, len(merged))


def _format_index(rows: list[dict], total: int, budget: int) -> str:
    """Render rows as a compact ranked index, honoring the char budget."""
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


def _paths_search(paths: list[str], scope: str | None,
                  limit: int) -> list[dict]:
    """Notes governing a set of changed file paths. OR semantics over the
    path-derived terms (a note rarely contains *every* token from *every*
    changed file), ranked by bm25, optionally scoped. Pure FTS — deterministic
    and offline; terms are alnum-only and quoted so an FTS operator can't leak."""
    terms = query_from_paths(paths).split()
    if not terms:
        return []
    db.reindex(force=False)
    match = " OR ".join(f'"{t}"' for t in terms)
    where = "fts MATCH ?"
    params: list = [match]
    if scope and scope != "all":
        where += " AND scope = ?"
        params.append(scope)
    # Don't surface invalidated/stale decisions or staged (auto) notes as
    # "governing" (mirror db.search's recall quarantine).
    where += (" AND path NOT IN "
              "(SELECT path FROM files WHERE status IN ('invalidated', 'auto'))")
    rows: list[dict] = []
    with contextlib.suppress(Exception), db.connect() as conn:
        for r in conn.execute(
            "SELECT path, title, scope, "
            "snippet(fts, 2, '[', ']', '…', 12) AS excerpt, bm25(fts) AS rank "
            f"FROM fts WHERE {where} ORDER BY rank LIMIT ?",
            (*params, limit),
        ):
            rows.append(dict(r))
    return rows


def _layer1(query: str, scope: str | None, since: str | None,
            limit: int, budget: int) -> str:
    """Compact ranked index. bm25 + semantic fused via Reciprocal Rank Fusion
    when fastembed is available (FTS-only fallback), with superseded/deprecated
    notes demoted below current ones."""
    rows, total = _hybrid_search(query, scope, limit)

    if since:
        rows = [r for r in rows if r.get("indexed_at", "") >= since
                or r.get("mtime_iso", "") >= since]

    if not rows:
        return f"no relevant notes found for: {query!r}"
    return _format_index(rows, total, budget)


def _layer2(query: str, scope: str | None, since: str | None,
            limit: int, budget: int) -> str:
    """Layer 1 + chronological context: for each top hit, list neighbours
    (in/out wikilinks) so the caller can see what's connected."""
    base = _layer1(query, scope, since, max(3, limit // 2), budget // 2)
    if base.startswith("no relevant"):
        return base

    # Seed neighbours from the SAME fused/reranked ranking as layer 1, not a
    # separate bm25 query, so the "Connected" hits match what was shown above.
    rows, _ = _hybrid_search(query, scope, 3)
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
    # Use the fused/reranked top hit so layer 3 returns the body of the SAME
    # note layer 1 ranked first (not a divergent bm25-only pick).
    rows, _ = _hybrid_search(query, scope, 1)
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
    ap.add_argument("--query", default=None,
                    help="Free-text query. Provide this OR --paths.")
    ap.add_argument("--paths", nargs="+", default=None,
                    help="Changed file paths — derive the query from them and "
                         "surface the notes that govern them. Advisory; pair "
                         "with a pre-push git hook (exit 0 always).")
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
    ap.add_argument("--rerank", action="store_true",
                    help="Enable the cross-encoder rerank pass (off by default; "
                         "measure the lift with /strata:eval before relying on "
                         "it — it costs a per-call model load).")
    args = ap.parse_args()

    if args.rerank:
        global _RERANK_ENABLED
        _RERANK_ENABLED = True

    global _LOG_HITS
    _LOG_HITS = True  # this is a real user-facing recall — log what it surfaces

    if not (args.query or args.paths):
        print("[strata] error: provide --query or --paths", file=sys.stderr)
        return 2

    if not memory_dir().exists():
        print("_vault not initialised — run `/strata:init` first_",
              file=sys.stderr)
        return 2

    if args.paths:
        query = query_from_paths(args.paths)
        rows = _paths_search(args.paths, args.scope, args.limit)
        if _LOG_HITS:
            with contextlib.suppress(Exception):
                import usage
                hits = [(r.get("path"), r.get("scope"), i)
                        for i, r in enumerate(rows)]
                usage.log_recall_hits(hits)
                usage.log_recall(query, args.scope, hits, "paths")
        out = (_format_index(rows, len(rows), args.budget) if rows
               else f"no notes govern the changed paths: {args.paths}")
    else:
        query = args.query
        if args.layer == 3:
            out = _layer3(query, args.scope, args.since, args.budget)
        elif args.layer == 2:
            out = _layer2(query, args.scope, args.since,
                          args.limit, args.budget)
        else:
            out = _layer1(query, args.scope, args.since,
                          args.limit, args.budget)

    if args.json:
        print(json.dumps({"layer": args.layer, "query": query,
                          "result": out}))
    else:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

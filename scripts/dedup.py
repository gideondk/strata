"""Recall-before-write deduplication for decisions.

Before a new ADR lands, surface existing decisions that look like the *same
choice*, so parallel agents don't mint near-duplicate or contradictory ADRs
(the "agents battling on ADRs" failure mode). Three cheap, local-first signals
— no network:

  - **exact / normalized title match** — deterministic, high precision
  - **keyword overlap** via FTS5 BM25 — always available
  - **semantic similarity** via local embeddings (fastembed) — when installed

This module does retrieval + a coarse recommendation only. The actual
ADD / UPDATE / SUPERSEDE / NO-OP adjudication is the caller's job: the agent
running `/strata:decide`, with the human draft-accept gate as the backstop.

Degradation is deliberate: a *hard block* on a possible duplicate needs the
semantic signal (or an exact title), because keyword overlap alone is too noisy
to justify refusing a write. With embeddings unavailable we drop to
warn-only + exact-title blocking — never block on FTS overlap alone.
"""
from __future__ import annotations

import contextlib
import os
import re
import sqlite3

import db
import lib_loader  # noqa: F401

# Cosine thresholds for the local model (bge-small-en-v1.5). Tunable; see the
# dedup-gate ADR for the calibration rationale.
SEMANTIC_HARD = 0.86   # near-duplicate → block the write
SEMANTIC_SOFT = 0.78   # similar → warn, but proceed

# Statuses that are resolved history. A match against one of these never hard
# blocks (the collision is already accounted for); it warns at most.
_RESOLVED = frozenset({"superseded", "rejected", "deprecated", "invalidated"})

_STOPWORDS = frozenset({
    "the", "a", "an", "to", "of", "for", "and", "or", "in", "on", "is", "are",
    "use", "using", "used", "with", "via", "we", "our", "as", "by", "be",
})

_NONALNUM_RE = re.compile(r"[^a-z0-9]+")


def _norm_title(title: str) -> str:
    """Normalize a title for equality testing: lowercase, collapse every run of
    non-alphanumerics to a single '-', strip the ends.

    Deliberately NOT `safe_slug` — that's a filename helper with a 48-char cap,
    so two distinct long titles sharing a 48-char prefix would collide (a
    false-positive block). This has no cap, and it folds '.'/'_' (which
    safe_slug preserves), so 'Use SQLite' and 'use sqlite.' match. Returns ''
    for alnum-empty titles (e.g. '***') so they never match each other.
    """
    return _NONALNUM_RE.sub("-", (title or "").lower()).strip("-")


def _title_terms(title: str) -> list[str]:
    """FTS query terms from a title: words >=2 chars, minus stopwords. The
    >=2 floor keeps short tech names ('Go', 'S3', 'CI', 'DB') as signal."""
    words = re.findall(r"[A-Za-z0-9]+", (title or "").lower())
    return [w for w in words if len(w) >= 2 and w not in _STOPWORDS]


@contextlib.contextmanager
def _offline_env():
    """Force HuggingFace/Transformers offline for the duration. The dedup gate
    runs on the interactive write path and must NEVER reach the network to
    fetch an embedding model — a not-yet-cached model degrades to keyword-only
    (the load raises and is suppressed), it does not download."""
    keys = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")
    prev = {k: os.environ.get(k) for k in keys}
    for k in keys:
        os.environ[k] = "1"
    try:
        yield
    finally:
        for k, v in prev.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def embeddings_available() -> bool:
    """Whether the local semantic layer is usable. STRATA_DISABLE_EMBEDDINGS
    forces keyword-only (also how the gate degrades when fastembed is absent)."""
    if os.environ.get("STRATA_DISABLE_EMBEDDINGS"):
        return False
    try:
        import embeddings
        return embeddings.available()
    except Exception:
        return False


def _live_decisions() -> dict[str, dict]:
    """All indexed decisions keyed by vault-relative path, with status."""
    out: dict[str, dict] = {}
    # Narrow suppression: a SQL/schema bug must surface (in tests/dev), not
    # silently yield zero candidates and let the gate fail open.
    with contextlib.suppress(sqlite3.Error), db.connect() as conn:
        for r in conn.execute(
            "SELECT path, title, status FROM files WHERE scope = 'decisions'"
        ):
            out[r["path"]] = {
                "path": r["path"],
                "title": r["title"] or "",
                "status": (r["status"] or "").lower(),
            }
    return out


def find_similar_decisions(title: str, body: str = "",
                           limit: int = 5) -> list[dict]:
    """Return existing decisions similar to a proposed one, ranked.

    Each candidate: {path, title, status, semantic (float|None), fts (bool),
    exact_title (bool)}. `semantic` is cosine in [0,1] when embeddings are
    available and the note scored in the top-K, else None.
    """
    title = (title or "").strip()
    if not title:
        return []

    # Make sure the index reflects current disk before we compare. Both are
    # incremental and cheap; failures degrade to whatever is already indexed.
    with contextlib.suppress(Exception):
        db.reindex(force=False)

    decisions = _live_decisions()
    if not decisions:
        return []

    cand: dict[str, dict] = {}

    def _slot(path: str) -> dict | None:
        meta = decisions.get(path)
        if meta is None:
            return None  # not a decision (or stale) — ignore
        c = cand.get(path)
        if c is None:
            c = {
                "path": path,
                "title": meta["title"],
                "status": meta["status"],
                "semantic": None,
                "fts": False,
                "exact_title": False,
            }
            cand[path] = c
        return c

    # 1. Exact / normalized title match (deterministic).
    want = _norm_title(title)
    for path, meta in decisions.items():
        if want and _norm_title(meta["title"]) == want:
            slot = _slot(path)
            if slot is not None:
                slot["exact_title"] = True

    # 2. Keyword overlap via FTS5. OR semantics (a near-dup rarely shares
    #    *every* word) — db.search ANDs, so query fts directly here. Terms are
    #    alnum-only; quote each so an FTS operator word (e.g. "not") can't leak.
    terms = _title_terms(title)
    if terms:
        match = " OR ".join(f'"{t}"' for t in terms)
        with contextlib.suppress(sqlite3.Error), db.connect() as conn:
            for r in conn.execute(
                "SELECT path FROM fts WHERE fts MATCH ? AND scope = 'decisions' "
                "ORDER BY bm25(fts) LIMIT ?",
                (match, limit * 2),
            ):
                slot = _slot(r["path"])
                if slot is not None:
                    slot["fts"] = True

    # 3. Semantic similarity via local embeddings — STRICTLY OFFLINE (see
    #    _offline_env): a not-yet-cached model degrades to keyword-only rather
    #    than downloading on the write path. Graceful if fastembed is absent.
    if embeddings_available():
        with contextlib.suppress(Exception), _offline_env():
            import embeddings
            embeddings.reindex(force=False)  # embed any new decisions first
            query = title if not body else f"{title}\n\n{body[:2000]}"
            for r in embeddings.search(query, limit=limit * 2,
                                       scope="decisions"):
                slot = _slot(r["path"])
                if slot is not None:
                    slot["semantic"] = r["score"]

    ranked = sorted(
        cand.values(),
        key=lambda c: (
            c["exact_title"],
            c["semantic"] if c["semantic"] is not None else -1.0,
            c["fts"],
        ),
        reverse=True,
    )
    return ranked[:limit]


def classify(candidates: list[dict]) -> tuple[str, dict | None]:
    """Coarse recommendation over candidates → (verdict, top_candidate).

    'block' — a live decision with the same title, or semantic >= HARD.
    'warn'  — semantic >= SOFT; or a resolved exact-title match; or, when
              embeddings are unavailable, any keyword (FTS) overlap.
    'clear' — nothing notable.
    """
    emb = embeddings_available()
    warn: dict | None = None
    for c in candidates:
        live = c["status"] not in _RESOLVED
        sem = c["semantic"]
        if live and (c["exact_title"] or (sem is not None and sem >= SEMANTIC_HARD)):
            return "block", c
        if warn is None and (
            (sem is not None and sem >= SEMANTIC_SOFT)  # similar by meaning
            or c["exact_title"]                          # resolved historical dup
            or ((not emb) and c["fts"])                  # no semantic — surface keyword hits
        ):
            warn = c
    return ("warn", warn) if warn else ("clear", None)


def reason(c: dict) -> str:
    """Human-readable why-this-matched string for a candidate."""
    bits: list[str] = []
    if c.get("exact_title"):
        bits.append("same title")
    if c.get("semantic") is not None:
        bits.append(f"semantic {c['semantic']:.2f}")
    if c.get("fts"):
        bits.append("keyword overlap")
    status = c.get("status")
    if status:
        bits.append(f"status: {status}")
    return ", ".join(bits) or "similar"

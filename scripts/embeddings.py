"""Semantic-search layer for the Strata vault.

Local CPU embeddings via fastembed (ONNX runtime). Embeddings stored as
BLOBs in the same SQLite db as FTS5. Brute-force cosine similarity at
query time — fine for <10k notes, which covers any reasonable vault.

Optional dep — if `fastembed` isn't importable the module's `available()`
returns False and callers should fall back to FTS5-only search."""
from __future__ import annotations

import contextlib
import os
import sqlite3

import lib_loader  # noqa: F401
from db import _safe_match, connect, db_path  # noqa: F401
from lib import info

# Cross-encoder reranker — small CPU ONNX model shipped by fastembed. Used as
# an optional final rerank pass after hybrid retrieval.
DEFAULT_RERANK_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"
_RERANK_CACHE: object | None = None

# Default model: small, fast, CPU-only, ~30MB. fastembed downloads on first
# use to ~/.cache/fastembed (network call on first install only).
DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
EMBED_DIM = 384  # bge-small-en-v1.5 output dimension


_MODEL_CACHE: object | None = None


def available() -> bool:
    """Return True iff fastembed + numpy are installed."""
    try:
        import fastembed  # noqa: F401
        import numpy  # noqa: F401
    except ImportError:
        return False
    return True


def _get_model():
    """Lazy singleton — model load is ~1s the first time per process."""
    global _MODEL_CACHE
    if _MODEL_CACHE is not None:
        return _MODEL_CACHE
    from fastembed import TextEmbedding
    _MODEL_CACHE = TextEmbedding(model_name=DEFAULT_MODEL)
    return _MODEL_CACHE


def _ensure_schema() -> None:
    """Add the embeddings table if it doesn't exist. Idempotent."""
    with connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS embeddings ("
            "path TEXT PRIMARY KEY, "
            "model TEXT NOT NULL, "
            "vec BLOB NOT NULL, "
            "indexed_at TEXT NOT NULL"
            ")"
        )


def _to_bytes(arr) -> bytes:
    import numpy as np
    return np.asarray(arr, dtype=np.float32).tobytes()


def _from_bytes(b: bytes):
    import numpy as np
    return np.frombuffer(b, dtype=np.float32)


def reindex(force: bool = False) -> dict:
    """Compute embeddings for all indexed files. Incremental: skips paths
    that already have an embedding for the current model unless force=True.

    Returns: {"indexed": N, "skipped": N, "errors": N}.
    """
    if not available():
        return {"indexed": 0, "skipped": 0, "errors": 0, "reason": "fastembed unavailable"}

    _ensure_schema()
    model = _get_model()

    # Pull paths + bodies from FTS5 once
    with connect() as conn:
        all_rows = conn.execute(
            "SELECT path, title, body FROM fts"
        ).fetchall()
        existing: set[str] = set()
        if not force:
            existing = {
                r["path"] for r in conn.execute(
                    "SELECT path FROM embeddings WHERE model = ?",
                    (DEFAULT_MODEL,),
                )
            }

    to_embed = [r for r in all_rows if r["path"] not in existing]
    if not to_embed:
        return {"indexed": 0, "skipped": len(all_rows), "errors": 0}

    # Embed in one batch — fastembed is much faster batched
    texts = [
        f"{r['title']}\n\n{r['body']}"[:8000]  # cap input length
        for r in to_embed
    ]
    indexed = errors = 0
    try:
        vectors = list(model.embed(texts))
    except Exception as e:
        info(f"embedding generation failed: {e}")
        return {"indexed": 0, "skipped": len(existing), "errors": len(to_embed)}

    import time
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with connect(write=True) as conn:
        for row, vec in zip(to_embed, vectors, strict=True):
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO embeddings(path, model, vec, indexed_at) "
                    "VALUES (?, ?, ?, ?)",
                    (row["path"], DEFAULT_MODEL, _to_bytes(vec), now),
                )
                indexed += 1
            except sqlite3.Error:
                errors += 1

    return {"indexed": indexed, "skipped": len(existing), "errors": errors}


def search(
    query: str,
    limit: int = 10,
    scope: str | None = None,
) -> list[dict]:
    """Semantic search: top-K cosine-similar notes for the query.

    Returns rows with `path`, `title`, `scope`, `branch`, `score` (0-1).
    Empty list if embeddings unavailable or vault unindexed."""
    if not available():
        return []
    _ensure_schema()
    import numpy as np

    model = _get_model()
    try:
        q_vec_list = list(model.embed([query]))
    except Exception:
        return []
    if not q_vec_list:
        return []
    q_vec = np.asarray(q_vec_list[0], dtype=np.float32)
    q_norm = np.linalg.norm(q_vec)
    if q_norm == 0:
        return []
    q_vec = q_vec / q_norm

    sql = (
        "SELECT e.path, e.vec, f.title, f.scope, f.branch "
        "FROM embeddings e JOIN files f ON e.path = f.path "
        "WHERE e.model = ? "
        # Quarantine: semantic recall must honor the same exclusions as FTS —
        # never surface staged (auto) or invalidated notes as canonical truth.
        "AND COALESCE(f.status, '') NOT IN ('auto', 'invalidated')"
    )
    params: list = [DEFAULT_MODEL]
    if scope and scope != "all":
        sql += " AND f.scope = ?"
        params.append(scope)

    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()

    scored: list[dict] = []
    for r in rows:
        v = _from_bytes(r["vec"])
        n = np.linalg.norm(v)
        if n == 0:
            continue
        v = v / n
        score = float(np.dot(q_vec, v))
        scored.append({
            "path": r["path"],
            "title": r["title"],
            "scope": r["scope"],
            "branch": r["branch"],
            "score": round(score, 4),
        })
    scored.sort(key=lambda x: -x["score"])
    return scored[:limit]


def rerank_available() -> bool:
    """Whether the cross-encoder reranker can be used. Honors the same
    disable knobs as embeddings, plus a rerank-specific one."""
    if os.environ.get("STRATA_DISABLE_EMBEDDINGS") or \
            os.environ.get("STRATA_DISABLE_RERANK"):
        return False
    try:
        import numpy  # noqa: F401
        from fastembed.rerank.cross_encoder import TextCrossEncoder  # noqa: F401
        return True
    except Exception:
        return False


def _get_reranker():
    global _RERANK_CACHE
    if _RERANK_CACHE is not None:
        return _RERANK_CACHE
    from fastembed.rerank.cross_encoder import TextCrossEncoder
    _RERANK_CACHE = TextCrossEncoder(model_name=DEFAULT_RERANK_MODEL)
    return _RERANK_CACHE


def rerank_scores(query: str, documents: list[str]) -> list[float] | None:
    """Cross-encoder relevance scores for each (query, document) pair, higher =
    more relevant. STRICTLY OFFLINE — a not-yet-cached model degrades to None
    (the caller keeps the prior ordering) rather than downloading on the recall
    path. Returns None on any failure or when unavailable."""
    if not rerank_available() or not documents:
        return None
    keys = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")
    prev = {k: os.environ.get(k) for k in keys}
    for k in keys:
        os.environ[k] = "1"
    try:
        model = _get_reranker()
        return [float(s) for s in model.rerank(query, documents)]
    except Exception:
        return None
    finally:
        for k, v in prev.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def status() -> dict:
    """Counts + model info for diagnostics."""
    if not available():
        return {"available": False, "reason": "fastembed not installed"}
    _ensure_schema()
    with connect() as conn:
        n = conn.execute("SELECT COUNT(*) AS n FROM embeddings").fetchone()["n"]
    return {
        "available": True,
        "model": DEFAULT_MODEL,
        "dim": EMBED_DIM,
        "indexed": n,
    }


# Side-effect-free no-op when called from `db._safe_match` import — we keep
# the import to surface schema setup but don't run anything on import.
with contextlib.suppress(Exception):
    _ensure_schema() if available() else None

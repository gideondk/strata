"""Tests for recall.py additions: cross-encoder rerank seam + changed-files
(--paths) query derivation."""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))


def _write(mem, rel, content):
    p = mem / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


# --- query_from_paths (pure) -----------------------------------------------

def test_query_from_paths_splits_and_filters():
    import recall
    q = recall.query_from_paths(
        ["src/auth/TokenBucket.py", "billing/invoice_service.go"]).split()
    assert "token" in q and "bucket" in q       # camelCase split
    assert "invoice" in q and "service" in q     # snake split
    assert "auth" in q and "billing" in q        # parent dirs
    assert "src" not in q                        # stopword dropped


def test_query_from_paths_empty_for_boilerplate():
    import recall
    # All tokens are boilerplate/stopwords → empty, so _paths_search
    # short-circuits instead of matching the commonest filenames corpus-wide.
    assert recall.query_from_paths(["src/main.py"]) == ""
    assert recall.query_from_paths(["lib/index.ts"]) == ""


# --- cross-encoder rerank seam ---------------------------------------------

def test_rerank_reorders_with_injected_scorer(initialised_vault, monkeypatch):
    monkeypatch.setenv("STRATA_DISABLE_EMBEDDINGS", "1")  # FTS-only baseline
    import db
    import recall
    mem = initialised_vault
    _write(mem, "decisions/2026-05-01-alpha.md",
           "---\ntitle: Alpha widget\n---\nwidget alpha body.\n")
    _write(mem, "decisions/2026-05-02-beta.md",
           "---\ntitle: Beta widget\n---\nwidget beta body.\n")
    db.reindex(force=True)

    # Rerank is opt-in (default off) — enable it for this test.
    monkeypatch.setattr(recall, "_RERANK_ENABLED", True)
    # A scorer that ranks the 'beta' document strictly highest.
    monkeypatch.setattr(
        recall, "_RERANK_SCORER",
        lambda q, docs: [1.0 if "beta" in d.lower() else 0.0 for d in docs])
    rows, _ = recall._hybrid_search("widget", "decisions", 5)
    assert rows[0]["path"].endswith("beta.md")


def test_rerank_disabled_is_identity(initialised_vault, monkeypatch):
    monkeypatch.setenv("STRATA_DISABLE_EMBEDDINGS", "1")
    import db
    import recall
    mem = initialised_vault
    _write(mem, "decisions/2026-05-01-alpha.md", "---\ntitle: Alpha widget\n---\nw.\n")
    _write(mem, "decisions/2026-05-02-beta.md", "---\ntitle: Beta widget\n---\nw.\n")
    db.reindex(force=True)

    monkeypatch.setattr(recall, "_RERANK_SCORER",
                        lambda q, docs: [1.0 if "beta" in d.lower() else 0.0
                                         for d in docs])
    monkeypatch.setattr(recall, "_RERANK_ENABLED", False)
    base, _ = recall._hybrid_search("widget", "decisions", 5)
    monkeypatch.setattr(recall, "_RERANK_ENABLED", True)
    on, _ = recall._hybrid_search("widget", "decisions", 5)
    assert on[0]["path"].endswith("beta.md")            # rerank put beta first
    assert base[0]["path"] != on[0]["path"]             # disabled ≠ enabled order


def test_rerank_bad_scores_keeps_order(initialised_vault, monkeypatch):
    monkeypatch.setenv("STRATA_DISABLE_EMBEDDINGS", "1")
    import db
    import recall
    mem = initialised_vault
    _write(mem, "decisions/2026-05-01-a.md", "---\ntitle: A widget\n---\nw.\n")
    _write(mem, "decisions/2026-05-02-b.md", "---\ntitle: B widget\n---\nw.\n")
    db.reindex(force=True)
    monkeypatch.setattr(recall, "_RERANK_ENABLED", False)
    before, _ = recall._hybrid_search("widget", "decisions", 5)
    # Rerank on, but the scorer returns a wrong-length list → ignored, order kept.
    monkeypatch.setattr(recall, "_RERANK_ENABLED", True)
    monkeypatch.setattr(recall, "_RERANK_SCORER", lambda q, docs: [1.0])
    after, _ = recall._hybrid_search("widget", "decisions", 5)
    assert [r["path"] for r in before] == [r["path"] for r in after]


# --- changed-files recall flow ---------------------------------------------

def test_paths_search_surfaces_governing_note(initialised_vault, monkeypatch):
    monkeypatch.setenv("STRATA_DISABLE_EMBEDDINGS", "1")
    import db
    import recall
    mem = initialised_vault
    _write(mem, "decisions/2026-05-01-token-bucket.md",
           "---\ntitle: Token bucket rate limiting\n---\n"
           "Rate limit with a token bucket.\n")
    db.reindex(force=True)
    # OR semantics: 'ratelimit' (from the dir) won't match, but token+bucket do.
    rows = recall._paths_search(["src/ratelimit/token_bucket.py"], None, 5)
    assert any("token-bucket" in r["path"] for r in rows)


def test_paths_search_or_not_and(initialised_vault, monkeypatch):
    """Two changed files in different areas: a note governing ONE must still
    surface (AND semantics would drop it)."""
    monkeypatch.setenv("STRATA_DISABLE_EMBEDDINGS", "1")
    import db
    import recall
    mem = initialised_vault
    _write(mem, "decisions/2026-05-01-auth.md",
           "---\ntitle: Authentication tokens\n---\nauth token policy.\n")
    db.reindex(force=True)
    rows = recall._paths_search(
        ["src/auth/token.py", "src/billing/invoice.py"], None, 5)
    assert any("auth" in r["path"] for r in rows)

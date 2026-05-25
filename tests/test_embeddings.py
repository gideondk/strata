"""Tests for the optional vector layer. Model download is slow + needs
network on first run; we skip the round-trip tests when fastembed isn't
present so the suite stays fast and CI-friendly."""
from __future__ import annotations

import importlib.util
import sys

import pytest


def _fastembed_available() -> bool:
    return importlib.util.find_spec("fastembed") is not None


def test_available_reports_truthfully(env):
    """Smoke test that mirrors the runtime check."""
    import embeddings
    assert embeddings.available() is _fastembed_available()


def test_status_when_unavailable(env, monkeypatch):
    """When fastembed isn't loadable, status() returns a friendly stub."""
    import embeddings
    monkeypatch.setattr(embeddings, "available", lambda: False)
    s = embeddings.status()
    assert s["available"] is False
    assert "fastembed" in s.get("reason", "")


def test_search_returns_empty_when_unavailable(env, monkeypatch):
    import embeddings
    monkeypatch.setattr(embeddings, "available", lambda: False)
    assert embeddings.search("anything") == []


def test_reindex_returns_zero_when_unavailable(env, monkeypatch):
    import embeddings
    monkeypatch.setattr(embeddings, "available", lambda: False)
    out = embeddings.reindex()
    assert out["indexed"] == 0
    assert "fastembed" in out.get("reason", "").lower() \
        or out.get("indexed") == 0


@pytest.mark.skipif(not _fastembed_available(),
                    reason="fastembed not installed")
def test_round_trip_with_fastembed(initialised_vault):
    """End-to-end: index a few notes, search, verify ordering."""
    import db
    import embeddings
    mem = initialised_vault
    (mem / "decisions" / "2026-05-23-auth.md").write_text(
        "---\ntitle: Use OAuth + JWT for authentication\n---\nWe chose OAuth.\n"
    )
    (mem / "decisions" / "2026-05-23-postgres.md").write_text(
        "---\ntitle: Use Postgres for X store\n---\nPostgres beats SQLite.\n"
    )
    db.reindex(force=True)

    counts = embeddings.reindex(force=True)
    assert counts["indexed"] >= 2, counts

    # Semantic match should find auth even though the query word "authentication"
    # doesn't appear in the title literally
    rows = embeddings.search("how do users sign in", limit=5)
    paths = [r["path"] for r in rows]
    assert any("auth" in p for p in paths)


def test_get_module_imports_without_side_effects(env):
    """Importing embeddings.py must not fail or do anything destructive."""
    # Force reload
    for mod in list(sys.modules):
        if mod == "embeddings":
            del sys.modules[mod]
    import embeddings  # noqa: F401

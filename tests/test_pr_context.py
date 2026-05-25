"""Tests for pr_context. We monkey-patch the internal helpers instead of
stubbing the `gh` binary on PATH — much more reliable and doesn't risk
breaking other tools the rest of the function depends on (e.g. git)."""
from __future__ import annotations


def test_no_gh(env, monkeypatch):
    import pr_context
    monkeypatch.setattr(pr_context, "_gh_available",
                        lambda: (False, "gh CLI not installed"))
    ctx = pr_context.fetch_for_current_branch()
    assert not ctx.available
    assert "not installed" in ctx.reason


def test_gh_unauthenticated(env, monkeypatch):
    import pr_context
    monkeypatch.setattr(pr_context, "_gh_available",
                        lambda: (False, "gh not authenticated"))
    ctx = pr_context.fetch_for_current_branch()
    assert not ctx.available
    assert "not authenticated" in ctx.reason


def test_no_open_pr(env, monkeypatch):
    import pr_context
    monkeypatch.setattr(pr_context, "_gh_available", lambda: (True, ""))
    monkeypatch.setattr(pr_context, "_gh_json", lambda *_, **__: [])
    ctx = pr_context.fetch_for_current_branch()
    assert not ctx.available
    assert "no open PR" in ctx.reason


def test_open_pr_parsed(env, monkeypatch):
    import pr_context
    monkeypatch.setattr(pr_context, "_gh_available", lambda: (True, ""))
    monkeypatch.setattr(pr_context, "_gh_json", lambda *_, **__: [{
        "number": 42,
        "title": "Test PR",
        "state": "OPEN",
        "body": "Body of the PR.",
        "url": "https://example/pull/42",
        "author": {"login": "tester"},
        "isDraft": False,
        "labels": [{"name": "feature"}],
        "comments": [
            {"author": {"login": "alice"}, "body": "LGTM",
             "createdAt": "2026-05-21T08:00:00Z"}
        ],
        "reviews": [],
    }])
    ctx = pr_context.fetch_for_current_branch()
    assert ctx.available
    assert ctx.number == 42
    assert ctx.title == "Test PR"
    assert ctx.author == "tester"
    assert "feature" in (ctx.labels or [])
    assert len(ctx.comments or []) == 1


def test_format_for_primer_truncates(env, monkeypatch):
    import pr_context
    long_body = "x" * 2000
    monkeypatch.setattr(pr_context, "_gh_available", lambda: (True, ""))
    monkeypatch.setattr(pr_context, "_gh_json", lambda *_, **__: [{
        "number": 1, "title": "T", "state": "OPEN",
        "body": long_body, "url": "u", "author": {"login": "a"},
        "isDraft": False, "labels": [], "comments": [], "reviews": [],
    }])
    ctx = pr_context.fetch_for_current_branch()
    out = pr_context.format_for_primer(ctx, body_chars=200)
    assert "…" in out  # truncation marker
    assert len(out) < 1500


def test_format_full_no_pr(env, monkeypatch):
    import pr_context
    monkeypatch.setattr(pr_context, "_gh_available",
                        lambda: (False, "gh CLI not installed"))
    ctx = pr_context.fetch_for_current_branch()
    out = pr_context.format_full(ctx)
    assert "no PR context" in out

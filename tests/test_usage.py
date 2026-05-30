"""Tests for the local usage ledger (recall hits, nudge events, dead notes)."""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))


def test_log_recall_hits_and_summary(initialised_vault):
    import usage
    usage.log_recall_hits([
        ("decisions/a.md", "decisions", 0),
        ("decisions/a.md", "decisions", 2),
        ("domain/b.md", "domain", 1),
        (None, "decisions", 3),  # path-less hit is ignored
    ])
    usage.log_event("nudge_shown", branch="feat/x")

    s = usage.summary()
    assert s["recall_hits"] == 3
    assert s["distinct_recalled"] == 2
    assert s["nudges_shown"] == 1
    assert s["top_recalled"][0] == {"path": "decisions/a.md", "hits": 2}
    assert usage.recalled_paths() == {"decisions/a.md", "domain/b.md"}


def test_summary_empty_when_no_events(initialised_vault):
    import usage
    s = usage.summary()
    assert s["recall_hits"] == 0
    assert s["distinct_recalled"] == 0
    assert s["top_recalled"] == []


def test_logging_never_raises_on_bad_dir(monkeypatch, tmp_path):
    """A failed write must be swallowed — telemetry can't break a hook."""
    import usage
    # Point plugin-data at a path that can't be created (under a file, not a dir).
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    monkeypatch.setattr(usage, "plugin_data_dir", lambda: blocker / "sub")
    # Should not raise even though mkdir under a file fails.
    usage.log_event("recall_hit", path="x")
    assert usage.summary()["events"] == 0

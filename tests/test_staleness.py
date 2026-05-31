"""Tests for importance-weighted staleness scoring."""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

DAY = 86400.0


def test_fresh_note_scores_near_zero():
    import staleness
    now = 1_000_000_000.0
    # Modified just now → no decay.
    assert staleness.score(now, now=now) < 0.01


def test_old_unrecalled_note_is_stale():
    import staleness
    now = 1_000_000_000.0
    # 180 days old, never recalled, tau=90 → ~2 tau → staleness ~0.86.
    s = staleness.score(now - 180 * DAY, now=now, hits=0)
    assert 0.8 < s < 0.92


def test_recall_frequency_slows_decay():
    """Two notes of equal age; the frequently-recalled one is less stale."""
    import staleness
    now = 1_000_000_000.0
    cold = staleness.score(now - 180 * DAY, now=now, hits=0)
    hot = staleness.score(now - 180 * DAY, now=now, hits=20)
    assert hot < cold


def test_recent_recall_resets_age():
    """A note modified long ago but recalled yesterday is treated as fresh —
    age is measured from the most recent of (modified, last recalled)."""
    import staleness
    now = 1_000_000_000.0
    s = staleness.score(now - 300 * DAY, now=now, hits=3,
                        last_recall_ts=now - 1 * DAY)
    assert s < 0.05


def test_recall_stats_aggregates_hits_and_last_ts(initialised_vault):
    import time

    import usage
    now = time.time()
    usage.log_event("recall_hit", path="decisions/a.md", scope="decisions",
                    rank=0, ts=now - 100)
    usage.log_event("recall_hit", path="decisions/a.md", scope="decisions",
                    rank=1, ts=now - 10)
    usage.log_event("recall_hit", path="domain/b.md", scope="domain",
                    rank=0, ts=now - 50)
    stats = usage.recall_stats()
    assert stats["decisions/a.md"]["hits"] == 2
    assert stats["decisions/a.md"]["last_ts"] == now - 10
    assert stats["domain/b.md"]["hits"] == 1


def test_parse_stamp_handles_both_formats():
    import staleness
    assert staleness._parse_stamp("2026-05-30") is not None
    assert staleness._parse_stamp("'2026-05-30'") is not None       # quoted
    assert staleness._parse_stamp("2026-05-30-1430") is not None    # stamp_minute
    assert staleness._parse_stamp("not-a-date") is None


def test_edit_epoch_prefers_frontmatter_over_mtime(tmp_path):
    """The whole shared-vault fix: age must come from the note's own date
    field, NOT filesystem mtime (which resets on sync)."""
    import staleness
    note = tmp_path / "d.md"
    note.write_text("---\ndate: '2020-01-01'\nstatus: accepted\n---\n\nbody\n")
    # mtime is 'now' (just written), but the frontmatter says 2020.
    epoch = staleness.edit_epoch(note, fallback_mtime=2_000_000_000.0)
    from datetime import datetime, timezone
    assert datetime.fromtimestamp(epoch, tz=timezone.utc).year == 2020


def test_edit_epoch_falls_back_to_mtime_when_no_date(tmp_path):
    import staleness
    note = tmp_path / "d.md"
    note.write_text("---\nstatus: accepted\n---\n\nbody\n")
    assert staleness.edit_epoch(note, fallback_mtime=12345.0) == 12345.0


def test_synced_vault_does_not_look_falsely_fresh(tmp_path):
    """Regression for the reported bug: a 2-year-old note freshly synced (mtime
    = now) must still score stale, because age comes from the frontmatter date."""
    import time

    import staleness
    note = tmp_path / "d.md"
    note.write_text("---\ndate: '2024-01-01'\n---\n\nbody\n")
    now = time.time()
    edited = staleness.edit_epoch(note, fallback_mtime=now)  # mtime = now (synced)
    s = staleness.score(edited, now=now, hits=0)
    assert s > 0.9, "a 2-year-old note must not read as fresh after sync"


def test_rank_stale_is_best_effort_without_index():
    """rank_stale must never raise — returns [] when db/ledger unavailable."""
    import staleness
    # Calling with a threshold of 2.0 (impossible) yields no rows even when
    # an index exists; the point is it returns a list, never an exception.
    assert isinstance(staleness.rank_stale(threshold=2.0), list)

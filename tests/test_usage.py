"""Tests for the local usage ledger (recall hits, nudge events, dead notes)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
SAVE = HERE.parent / "scripts" / "save-note.py"


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


def test_save_note_telemetry_is_content_free(initialised_vault):
    """Lock the hard 'never log note content' invariant to the REAL emitter
    (save-note.py), not just the aggregator: the note_saved record must carry
    only event/ts/scope/kind/via_draft — never the topic, body, title, or path.
    """
    secret_topic = "zsecrettopicmarker"
    r = subprocess.run(
        [sys.executable, str(SAVE), "--topic", secret_topic, "--kind", "session"],
        input="zsecretbodymarker — sensitive note body\n",
        capture_output=True, text=True, check=False, env=os.environ.copy(),
    )
    assert r.returncode == 0, r.stderr

    ledger = Path(os.environ["CLAUDE_PLUGIN_DATA"]) / "usage.jsonl"
    recs = [json.loads(line) for line in ledger.read_text().splitlines()
            if '"note_saved"' in line]
    assert recs, "no note_saved event logged"
    rec = recs[-1]
    assert set(rec) == {"event", "ts", "scope", "kind", "via_draft"}
    # No content leaks anywhere in the serialized record.
    blob = json.dumps(rec)
    assert secret_topic not in blob
    assert "zsecretbodymarker" not in blob
    assert rec["scope"] == "pr-context" and rec["kind"] == "session"


def test_summary_tracks_saves_and_draft_accepts(initialised_vault):
    """Per-kind save + draft-accept counts — the graduation prerequisite."""
    import usage
    usage.log_event("note_saved", scope="pr-context", kind="session",
                    via_draft=True)
    usage.log_event("note_saved", scope="lessons", kind="handoff",
                    via_draft=False)
    s = usage.summary()
    assert s["notes_saved"] == 2
    assert s["saves_via_draft"] == 1
    assert s["saves_by_kind"]["session"] == 1


def test_log_recall_groups_query_mechanism_and_hits(initialised_vault):
    """The grouped recall audit event records the query, how it was answered,
    and the ranked paths — the observability trail."""
    import usage
    usage.log_recall(
        "order aggregate invariants", "domain",
        [("domain/order.md", "domain", 0), ("domain/line-item.md", "domain", 1)],
        "rrf+rerank",
    )
    usage.log_recall("  deploy steps  ", None,
                     [("procedural/deploy.md", "procedural", 0)], "fts")

    recents = usage.recent_recalls()
    assert len(recents) == 2
    # Newest first.
    assert recents[0]["query"] == "deploy steps"  # trimmed
    assert recents[0]["scope"] == "all"           # None normalised to "all"
    assert recents[0]["mechanism"] == "fts"
    assert recents[0]["n"] == 1
    older = recents[1]
    assert older["query"] == "order aggregate invariants"
    assert older["mechanism"] == "rrf+rerank"
    assert older["n"] == 2
    assert older["hits"][0]["path"] == "domain/order.md"


def test_recent_recalls_honors_limit_and_is_separate_from_hits(initialised_vault):
    """recent_recalls reads only grouped `recall` events; recall_hit events
    (dead-weight detection) stay separate and don't leak into the audit list."""
    import usage
    usage.log_recall_hits([("decisions/a.md", "decisions", 0)])
    for i in range(5):
        usage.log_recall(f"q{i}", "all", [("x.md", "all", 0)], "fts")
    recents = usage.recent_recalls(limit=3)
    assert len(recents) == 3
    assert all(e["event"] == "recall" for e in recents)
    # The recall_hit still feeds summary, not the audit trail.
    assert usage.summary()["recall_hits"] == 1


def test_log_recall_truncates_long_query(initialised_vault):
    """A pathological query is capped so the ledger can't bloat."""
    import usage
    usage.log_recall("z" * 1000, "all", [], "fts")
    assert len(usage.recent_recalls()[0]["query"]) == 300


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

"""Tests for inbox.py (the notify/question/review queue) and its surfacing
through the nudge and the dashboard."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))


def _write(mem, rel, content):
    p = mem / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


def _backdate(p: Path, days: float):
    old = time.time() - days * 86400
    os.utime(p, (old, old))


def _proposition(mem, rel, title, status, age_days):
    p = _write(mem, rel, f"---\ntitle: {title}\nstatus: {status}\n---\nbody\n")
    _backdate(p, age_days)
    return p


# --- inbox.aging_questions --------------------------------------------------

def test_aging_questions_includes_old_open(initialised_vault):
    import db
    import inbox
    mem = initialised_vault
    _proposition(mem, "propositions/2026-05-01-shard.md",
                 "Should we shard tenants", "open", age_days=3)
    db.reindex(force=True)
    qs = inbox.aging_questions()
    assert any("shard" in q["title"].lower() for q in qs)


def test_aging_questions_excludes_fresh(initialised_vault):
    import db
    import inbox
    mem = initialised_vault
    _proposition(mem, "propositions/2026-05-30-fresh.md",
                 "Fresh question", "open", age_days=0)
    db.reindex(force=True)
    qs = inbox.aging_questions(min_age_days=1)
    assert not any("fresh" in q["title"].lower() for q in qs)


def test_aging_questions_excludes_settled(initialised_vault):
    import db
    import inbox
    mem = initialised_vault
    _proposition(mem, "propositions/2026-05-01-done.md",
                 "Settled already", "settled-as-decision", age_days=5)
    db.reindex(force=True)
    qs = inbox.aging_questions()
    assert not any("settled already" in q["title"].lower() for q in qs)


def test_aging_questions_includes_converging_but_nudge_set_excludes_it(
        initialised_vault):
    import db
    import inbox
    mem = initialised_vault
    _proposition(mem, "propositions/2026-05-01-conv.md",
                 "Converging question", "converging", age_days=3)
    db.reindex(force=True)
    # Default (dashboard) set includes converging...
    assert any("converging question" in q["title"].lower()
               for q in inbox.aging_questions())
    # ...but the nudge narrows to open/contested, so it's excluded there.
    assert not inbox.aging_questions(statuses=("open", "contested"))


# --- nudge surfacing (batched, default-silent) ------------------------------

def _snap():
    return {"available": True, "branch": "feat/x", "commits": [],
            "uncommitted": [], "suggested_topic": "x", "hot_paths": [],
            "head_sha": "abc123"}


def test_nudge_mentions_questions_singular(initialised_vault):
    import db
    import nudge_common
    mem = initialised_vault
    _proposition(mem, "propositions/2026-05-01-q.md",
                 "Open question", "open", age_days=3)
    db.reindex(force=True)
    msg = nudge_common.build_message(_snap(), drafted=False, branch="feat/x")
    assert "awaiting your input" in msg.lower()
    assert "1 question " in msg          # singular
    assert "questions awaiting" not in msg


def test_nudge_pluralizes_questions(initialised_vault):
    import db
    import nudge_common
    mem = initialised_vault
    _proposition(mem, "propositions/2026-05-01-a.md", "Q A", "open", age_days=3)
    _proposition(mem, "propositions/2026-05-02-b.md", "Q B", "contested",
                 age_days=2)
    db.reindex(force=True)
    msg = nudge_common.build_message(_snap(), drafted=False, branch="feat/x")
    assert "2 questions awaiting" in msg


def test_nudge_silent_for_converging_only(initialised_vault):
    import db
    import nudge_common
    mem = initialised_vault
    _proposition(mem, "propositions/2026-05-01-c.md", "Converging only",
                 "converging", age_days=3)
    db.reindex(force=True)
    msg = nudge_common.build_message(_snap(), drafted=False, branch="feat/x")
    assert "awaiting your input" not in msg.lower()


def test_nudge_silent_when_no_aging_questions(initialised_vault):
    import db
    import nudge_common
    db.reindex(force=True)
    msg = nudge_common.build_message(_snap(), drafted=False, branch="feat/x")
    assert "awaiting your input" not in msg.lower()


# --- dashboard section ------------------------------------------------------

def test_dashboard_awaiting_input_lists_questions(initialised_vault):
    import dashboard
    import db
    mem = initialised_vault
    _proposition(mem, "propositions/2026-05-01-q.md",
                 "Lingering dashboard Q", "contested", age_days=3)
    db.reindex(force=True)
    bullets = dashboard._awaiting_input_bullets()
    assert any("lingering dashboard q" in b.lower() for b in bullets)

"""Tests for the status:auto staged-observation lane (observe.py) + its
surfacing through the inbox/dashboard review queue."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import frontmatter

HERE = Path(__file__).resolve().parent
PLUGIN_ROOT = HERE.parent
OBSERVE = PLUGIN_ROOT / "scripts" / "observe.py"
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))


def _run(args, body="", env=None):
    e = os.environ.copy()
    if env:
        e.update(env)
    return subprocess.run(
        [sys.executable, str(OBSERVE), *args],
        input=body, capture_output=True, text=True, check=False, env=e,
    )


def _created_path(r) -> Path:
    """The note path observe.py printed (init seeds sample notes, so a bare
    glob is ambiguous)."""
    for line in r.stdout.splitlines():
        if "auto-captured observation" in line and "→" in line:
            return Path(line.split("→", 1)[1].strip())
    raise AssertionError(f"no created-path line in stdout: {r.stdout!r}")


def test_observe_writes_grounded_staged_note(initialised_vault):
    mem = initialised_vault
    r = _run(["--topic", "retry budget bumped", "--source-file", "src/http.py"],
             body="Commit bumped the retry budget 3→5 in the HTTP client.",
             env=os.environ.copy())
    assert r.returncode == 0, r.stderr
    notes = list((mem / "pr-context").rglob("*retry-budget-bumped.md"))
    assert notes, "observation not written to pr-context"
    post = frontmatter.load(notes[0])
    assert post.metadata["status"] == "auto"        # quarantine tier
    assert post.metadata["kind"] == "observation"
    assert post.metadata["source"] == "git-derived"  # provenance
    assert post.metadata["source_file"] == "src/http.py"


def test_save_observe_mode_delegates_to_capture(initialised_vault):
    """`save-note.py --observe` writes a status:auto observation via the shared
    guarded path (the observe→save fold), grounding required."""
    import frontmatter
    mem = initialised_vault
    save = PLUGIN_ROOT / "scripts" / "save-note.py"
    r = subprocess.run(
        [sys.executable, str(save), "--observe", "--topic", "folded obs",
         "--source-file", "src/x.py"],
        input="grounded via save --observe", capture_output=True, text=True,
        check=False, env=os.environ.copy())
    assert r.returncode == 0, r.stderr
    notes = list((mem / "pr-context").rglob("*folded-obs.md"))
    assert notes, "save --observe did not write an observation"
    assert frontmatter.load(notes[0]).metadata["status"] == "auto"
    # Grounding guardrail still enforced through the delegated path.
    r2 = subprocess.run(
        [sys.executable, str(save), "--observe", "--topic", "ungrounded"],
        input="no grounding", capture_output=True, text=True, check=False,
        env=os.environ.copy())
    assert r2.returncode == 2


def test_save_observe_note_quarantined_from_recall(initialised_vault):
    """The guardrail that matters most, through the save --observe entry point:
    a status:auto observation must stay OUT of recall."""
    import db
    save = PLUGIN_ROOT / "scripts" / "save-note.py"
    subprocess.run(
        [sys.executable, str(save), "--observe", "--topic", "via save",
         "--source-file", "src/x.py"],
        input="grounded marker zsaveobsquarantine", capture_output=True,
        text=True, check=False, env=os.environ.copy())
    db.reindex(force=True)
    assert db.search(["zsaveobsquarantine"])[1] == 0
    assert any("via-save" in a["path"] for a in __import__("inbox").auto_notes())


def test_observe_refuses_without_grounding(initialised_vault):
    """An auto-write must be anchored to a verifiable artifact."""
    r = _run(["--topic", "ungrounded musing"],
             body="just a thought, no source", env=os.environ.copy())
    assert r.returncode == 2
    assert "grounded" in r.stderr.lower()


def test_observe_refuses_empty_body(initialised_vault):
    r = _run(["--topic", "x", "--commit", "abc1234"], body="",
             env=os.environ.copy())
    assert r.returncode == 2


def test_observe_colon_topic_stays_quarantined(initialised_vault):
    """A conventional-commit topic with a colon must NOT break frontmatter into
    status=None (the fail-open) — status stays 'auto' and it's out of recall."""
    import frontmatter

    import db
    r = _run(["--topic", "fix: retry budget 3 to 5", "--source-file", "src/http.py"],
             body="grounded note with unique marker zcolonquarantine.",
             env=os.environ.copy())
    assert r.returncode == 0, r.stderr
    note = _created_path(r)
    assert frontmatter.load(note).metadata["status"] == "auto"  # not None
    db.reindex(force=True)
    assert db.search(["zcolonquarantine"])[1] == 0  # quarantined from recall


def test_observe_topic_newline_injection_blocked(initialised_vault):
    """A newline in --topic must not inject a second `status:` key that flips
    the note out of quarantine."""
    import frontmatter
    r = _run(["--topic", "evil\nstatus: reviewed", "--source-file", "src/x.py"],
             body="grounded", env=os.environ.copy())
    assert r.returncode == 0, r.stderr
    note = _created_path(r)
    assert frontmatter.load(note).metadata["status"] == "auto"  # not 'reviewed'


def test_source_file_index_excludes_auto(initialised_vault):
    """An auto-note's source_file must not surface in the by-file index that
    feeds the SessionStart primer."""
    import db
    _run(["--topic", "obs", "--source-file", "src/onlyauto.py"],
         body="grounded note", env=os.environ.copy())
    db.reindex(force=True)
    assert all(e["source_file"] != "src/onlyauto.py"
               for e in db.source_file_index())


def test_observe_grounds_on_commit(initialised_vault):
    mem = initialised_vault
    r = _run(["--topic", "schema migrated", "--commit", "deadbeef"],
             body="Schema v2 landed in this commit.", env=os.environ.copy())
    assert r.returncode == 0, r.stderr
    notes = list((mem / "pr-context").rglob("*schema-migrated.md"))
    post = frontmatter.load(notes[0])
    assert post.metadata["grounded_in"] == "deadbeef"


def test_observe_is_observation_only_no_decisions(initialised_vault):
    """Structural guardrail: observe.py exposes no scope flag, so an agent can
    never reach decisions/ through it — they stay human-ratified."""
    mem = initialised_vault
    _run(["--topic", "anything", "--source-file", "a.py"],
         body="grounded note", env=os.environ.copy())
    # Nothing landed outside pr-context.
    assert not list((mem / "decisions").glob("*anything*.md"))
    assert not list((mem / "domain").glob("*anything*.md"))


# --- surfacing in the review queue -----------------------------------------

def _write(mem, rel, content):
    p = mem / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


def test_inbox_auto_notes_surfaces_staged(initialised_vault):
    import db
    import inbox
    mem = initialised_vault
    _write(mem, "pr-context/feat-x/2026-05-30-1200--gk--obs.md",
           "---\nkind: observation\nstatus: auto\nsource: git-derived\n"
           "title: Staged obs\n---\nbody\n")
    db.reindex(force=True)
    autos = inbox.auto_notes()
    assert any(a["path"].endswith("gk--obs.md") for a in autos)
    assert all(isinstance(a.get("age_days"), int) for a in autos)  # decay signal


def test_auto_notes_quarantined_from_recall(initialised_vault):
    """status:auto content must NOT surface in normal recall (it's unreviewed),
    only in the review queue — else auto-capture would pollute recall."""
    import db
    import inbox
    mem = initialised_vault
    _write(mem, "pr-context/feat-x/2026-05-30-1200--gk--quarantined.md",
           "---\nkind: observation\nstatus: auto\nsource: git-derived\n"
           "title: Quarantined obs\n---\nUnique marker zxqquarantine.\n")
    db.reindex(force=True)
    # Excluded from recall...
    assert db.search(["zxqquarantine"])[1] == 0
    # ...but present in the review queue.
    assert any("quarantined" in a["path"] for a in inbox.auto_notes())


def test_dashboard_surfaces_auto_captured(initialised_vault):
    import dashboard
    import db
    mem = initialised_vault
    _write(mem, "pr-context/feat-x/2026-05-30-1200--gk--obs.md",
           "---\nkind: observation\nstatus: auto\nsource: git-derived\n"
           "title: Dashboard staged obs\n---\nbody\n")
    db.reindex(force=True)
    bullets = dashboard._awaiting_input_bullets()
    assert any("auto-captured" in b.lower() and "dashboard staged obs" in b.lower()
               for b in bullets)


def test_dashboard_recent_activity_excludes_auto(initialised_vault):
    """An auto-note must NOT appear in canonical 'recent activity' — only in the
    review queue (else it triple-surfaces as if it were ratified)."""
    import dashboard
    mem = initialised_vault
    _write(mem, "pr-context/feat-x/2026-05-30-1200--gk--zrecent.md",
           "---\nkind: observation\nstatus: auto\nsource: git-derived\n"
           "title: zrecentauto\n---\nbody\n")
    rows = dashboard._recent_activity()
    assert all("zrecent" not in r["path"] for r in rows)


# --- auto-discard floor (the missing third bucket) -------------------------

def _observations(mem):
    return [n for n in (mem / "pr-context").rglob("*.md")
            if frontmatter.load(n).metadata.get("kind") == "observation"]


def test_observe_discards_near_duplicate(initialised_vault):
    """A near-identical observation is dropped, not queued — the quarantine
    lane must not fill with redundant re-captures."""
    mem = initialised_vault
    body = ("The pricing process manager now emits OrderPriced strictly before "
            "OrderConfirmed so downstream projections never read a stale total.")
    r1 = _run(["--topic", "event order fixed", "--source-file", "src/orders.py"],
              body=body, env=os.environ.copy())
    assert r1.returncode == 0, r1.stderr
    # Same content, different topic → should be discarded as a near-duplicate.
    r2 = _run(["--topic", "ordering note again", "--source-file", "src/orders.py"],
              body=body + " Small clarifying addendum.", env=os.environ.copy())
    assert r2.returncode == 0
    assert "near-duplicate" in (r2.stdout + r2.stderr).lower(), r2.stdout
    assert len(_observations(mem)) == 1, "near-duplicate must not be queued"


def test_observe_keeps_distinct_observation(initialised_vault):
    """A genuinely different observation is still captured (floor is targeted)."""
    mem = initialised_vault
    _run(["--topic", "retry", "--source-file", "src/a.py"],
         body="The retry budget was raised from three to five attempts.",
         env=os.environ.copy())
    _run(["--topic", "cache", "--source-file", "src/b.py"],
         body="Caching switched to an in-process LRU with a 512 entry cap.",
         env=os.environ.copy())
    assert len(_observations(mem)) == 2

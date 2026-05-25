"""Tests for migrate-bootstrap-to-lessons.py.

Moves bootstrap-origin notes (frontmatter has `source_file:`) out of
`pr-context/<branch>/` into `lessons/`. Live-work notes (no
source_file) stay put.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "migrate-bootstrap-to-lessons.py"


def _run(*args, env=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, check=False,
        env=env,
    )


def _write_note(p: Path, frontmatter: dict, body: str = "body\n"):
    p.parent.mkdir(parents=True, exist_ok=True)
    fm_lines = ["---"]
    for k, v in frontmatter.items():
        fm_lines.append(f"{k}: {v}")
    fm_lines.append("---\n\n")
    p.write_text("\n".join(fm_lines) + body)


def test_dry_run_reports_without_moving(initialised_vault):
    mem = initialised_vault
    src = mem / "pr-context" / "feat-x" / "2026-05-24-1015--gd--legacy.md"
    _write_note(src, {
        "branch": "feat/x", "kind": "handoff", "topic": "legacy-thing",
        "source_file": "docs/old.md", "created": "2026-05-24",
    })

    r = _run(env=os.environ.copy())
    assert r.returncode == 0
    assert "Would move" in r.stdout
    # File still in pr-context
    assert src.exists()


def test_apply_moves_to_lessons(initialised_vault):
    mem = initialised_vault
    src = mem / "pr-context" / "feat-x" / "2026-05-24-1015--gd--legacy.md"
    _write_note(src, {
        "branch": "feat/x", "kind": "handoff",
        "topic": "build velocity audit",
        "source_file": "docs/old.md", "created": "2026-05-24",
    })

    r = _run("--apply", env=os.environ.copy())
    assert r.returncode == 0
    # Original gone
    assert not src.exists()
    # New note in lessons with date-prefixed filename derived from `created`
    matches = list((mem / "lessons").glob("2026-05-24-build-velocity-audit.md"))
    assert matches, f"target not found in lessons/, got: {list((mem / 'lessons').iterdir())}"


def test_live_work_note_without_source_file_is_left_alone(initialised_vault):
    """Live PR-context notes (no source_file frontmatter) are NOT
    migrated — they were authored in-session, not extracted."""
    mem = initialised_vault
    src = mem / "pr-context" / "feat-x" / "2026-05-24-0930--gd--live-work.md"
    _write_note(src, {
        "branch": "feat/x", "kind": "session", "topic": "live-work",
        # NO source_file
    })

    r = _run("--apply", env=os.environ.copy())
    assert r.returncode == 0
    # Still where it was
    assert src.exists()


def test_filename_collision_gets_suffixed(initialised_vault):
    """Two bootstrap notes with same date+topic → second gets `-2` suffix."""
    mem = initialised_vault
    for i, fname in enumerate([
        "2026-05-24-1015--gd--same-topic.md",
        "2026-05-24-1230--gd--same-topic.md",
    ]):
        _write_note(
            mem / "pr-context" / "feat-x" / fname,
            {"branch": "feat/x", "kind": "handoff", "topic": "same topic",
             "source_file": f"docs/{i}.md", "created": "2026-05-24"},
        )

    r = _run("--apply", env=os.environ.copy())
    assert r.returncode == 0
    lessons = list((mem / "lessons").glob("2026-05-24-same-topic*.md"))
    assert len(lessons) == 2, f"expected 2 lessons, got: {lessons}"
    names = sorted(f.name for f in lessons)
    assert names == ["2026-05-24-same-topic-2.md",
                     "2026-05-24-same-topic.md"]


def test_no_matches_reports_cleanly(initialised_vault):
    r = _run(env=os.environ.copy())
    assert r.returncode == 0
    assert "Nothing to migrate" in r.stdout or "no bootstrap" in r.stdout.lower()

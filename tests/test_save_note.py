"""Tests for save-note.py — pr-context vs lessons scoping.

The split exists because bootstrap-extracted content is historical and
has no current branch context — it must land in `lessons/`, not
`pr-context/<current-branch>/`. An earlier bug routed bootstrap saves
to pr-context; these tests pin the fix.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SAVE = HERE.parent / "scripts" / "save-note.py"


def _run(*args, body: str = "body content\n", env=None):
    return subprocess.run(
        [sys.executable, str(SAVE), *args],
        input=body, capture_output=True, text=True, check=False,
        env=env,
    )


def test_default_scope_writes_to_pr_context(initialised_vault):
    """No --scope flag → pr-context/<branch>/ (preserves existing behaviour)."""
    mem = initialised_vault
    r = _run("--topic", "auth-rewrite-session", "--kind", "session",
             env=os.environ.copy())
    assert r.returncode == 0
    pr = mem / "pr-context" / "feat-test-branch"
    matches = list(pr.glob("*--auth-rewrite-session.md"))
    assert matches, f"expected pr-context note, got nothing in {pr}"
    # No lessons file should have been written
    lessons = mem / "lessons"
    if lessons.exists():
        for f in lessons.glob("*.md"):
            assert "auth-rewrite-session" not in f.name


def test_scope_lessons_writes_to_lessons_dir(initialised_vault):
    """--scope lessons → lessons/YYYY-MM-DD-<topic>.md, no branch prefix."""
    mem = initialised_vault
    r = _run("--topic", "build-velocity-audit", "--scope", "lessons",
             "--kind", "handoff", "--source-file",
             "docs/audits/2026-04-29.md",
             env=os.environ.copy())
    assert r.returncode == 0, f"stderr: {r.stderr}"
    lessons = mem / "lessons"
    matches = list(lessons.glob("*-build-velocity-audit.md"))
    assert matches, f"expected lessons note, got nothing in {lessons}"
    body = matches[0].read_text()
    # Frontmatter: NO branch field for lessons scope
    assert "branch:" not in body.split("---")[1]
    # source_file preserved
    assert "source_file: docs/audits/2026-04-29.md" in body
    # kind preserved
    assert "kind: handoff" in body


def test_scope_lessons_filename_is_date_prefixed_only(initialised_vault):
    """Lessons filename: `YYYY-MM-DD-<topic>.md` — no time, no initials.
    Matches the existing lessons/2026-04-29-build-velocity-vs-birdie.md
    convention. PR-context uses HHMM + initials because branch work can
    have several notes per day per person; lessons should not."""
    mem = initialised_vault
    r = _run("--topic", "auth-rewrite-lessons", "--scope", "lessons",
             env=os.environ.copy())
    assert r.returncode == 0
    name = next((mem / "lessons").glob("*auth-rewrite-lessons.md")).name
    # YYYY-MM-DD prefix (10 chars + dash)
    assert name[:10].count("-") == 2
    assert name[10] == "-"
    # No HHMM segment, no `--<initials>--` segment
    assert "--" not in name


def test_scope_lessons_no_branch_in_frontmatter(initialised_vault):
    """Branch is irrelevant for a lesson — must be omitted, not set to
    whatever branch the user happens to be on at extraction time."""
    mem = initialised_vault
    r = _run("--topic", "historical-context", "--scope", "lessons",
             env=os.environ.copy())
    assert r.returncode == 0
    note = next((mem / "lessons").glob("*historical-context.md"))
    fm = note.read_text().split("---")[1]
    assert "branch:" not in fm

"""Tests for the repeatable --source-file flag + --project-dir override
added to new-decision.py and save-note.py for multi-source consolidation
during /strata:bootstrap."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import frontmatter

HERE = Path(__file__).resolve().parent
PLUGIN_ROOT = HERE.parent
NEW_DECISION = PLUGIN_ROOT / "scripts" / "new-decision.py"
SAVE_NOTE = PLUGIN_ROOT / "scripts" / "save-note.py"


def _run(script: Path, *args, stdin: str = "", env=None):
    return subprocess.run(
        [sys.executable, str(script), *args],
        input=stdin,
        capture_output=True, text=True, check=False,
        env=env,
    )


def test_new_decision_accepts_single_source_file(initialised_vault, env):
    r = _run(
        NEW_DECISION,
        "--title", "Use Postgres",
        "--status", "accepted",
        "--source-file", ".planning/auth/PLAN.md",
        stdin="## Context\nx\n## Decision\ny\n",
        env=os.environ.copy(),
    )
    assert r.returncode == 0, r.stderr
    adr = next((env["vault"] / "myrepo" / "decisions").glob("*-use-postgres.md"))
    post = frontmatter.load(adr)
    # Single source → stored as a string, preserves existing behaviour
    assert post.metadata["source_file"] == ".planning/auth/PLAN.md"


def test_new_decision_accepts_repeated_source_file(initialised_vault, env):
    r = _run(
        NEW_DECISION,
        "--title", "Section-at-once pattern",
        "--status", "accepted",
        "--source-file", ".planning/auth/PLAN.md",
        "--source-file", ".planning/auth/SPEC.md",
        "--source-file", ".planning/auth/CONTEXT.md",
        stdin="## Context\nx\n## Decision\ny\n",
        env=os.environ.copy(),
    )
    assert r.returncode == 0, r.stderr
    adr = next((env["vault"] / "myrepo" / "decisions").glob("*-section-at-once-pattern.md"))
    post = frontmatter.load(adr)
    # Multiple sources → stored as a list, preserves full provenance
    assert isinstance(post.metadata["source_file"], list)
    assert post.metadata["source_file"] == [
        ".planning/auth/PLAN.md",
        ".planning/auth/SPEC.md",
        ".planning/auth/CONTEXT.md",
    ]


def test_new_decision_accepts_comma_joined_source_file(initialised_vault, env):
    r = _run(
        NEW_DECISION,
        "--title", "Comma joined sources",
        "--status", "accepted",
        "--source-file", ".planning/a.md, .planning/b.md, .planning/c.md",
        stdin="## Context\nx\n## Decision\ny\n",
        env=os.environ.copy(),
    )
    assert r.returncode == 0, r.stderr
    adr = next((env["vault"] / "myrepo" / "decisions").glob("*-comma-joined-sources.md"))
    post = frontmatter.load(adr)
    assert post.metadata["source_file"] == [".planning/a.md", ".planning/b.md", ".planning/c.md"]


def test_new_decision_dedupes_source_files(initialised_vault, env):
    r = _run(
        NEW_DECISION,
        "--title", "Dedup test",
        "--status", "accepted",
        "--source-file", "x.md",
        "--source-file", "x.md",
        "--source-file", "y.md",
        stdin="## Context\nx\n## Decision\ny\n",
        env=os.environ.copy(),
    )
    assert r.returncode == 0, r.stderr
    adr = next((env["vault"] / "myrepo" / "decisions").glob("*-dedup-test.md"))
    post = frontmatter.load(adr)
    assert post.metadata["source_file"] == ["x.md", "y.md"]


def test_save_note_lessons_repeatable_source_file(initialised_vault, env):
    r = _run(
        SAVE_NOTE,
        "--scope", "lessons",
        "--kind", "handoff",
        "--topic", "multi-source retro",
        "--source-file", "old/A.md",
        "--source-file", "old/B.md",
        stdin="- bullet 1\n- bullet 2\n",
        env=os.environ.copy(),
    )
    assert r.returncode == 0, r.stderr
    note = next((env["vault"] / "myrepo" / "lessons").glob("*-multi-source-retro.md"))
    body = note.read_text()
    # YAML list format when there are multiple sources
    assert "source_file:" in body
    assert "  - old/A.md" in body
    assert "  - old/B.md" in body


def test_save_note_project_dir_pins_namespace(initialised_vault, env, tmp_path,
                                                monkeypatch):
    """`--project-dir` overrides cwd-based namespace resolution. Without it,
    a worker that forgets to cd would write to the wrong vault namespace
    (the bug surfaced in an earlier quality audit)."""
    other_repo = tmp_path / "other-repo"
    other_repo.mkdir()
    # Make it a git repo with a remote so repo_name() resolves to "other-repo"
    subprocess.run(["git", "init", "-q"], cwd=other_repo, check=True)
    subprocess.run(["git", "remote", "add", "origin",
                    "https://example.invalid/test/other-repo.git"],
                   cwd=other_repo, check=True)

    r = _run(
        SAVE_NOTE,
        "--scope", "lessons",
        "--kind", "handoff",
        "--topic", "pinned namespace",
        "--project-dir", str(other_repo),
        stdin="- pinned to other-repo\n",
        env=os.environ.copy(),
    )
    assert r.returncode == 0, r.stderr
    # Note should land under the OTHER repo's namespace, NOT myrepo
    other_lessons = env["vault"] / "other-repo" / "lessons"
    assert other_lessons.exists()
    assert any(other_lessons.glob("*-pinned-namespace.md"))
    # And NOT in myrepo
    myrepo_lessons = env["vault"] / "myrepo" / "lessons"
    if myrepo_lessons.exists():
        assert not any(myrepo_lessons.glob("*-pinned-namespace.md"))

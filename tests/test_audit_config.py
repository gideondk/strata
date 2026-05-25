"""Tests for /strata:audit-config — drift detection."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
AUDIT = HERE.parent / "scripts" / "audit-config.py"


def _run(*args, env=None):
    return subprocess.run(
        [sys.executable, str(AUDIT), *args],
        capture_output=True, text=True, check=False,
        env=env,
    )


def _backdate(path: Path, days: int) -> None:
    t = time.time() - days * 86400
    os.utime(path, (t, t))


def test_reports_no_files_when_nothing_present(env):
    r = _run(env=os.environ.copy())
    assert r.returncode == 0
    assert "(not present)" in r.stdout
    assert "good" in r.stdout.lower()


def test_flags_stale_claude_md(env):
    pd = env["repo"]
    cm = pd / "CLAUDE.md"
    cm.write_text("# Project conventions\n")
    _backdate(cm, 365)  # well past 180-day default

    r = _run(env=os.environ.copy())
    assert r.returncode == 0
    assert "STALE" in r.stdout
    assert "CLAUDE.md" in r.stdout


def test_fresh_claude_md_not_flagged(env):
    pd = env["repo"]
    (pd / "CLAUDE.md").write_text("fresh\n")
    r = _run(env=os.environ.copy())
    assert r.returncode == 0
    assert "STALE" not in r.stdout


def test_parses_settings_json(env):
    pd = env["repo"]
    claude_dir = pd / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    (claude_dir / "settings.json").write_text(
        '{"enabledPlugins": ["strata@local", "other@local"], '
        '"hooks": {"SessionStart": []}}'
    )
    r = _run(env=os.environ.copy())
    assert r.returncode == 0
    assert "enabled plugins: 2" in r.stdout
    assert "strata@local" in r.stdout


def test_counts_project_local_skills(env):
    pd = env["repo"]
    skills = pd / ".claude" / "skills"
    (skills / "skill-one").mkdir(parents=True)
    (skills / "skill-one" / "SKILL.md").write_text("# one\n")
    (skills / "skill-two").mkdir(parents=True)
    (skills / "skill-two" / "SKILL.md").write_text("# two\n")
    r = _run(env=os.environ.copy())
    assert r.returncode == 0
    assert "2 item(s)" in r.stdout


def test_custom_stale_threshold(env):
    pd = env["repo"]
    cm = pd / "CLAUDE.md"
    cm.write_text("a\n")
    _backdate(cm, 60)
    # Default 180 → not stale
    r = _run(env=os.environ.copy())
    assert "STALE" not in r.stdout
    # Threshold 30 → stale
    r2 = _run("--stale-days", "30", env=os.environ.copy())
    assert "STALE" in r2.stdout


def test_no_project_returns_2(env, monkeypatch):
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    # Also nuke cwd's .git presence by chdir'ing to /tmp
    monkeypatch.chdir("/tmp")
    r = _run(env=os.environ.copy())
    assert r.returncode == 2

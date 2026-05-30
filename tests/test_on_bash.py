"""Tests for the PostToolUse(Bash) hook — commit-boundary save-nudge."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ON_BASH = HERE.parent / "scripts" / "on-bash.py"


def _run(command: str, env=None):
    payload = json.dumps({"tool_input": {"command": command}})
    return subprocess.run(
        [sys.executable, str(ON_BASH)],
        input=payload,
        capture_output=True, text=True, check=False,
        env=env,
    )


def _git_in(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True)


def test_commit_boundary_nudges(initialised_vault, env):
    """A `git commit` that advanced HEAD triggers a save-nudge."""
    repo = env["repo"]
    (repo / "a.py").write_text("# a\n")
    _git_in(repo, "add", "a.py")
    _git_in(repo, "commit", "-qm", "feat: a")

    r = _run("git commit -m 'feat: a'", env=os.environ.copy())
    assert r.returncode == 0
    assert r.stdout, "expected a systemMessage nudge after commit"
    payload = json.loads(r.stdout)
    assert "systemMessage" in payload
    assert "strata:save" in payload["systemMessage"]


def test_commit_boundary_stashes_draft_when_threshold_met(
        initialised_vault, env):
    """3+ commits in the window → the commit nudge stashes a draft and offers
    --apply-draft, same as the Stop surface."""
    import draft_store
    repo = env["repo"]
    for i in range(3):
        (repo / f"f{i}.py").write_text(f"# {i}\n")
        _git_in(repo, "add", f"f{i}.py")
        _git_in(repo, "commit", "-qm", f"feat: change {i}")

    r = _run("git commit -m 'feat: change 2'", env=os.environ.copy())
    assert r.stdout
    msg = json.loads(r.stdout)["systemMessage"]
    assert "--apply-draft" in msg, f"missing apply-draft hint: {msg!r}"
    assert draft_store.load_draft() is not None


def test_commit_boundary_dedup_same_head(initialised_vault, env):
    """Two commit commands at the same HEAD nudge only once."""
    repo = env["repo"]
    (repo / "a.py").write_text("# a\n")
    _git_in(repo, "add", "a.py")
    _git_in(repo, "commit", "-qm", "feat: a")

    r1 = _run("git commit -m x", env=os.environ.copy())
    assert r1.stdout, "first commit should nudge"
    r2 = _run("git commit -m x", env=os.environ.copy())
    assert r2.stdout == "", "second nudge at same HEAD should be silent"


def test_non_commit_command_is_noop(initialised_vault, env):
    """A plain command emits nothing."""
    r = _run("ls -la", env=os.environ.copy())
    assert r.returncode == 0
    assert r.stdout == ""


def test_commit_nudge_silent_without_vault(env):
    """No vault initialised → commit boundary stays silent."""
    repo = env["repo"]
    (repo / "a.py").write_text("# a\n")
    _git_in(repo, "add", "a.py")
    _git_in(repo, "commit", "-qm", "feat: a")

    r = _run("git commit -m 'feat: a'", env=os.environ.copy())
    assert r.returncode == 0
    assert r.stdout == ""


def test_branch_switch_still_reprimes(initialised_vault, env):
    """The branch-switch path is unchanged: a checkout emits a primer via
    additionalContext, not a systemMessage."""
    r = _run("git switch some-feature", env=os.environ.copy())
    assert r.returncode == 0
    assert r.stdout, "branch switch should emit a primer"
    payload = json.loads(r.stdout)
    assert "hookSpecificOutput" in payload
    assert payload["hookSpecificOutput"]["hookEventName"] == "PostToolUse"

"""Tests for archive-planning.py — git mv .planning/<x> → .attic/<x>
after the subdir has been bootstrap-processed.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "archive-planning.py"


def _run(*args, env=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, check=False,
        env=env,
    )


def _git(repo, *args, **kw):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True, **kw)


def _seed_state(mem: Path, paths: dict[str, str]) -> None:
    """Write a bootstrap-state.json with the given {path: sha256} map."""
    mem.mkdir(parents=True, exist_ok=True)
    state = {
        "processed_files": {p: {"sha256": s, "processed_at": "now"}
                            for p, s in paths.items()},
        "graphify_built": False,
    }
    (mem / ".bootstrap-state.json").write_text(json.dumps(state))


def _sha256(p: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def test_dry_run_refuses_unprocessed_subdir(initialised_vault, env):
    """Default: refuse to archive when files haven't been bootstrap-
    processed. Knowledge would be lost in the move."""
    pd = env["repo"]
    (pd / ".planning" / "x").mkdir(parents=True)
    (pd / ".planning" / "x" / "PLAN.md").write_text("plan\n")
    _git(pd, "add", ".")
    _git(pd, "commit", "-qm", "add plan")

    r = _run(".planning/x", env=os.environ.copy())
    assert r.returncode == 2
    assert "bootstrap-processed" in r.stderr.lower()
    assert "refusing" in r.stderr.lower()
    # Source dir still in place
    assert (pd / ".planning" / "x").is_dir()


def test_dry_run_clean_when_all_processed(initialised_vault, env):
    pd = env["repo"]
    (pd / ".planning" / "x").mkdir(parents=True)
    pf = pd / ".planning" / "x" / "PLAN.md"
    pf.write_text("plan\n")
    _git(pd, "add", ".")
    _git(pd, "commit", "-qm", "add plan")

    mem = initialised_vault
    _seed_state(mem, {".planning/x/PLAN.md": _sha256(pf)})

    r = _run(".planning/x", env=os.environ.copy())
    assert r.returncode == 0
    assert "Will move" in r.stdout
    assert "dry-run" in r.stdout
    # Still in place — no --apply
    assert (pd / ".planning" / "x").is_dir()


def test_apply_moves_to_attic_and_commits(initialised_vault, env):
    pd = env["repo"]
    (pd / ".planning" / "auth").mkdir(parents=True)
    pf = pd / ".planning" / "auth" / "PLAN.md"
    pf.write_text("auth plan\n")
    _git(pd, "add", ".")
    _git(pd, "commit", "-qm", "add auth plan")

    mem = initialised_vault
    _seed_state(mem, {".planning/auth/PLAN.md": _sha256(pf)})

    r = _run(".planning/auth", "--apply", env=os.environ.copy())
    assert r.returncode == 0
    # Source moved
    assert not (pd / ".planning" / "auth").exists()
    # Target exists in attic
    assert (pd / ".attic" / "auth" / "PLAN.md").exists()
    # New commit landed
    log = _git(pd, "log", "--oneline", "-1").stdout
    assert "archive planning" in log


def test_force_archives_unprocessed_anyway(initialised_vault, env):
    pd = env["repo"]
    (pd / ".planning" / "scratch").mkdir(parents=True)
    (pd / ".planning" / "scratch" / "BRAINSTORM.md").write_text("\n")
    _git(pd, "add", ".")
    _git(pd, "commit", "-qm", "scratch")

    # No state seeded — file is unprocessed
    r = _run(".planning/scratch", "--apply", "--force",
             env=os.environ.copy())
    assert r.returncode == 0
    assert not (pd / ".planning" / "scratch").exists()
    assert (pd / ".attic" / "scratch" / "BRAINSTORM.md").exists()


def test_refuses_traversal(initialised_vault, env):
    r = _run("../../etc", env=os.environ.copy())
    assert r.returncode == 2

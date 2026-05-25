"""Shared fixtures: build a temp vault + project for each test."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PLUGIN_ROOT = HERE.parent


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Set up CLAUDE_PROJECT_DIR + STRATA_VAULT_PATH against fresh tmp dirs."""
    vault = tmp_path / "vault"
    repo = tmp_path / "myrepo"
    data = tmp_path / "plugin-data"
    vault.mkdir()
    repo.mkdir()
    data.mkdir()

    # Make a real git repo so is_git_repo() / current_branch() work
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@strata.local"],
                   cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"],
                   cwd=repo, check=True)
    subprocess.run(["git", "remote", "add", "origin",
                    "https://example.invalid/test/myrepo.git"],
                   cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-q", "-b", "feat/test-branch"],
                   cwd=repo, check=True)
    (repo / "README.md").write_text("init\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(PLUGIN_ROOT))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(data))
    monkeypatch.setenv("STRATA_VAULT_PATH", str(vault))
    monkeypatch.delenv("STRATA_REPO_NAME", raising=False)

    # Ensure scripts/ is importable
    scripts = str(PLUGIN_ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    mcp_dir = str(PLUGIN_ROOT / "mcp")
    if mcp_dir not in sys.path:
        sys.path.insert(0, mcp_dir)

    # Wipe any cached lib state from prior tests
    for mod in list(sys.modules):
        if mod in ("lib", "db", "pr_context"):
            del sys.modules[mod]

    return {"vault": vault, "repo": repo, "data": data}


@pytest.fixture
def initialised_vault(env):
    """Bootstrap docs/memory/<repo>/ and return its path."""
    # init-memory.py has a dash in the filename, so we invoke it as a script
    # rather than trying to import it.
    subprocess.run(
        [sys.executable, str(PLUGIN_ROOT / "scripts" / "init-memory.py")],
        check=True, env=os.environ.copy(),
        capture_output=True,
    )
    return env["vault"] / "myrepo"

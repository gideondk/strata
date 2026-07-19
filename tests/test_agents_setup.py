"""Tests for `strata agents-setup` — the generic ~/.agents/skills installer.

The command symlinks the generated opencode/skills/strata-* layer into the
cross-agent skills directory (~/.agents/skills, scanned natively by Kimi
Code, OpenCode and Codex). Tests point it at a temp dir via
STRATA_AGENTS_SKILLS_DIR so the real home directory is never touched.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
STRATA_BIN = PLUGIN_ROOT / "bin" / "strata"
GENERATED = PLUGIN_ROOT / "opencode" / "skills"


def _run_agents_setup(target: Path, *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["STRATA_AGENTS_SKILLS_DIR"] = str(target)
    return subprocess.run(
        [str(STRATA_BIN), "agents-setup", *args],
        capture_output=True, text=True, env=env,
    )


def _expected_names() -> set[str]:
    return {p.name for p in GENERATED.glob("strata-*") if p.is_dir()}


def test_links_every_generated_skill(tmp_path):
    target = tmp_path / "skills"
    proc = _run_agents_setup(target)
    assert proc.returncode == 0, proc.stderr
    linked = {p.name for p in target.iterdir() if p.is_symlink()}
    assert linked == _expected_names()
    for p in target.iterdir():
        assert p.resolve().parent == GENERATED
    # The Kimi Code MCP snippet is printed for the read/recall side.
    assert "mcpServers" in proc.stdout
    assert ".kimi-code/mcp.json" in proc.stdout


def test_second_run_is_idempotent(tmp_path):
    target = tmp_path / "skills"
    assert _run_agents_setup(target).returncode == 0
    proc = _run_agents_setup(target)
    assert proc.returncode == 0, proc.stderr
    assert "0 linked" in proc.stderr
    assert f"{len(_expected_names())} already in place" in proc.stderr


def test_real_directory_is_never_clobbered(tmp_path):
    target = tmp_path / "skills"
    target.mkdir()
    squat = target / "strata-save"
    squat.mkdir()
    (squat / "mine.md").write_text("not strata's\n")
    proc = _run_agents_setup(target)
    assert proc.returncode == 1
    assert "SKIP" in proc.stderr
    assert (squat / "mine.md").read_text() == "not strata's\n"


def test_stale_symlink_is_repointed(tmp_path):
    target = tmp_path / "skills"
    target.mkdir()
    stale = target / "strata-save"
    stale.symlink_to(tmp_path / "nowhere")
    proc = _run_agents_setup(target)
    assert proc.returncode == 0, proc.stderr
    assert stale.resolve().parent == GENERATED


def test_uninstall_removes_only_our_links(tmp_path):
    target = tmp_path / "skills"
    assert _run_agents_setup(target).returncode == 0
    foreign = target / "strata-foreign"
    foreign.symlink_to(tmp_path)  # not into our skills dir — must survive
    proc = _run_agents_setup(target, "--uninstall")
    assert proc.returncode == 0, proc.stderr
    remaining = list(target.iterdir())
    assert [p.name for p in remaining] == ["strata-foreign"]

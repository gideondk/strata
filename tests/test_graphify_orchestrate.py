"""Tests for /strata:graphify orchestration — uses a stubbed `graphify` binary."""
from __future__ import annotations

import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORCH = HERE.parent / "scripts" / "graphify-orchestrate.py"


def _run(*args, env=None):
    return subprocess.run(
        [sys.executable, str(ORCH), *args],
        capture_output=True, text=True, check=False,
        env=env,
    )


def _install_graphify_stub(tmp_path, monkeypatch, exit_code: int = 0):
    """Drop a fake `graphify` binary on PATH that echoes its argv and exits."""
    stub_dir = tmp_path / "graphify-stub-bin"
    stub_dir.mkdir()
    gh = stub_dir / "graphify"
    gh.write_text(textwrap.dedent(f"""\
        #!/usr/bin/env bash
        echo "STUB graphify called with: $*"
        exit {exit_code}
        """))
    gh.chmod(gh.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{stub_dir}:{os.environ['PATH']}")


def test_orchestrate_missing_graphify_exits_2(env, monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")
    r = _run(env=os.environ.copy())
    assert r.returncode == 2
    assert "graphify not installed" in r.stderr


def test_orchestrate_default_uses_update_subcommand(
        env, monkeypatch, tmp_path):
    """Default: `graphify update .` — AST-only, no LLM API key needed.

    Current Graphify versions made the bare `graphify .` form require
    an LLM. The `update` subcommand is the canonical no-LLM path.
    """
    _install_graphify_stub(tmp_path, monkeypatch)
    r = _run(env=os.environ.copy())
    assert r.returncode == 0
    assert "STUB graphify called with: update ." in r.stdout
    assert "--obsidian" not in r.stdout
    assert "--mode" not in r.stdout


def test_orchestrate_obsidian_does_not_pass_flag_to_graphify(
        env, monkeypatch, tmp_path):
    """--obsidian must NOT propagate to graphify (it requires an LLM key
    there). We do the obsidian export ourselves from graph.json."""
    _install_graphify_stub(tmp_path, monkeypatch)
    # Have the stub write a minimal graph.json so our local export runs
    graph_dir = env["repo"] / "graphify-out"
    graph_dir.mkdir(parents=True, exist_ok=True)
    import json as _json
    (graph_dir / "graph.json").write_text(_json.dumps({
        "nodes": [
            {"id": "A", "label": "A", "type": "function"},
            {"id": "B", "label": "B", "type": "class"},
        ],
        "edges": [{"src": "A", "dst": "B", "relation": "calls"}],
    }))

    r = _run("--obsidian", env=os.environ.copy())
    assert r.returncode == 0, r.stderr
    # graphify CLI args should NOT include --obsidian (that's our path now)
    stub_line = [
        line for line in r.stdout.splitlines()
        if line.startswith("STUB graphify called with:")
    ]
    assert stub_line, r.stdout
    assert "--obsidian" not in stub_line[0]
    # Per-node notes should land in the vault's graphify/ dir
    obsidian_dir = env["vault"] / "myrepo" / "graphify"
    assert obsidian_dir.exists()
    md_files = list(obsidian_dir.glob("*.md"))
    assert len(md_files) == 2
    # Verify wikilink connection wrote out
    a_note = next(p for p in md_files if p.name == "A.md")
    assert "[[B]]" in a_note.read_text()
    assert "`calls`" in a_note.read_text()


def test_orchestrate_rebuild_passes_force_flag(env, monkeypatch, tmp_path):
    """--rebuild becomes --force on the update subcommand (current Graphify)."""
    _install_graphify_stub(tmp_path, monkeypatch)
    r = _run("--rebuild", env=os.environ.copy())
    assert r.returncode == 0
    assert "update . --force" in r.stdout


def test_orchestrate_deep_passes_mode_flag(env, monkeypatch, tmp_path):
    """--deep falls back to the bare `graphify .` form (LLM required)
    plus --mode deep. Does NOT use the `update` subcommand."""
    _install_graphify_stub(tmp_path, monkeypatch)
    r = _run("--deep", env=os.environ.copy())
    assert r.returncode == 0
    assert "--mode deep" in r.stdout
    # --deep uses the bare form, not `update`
    assert "update" not in r.stdout
    # We removed graphify's --obsidian path; our local export is opt-in
    assert "--obsidian" not in r.stdout
    obsidian_dir = env["vault"] / "myrepo" / "graphify"
    assert not obsidian_dir.exists()


def test_orchestrate_status_uses_code_graph(env, tmp_path):
    """--status doesn't invoke graphify — it queries graph.json directly."""
    # With no graph.json present, status returns 0 with "no graph.json" msg
    r = _run("--status", env=os.environ.copy())
    assert r.returncode == 0
    assert "no graph.json" in r.stdout or "graph.json" in r.stdout

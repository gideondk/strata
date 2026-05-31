"""Tests for /strata:doctor — the post-install health-check surface."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DOCTOR = HERE.parent / "scripts" / "doctor.py"


def _run() -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(DOCTOR)],
        capture_output=True, text=True, check=False, env=os.environ.copy(),
    )


def test_doctor_healthy_vault_exits_zero(initialised_vault):
    r = _run()
    assert r.returncode == 0, r.stdout + r.stderr
    out = r.stdout
    # Every required check label is present and the verdict is healthy.
    for label in ("runtime packages", "vault directory", "repo namespace",
                  "search index", "MCP server"):
        assert label in out
    assert "healthy" in out
    assert "✓ healthy" in out


def test_doctor_uninitialised_namespace_fails(env):
    """Vault dir exists (fixture made it) but the repo namespace isn't created
    yet — doctor must flag it and exit non-zero with the /strata:init hint."""
    r = _run()
    assert r.returncode == 1, r.stdout
    assert "repo namespace" in r.stdout
    assert "/strata:init" in r.stdout
    assert "not healthy" in r.stdout


def test_doctor_missing_vault_dir_fails(env, monkeypatch, tmp_path):
    """Point vault_path at a path that doesn't exist — required failure."""
    monkeypatch.setenv("STRATA_VAULT_PATH", str(tmp_path / "nope"))
    r = _run()
    assert r.returncode == 1, r.stdout
    assert "vault directory" in r.stdout
    assert "does not exist" in r.stdout

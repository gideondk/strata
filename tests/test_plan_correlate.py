"""Tests for plan_correlate — git-log + graph correlation of plan claims."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "plan_correlate.py"


def _run(*args, env=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, check=False,
        env=env,
    )


def _git(repo: Path, *args, **kw):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True, **kw)


def test_error_on_nonexistent_subdir(env):
    r = _run("nonexistent", env=os.environ.copy())
    assert r.returncode == 1
    assert "not a directory" in r.stdout or "not a directory" in r.stderr


def test_correlate_finds_existing_path_with_commits(env):
    pd = env["repo"]
    # Create a plan that mentions a file, then create + commit the file
    (pd / ".planning" / "x").mkdir(parents=True)
    (pd / ".planning" / "x" / "PLAN.md").write_text(
        "We will implement `services/orders/OrderAggregate.cs` and "
        "`services/orders/Router.cs`.\n"
    )
    (pd / "services").mkdir()
    (pd / "services" / "orders").mkdir()
    (pd / "services" / "orders" / "OrderAggregate.cs").write_text(
        "public class OrderAggregate {}\n"
    )
    _git(pd, "add", ".")
    _git(pd, "commit", "-qm", "feat: scaffold orders")

    r = _run(".planning/x", "--json", env=os.environ.copy())
    assert r.returncode == 0
    data = json.loads(r.stdout)
    paths = data["path_claims"]
    assert "services/orders/OrderAggregate.cs" in paths
    info = paths["services/orders/OrderAggregate.cs"]
    assert info["exists_now"] is True
    assert info["commit_count"] >= 1
    assert info["first_commit"]["subject"].startswith("feat: scaffold")

    # The other path was mentioned but never created → no evidence
    other = paths.get("services/orders/Router.cs")
    assert other is not None
    assert other["exists_now"] is False
    assert other["commit_count"] == 0


def test_completion_estimate_reflects_evidence(env):
    pd = env["repo"]
    (pd / ".planning" / "y").mkdir(parents=True)
    (pd / ".planning" / "y" / "PLAN.md").write_text(
        "Touch `src/a.py` and `src/b.py` and `src/c.py`.\n"
    )
    (pd / "src").mkdir()
    # Build 2 of the 3 mentioned files
    (pd / "src" / "a.py").write_text("# a\n")
    (pd / "src" / "b.py").write_text("# b\n")
    _git(pd, "add", ".")
    _git(pd, "commit", "-qm", "two of three")

    r = _run(".planning/y", "--json", env=os.environ.copy())
    assert r.returncode == 0
    data = json.loads(r.stdout)
    s = data["summary"]
    assert s["paths_mentioned"] == 3
    assert s["paths_existing_now"] == 2
    # No symbols mentioned in PLAN
    assert s["symbols_mentioned"] == 0
    assert s["completion_estimate"] == round(2 / 3, 2)


def test_markdown_verdict_high_evidence(env):
    pd = env["repo"]
    (pd / ".planning" / "h").mkdir(parents=True)
    (pd / ".planning" / "h" / "PLAN.md").write_text(
        "Build `src/x.py`.\n"
    )
    (pd / "src").mkdir()
    (pd / "src" / "x.py").write_text("x\n")
    _git(pd, "add", ".")
    _git(pd, "commit", "-qm", "x")

    r = _run(".planning/h", env=os.environ.copy())
    assert r.returncode == 0
    # All paths resolve; verdict should be high evidence
    assert "high evidence" in r.stdout.lower() or "100%" in r.stdout


def test_markdown_verdict_low_evidence(env):
    pd = env["repo"]
    (pd / ".planning" / "l").mkdir(parents=True)
    (pd / ".planning" / "l" / "PLAN.md").write_text(
        "We considered `src/never.py` and `src/built.py`.\n"
    )
    # No files created; commit only the plan
    _git(pd, "add", ".")
    _git(pd, "commit", "-qm", "plan only")

    r = _run(".planning/l", env=os.environ.copy())
    assert r.returncode == 0
    out = r.stdout.lower()
    assert "low evidence" in out or "lesson" in out


def test_url_paths_filtered_out(env):
    """plan_correlate should NOT cross-check URL hostnames as repo
    paths — they'd always come back missing and pollute completion %."""
    pd = env["repo"]
    (pd / ".planning" / "u").mkdir(parents=True)
    (pd / ".planning" / "u" / "PLAN.md").write_text(
        "Implement `src/real.py`. See https://github.com/foo/bar.py for ref.\n"
    )
    (pd / "src").mkdir()
    (pd / "src" / "real.py").write_text("\n")
    _git(pd, "add", ".")
    _git(pd, "commit", "-qm", "real")

    r = _run(".planning/u", "--json", env=os.environ.copy())
    data = json.loads(r.stdout)
    assert "src/real.py" in data["path_claims"]
    # URL component must NOT appear as a tracked claim
    bad = [p for p in data["path_claims"] if "github.com" in p]
    assert not bad, f"URL leaked as path claim: {bad}"

"""Tests for commit_graph — churn, hotspots, ADR ↔ commit linkage."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))


def _git(repo: Path, *args, **kw):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True, **kw)


def _reload():
    for mod in ("commit_graph", "lib"):
        if mod in sys.modules:
            del sys.modules[mod]


def test_churn_returns_zero_when_path_never_committed(env):
    _reload()
    import commit_graph
    assert commit_graph.churn("nonexistent.py", days=90) == 0


def test_churn_counts_recent_commits(env):
    pd = env["repo"]
    (pd / "src.py").write_text("v1\n")
    _git(pd, "add", "src.py")
    _git(pd, "commit", "-qm", "feat: v1")
    (pd / "src.py").write_text("v2\n")
    _git(pd, "add", "src.py")
    _git(pd, "commit", "-qm", "fix: v2")
    (pd / "src.py").write_text("v3\n")
    _git(pd, "add", "src.py")
    _git(pd, "commit", "-qm", "fix: v3")

    _reload()
    import commit_graph
    assert commit_graph.churn("src.py", days=90) == 3


def test_hotspots_ranks_by_commit_count(env):
    pd = env["repo"]
    # File A: 4 commits. File B: 2 commits. File C: 1 commit.
    for i in range(4):
        (pd / "a.py").write_text(f"v{i}\n")
        _git(pd, "add", "a.py")
        _git(pd, "commit", "-qm", f"a v{i}")
    for i in range(2):
        (pd / "b.py").write_text(f"v{i}\n")
        _git(pd, "add", "b.py")
        _git(pd, "commit", "-qm", f"b v{i}")
    (pd / "c.py").write_text("\n")
    _git(pd, "add", "c.py")
    _git(pd, "commit", "-qm", "c v0")

    _reload()
    import commit_graph
    hot = commit_graph.hotspots(days=90, top=5)
    paths = [h["path"] for h in hot]
    assert paths[0] == "a.py"
    assert paths[1] == "b.py"
    a_count = next(h["commits"] for h in hot if h["path"] == "a.py")
    assert a_count == 4


def test_adr_implementations_finds_referenced_decisions(env):
    pd = env["repo"]
    (pd / "src.py").write_text("\n")
    _git(pd, "add", "src.py")
    _git(pd, "commit", "-qm",
         "feat: implement token rotation per decisions/2026-05-24-use-jwt")
    (pd / "src.py").write_text("v2\n")
    _git(pd, "add", "src.py")
    _git(pd, "commit", "-qm",
         "fix: address review on decisions/2026-05-24-use-jwt.md")
    (pd / "other.py").write_text("\n")
    _git(pd, "add", "other.py")
    _git(pd, "commit", "-qm", "chore: unrelated commit")

    _reload()
    import commit_graph
    links = commit_graph.adr_implementations(
        ["2026-05-24-use-jwt"]
    )
    assert "2026-05-24-use-jwt" in links
    assert len(links["2026-05-24-use-jwt"]) == 2


def test_adr_implementations_handles_full_path_slugs(env):
    pd = env["repo"]
    (pd / "src.py").write_text("\n")
    _git(pd, "add", "src.py")
    _git(pd, "commit", "-qm",
         "feat: per decisions/2026-05-24-foo")

    _reload()
    import commit_graph
    # Pass full vault-relative path — script must normalise to slug
    links = commit_graph.adr_implementations(
        ["decisions/2026-05-24-foo.md"]
    )
    assert "2026-05-24-foo" in links


def test_adr_implementations_unmentioned_slug_omitted(env):
    pd = env["repo"]
    (pd / "src.py").write_text("\n")
    _git(pd, "add", "src.py")
    _git(pd, "commit", "-qm", "chore: nothing to do with ADRs")

    _reload()
    import commit_graph
    links = commit_graph.adr_implementations(["2026-05-24-not-mentioned"])
    assert links == {}


def test_commits_since_path_was_written(env):
    pd = env["repo"]
    (pd / "src.py").write_text("v1\n")
    _git(pd, "add", "src.py")
    _git(pd, "commit", "-qm", "v1")
    (pd / "src.py").write_text("v2\n")
    _git(pd, "add", "src.py")
    _git(pd, "commit", "-qm", "v2")

    _reload()
    import commit_graph
    # All commits are in our future-since-the-epoch window
    n = commit_graph.commits_since_path_was_written(
        "src.py", "2020-01-01T00:00:00")
    assert n == 2

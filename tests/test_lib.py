"""Tests for scripts/lib.py — branch detection, repo namespace, slugging."""
from __future__ import annotations


def test_repo_name_from_remote(env):
    import lib
    # Remote is https://example.invalid/test/myrepo.git → "myrepo"
    assert lib.repo_name() == "myrepo"


def test_repo_name_env_override(env, monkeypatch):
    import lib
    monkeypatch.setenv("STRATA_REPO_NAME", "custom-name")
    assert lib.repo_name() == "custom-name"


def test_repo_name_slugifies(env, monkeypatch):
    import lib
    monkeypatch.setenv("STRATA_REPO_NAME", "weird name/with slashes")
    assert "/" not in lib.repo_name()
    assert " " not in lib.repo_name()


def test_branch_slug():
    import lib
    assert lib.branch_slug("feat/user-auth") == "feat-user-auth"
    assert lib.branch_slug("main") == "main"
    assert lib.branch_slug("release/v1.2.3") == "release-v1.2.3"


def test_current_branch(env):
    import lib
    assert lib.current_branch() == "feat/test-branch"


def test_memory_dir_under_vault(env):
    import lib
    mem = lib.memory_dir()
    assert mem == env["vault"] / "myrepo"


def test_safe_slug_caps_length():
    import lib
    long = "x" * 200
    assert len(lib.safe_slug(long)) <= 48


def test_safe_slug_cuts_on_word_boundary():
    """Regression: bootstrap produced ADR filenames like `legacy.vi.md`,
    `aggrega.md`, `subdoma.md` because the truncator did a hard char cut
    mid-token. Now we slice at the rightmost `-` or `.` before the limit
    (when past halfway), so the visible slug stays readable."""
    import lib
    # Real titles observed in the wild
    cases = [
        ("Extract Visit aggregate into dedicated Legacy.VisitsAcl service",
         ["legacy.vi", "legacy.v"]),
        ("Implement ticket domain as event-sourced aggregate with four-wave",
         ["aggrega"]),
        ("Split monolithic Scheduling.Api into per-subdomain Api projects",
         ["subdoma"]),
    ]
    for title, bad_tails in cases:
        slug = lib.safe_slug(title)
        for bad in bad_tails:
            assert not slug.endswith(bad), (
                f"slug {slug!r} ends with mid-token tail {bad!r}"
            )
        # And the slug must not end on a separator
        assert not slug.endswith(("-", "."))


def test_safe_slug_keeps_short_titles_intact():
    import lib
    assert lib.safe_slug("Short title") == "short-title"
    assert lib.safe_slug("") == "note"


def test_project_dir_env_override(env, monkeypatch, tmp_path):
    """STRATA_PROJECT_DIR overrides CLAUDE_PROJECT_DIR for namespace pinning."""
    import lib
    other = tmp_path / "other-project"
    other.mkdir()
    monkeypatch.setenv("STRATA_PROJECT_DIR", str(other))
    assert lib.project_dir() == other


def test_project_dir_falls_back_to_claude_project_dir(env, monkeypatch):
    """When STRATA_PROJECT_DIR is unset, CLAUDE_PROJECT_DIR still wins."""
    import lib
    monkeypatch.delenv("STRATA_PROJECT_DIR", raising=False)
    # CLAUDE_PROJECT_DIR set by the env fixture
    assert lib.project_dir() == env["repo"]

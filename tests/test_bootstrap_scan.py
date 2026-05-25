"""Tests for bootstrap-scan — generic markdown discovery + idempotency."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCAN = HERE.parent / "scripts" / "bootstrap-scan.py"


def _run(*args, env=None):
    return subprocess.run(
        [sys.executable, str(SCAN), *args],
        capture_output=True, text=True, check=False,
        env=env,
    )


def _write(p: Path, content: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def _cleanup_conftest_readme(env):
    """conftest.py creates README.md in the test repo; remove it so each
    test starts from a clean slate."""
    p = env["repo"] / "README.md"
    if p.exists():
        p.unlink()


def test_no_markdown_means_no_candidates(initialised_vault, env):
    _cleanup_conftest_readme(env)
    r = _run(env=os.environ.copy())
    assert r.returncode == 0
    assert "No markdown" in r.stdout or "0 unprocessed" in r.stdout


def test_finds_root_files(initialised_vault, env):
    _cleanup_conftest_readme(env)
    pd = env["repo"]
    _write(pd / "CLAUDE.md", "# x\n")
    _write(pd / "ARCHITECTURE.md", "# y\n")
    r = _run(env=os.environ.copy())
    assert r.returncode == 0
    assert "(root)" in r.stdout
    assert "CLAUDE.md" in r.stdout
    assert "ARCHITECTURE.md" in r.stdout


def test_finds_arbitrary_directory(initialised_vault, env):
    """Generic — works for any directory name, not just docs/.planning/etc."""
    _cleanup_conftest_readme(env)
    pd = env["repo"]
    _write(pd / "knowledge" / "tenant.md", "# x\n")
    _write(pd / "knowledge" / "events.md", "# y\n")
    _write(pd / "rfcs" / "001-cdc.md", "# z\n")
    r = _run(env=os.environ.copy())
    assert r.returncode == 0
    assert "knowledge/" in r.stdout
    assert "rfcs/" in r.stdout


def test_skips_noise_directories(initialised_vault, env):
    _cleanup_conftest_readme(env)
    pd = env["repo"]
    _write(pd / "node_modules" / "pkg" / "README.md", "noise\n")
    _write(pd / ".venv" / "lib" / "x.md", "noise\n")
    _write(pd / "graphify-out" / "wiki" / "node.md", "noise\n")
    _write(pd / "real-doc.md", "real\n")
    r = _run(env=os.environ.copy())
    assert "node_modules" not in r.stdout
    assert ".venv" not in r.stdout
    assert "graphify-out" not in r.stdout
    assert "real-doc.md" in r.stdout


def test_skips_oversize_files(initialised_vault, env):
    _cleanup_conftest_readme(env)
    pd = env["repo"]
    _write(pd / "huge.md", "x" * 500_000)  # 500 KB
    _write(pd / "small.md", "ok\n")
    r = _run(env=os.environ.copy())
    # Default cap is 200_000 — huge.md should be filtered
    assert "huge.md" not in r.stdout
    assert "small.md" in r.stdout


def test_json_output_includes_totals(initialised_vault, env):
    _cleanup_conftest_readme(env)
    pd = env["repo"]
    _write(pd / "a.md", "x\n")
    _write(pd / "sub" / "b.md", "y\n")
    r = _run("--json", env=os.environ.copy())
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert data["total_files"] == 2
    assert data["graphify_built"] is False


def test_mark_persists_to_state_file(initialised_vault, env):
    _cleanup_conftest_readme(env)
    pd = env["repo"]
    mem = initialised_vault
    _write(pd / "CLAUDE.md", "# x\n")
    r = _run("--mark", "CLAUDE.md", env=os.environ.copy())
    assert r.returncode == 0
    state_file = mem / ".bootstrap-state.json"
    assert state_file.exists()
    state = json.loads(state_file.read_text())
    assert "CLAUDE.md" in state["processed_files"]
    assert "sha256" in state["processed_files"]["CLAUDE.md"]


def test_unprocessed_hides_marked_files(initialised_vault, env):
    _cleanup_conftest_readme(env)
    pd = env["repo"]
    _write(pd / "CLAUDE.md", "# x\n")
    _write(pd / "OTHER.md", "# y\n")
    _run("--mark", "CLAUDE.md", env=os.environ.copy())
    r = _run("--unprocessed", env=os.environ.copy())
    assert "CLAUDE.md" not in r.stdout
    assert "OTHER.md" in r.stdout


def test_modified_file_resurfaces(initialised_vault, env):
    _cleanup_conftest_readme(env)
    pd = env["repo"]
    _write(pd / "CLAUDE.md", "# v1\n")
    _run("--mark", "CLAUDE.md", env=os.environ.copy())
    _write(pd / "CLAUDE.md", "# v2 — changed\n")
    r = _run("--unprocessed", env=os.environ.copy())
    assert "CLAUDE.md" in r.stdout


def test_mark_nonexistent_file_errors(initialised_vault, env):
    r = _run("--mark", "does/not/exist.md", env=os.environ.copy())
    assert r.returncode == 2


# ---- Verify precision (regression: greedy alternation + URL filter) ----


def test_extension_alternation_longest_wins():
    """`async-and-disposal.md` must match `.md` not `.m`."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "bootstrap_scan",
        Path(__file__).resolve().parent.parent / "scripts" / "bootstrap-scan.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    claims = mod._extract_path_claims("See `async-and-disposal.md` for more.")
    assert "async-and-disposal.md" in claims
    # Not the truncated form
    assert "async-and-disposal.m" not in claims


def test_extension_word_boundary_rejects_domain_truncation():
    """`chriskiehl.com` must NOT be captured as `chriskiehl.c`."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "bootstrap_scan",
        Path(__file__).resolve().parent.parent / "scripts" / "bootstrap-scan.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    claims = mod._extract_path_claims("Visit chriskiehl.com or developers.openai.com.")
    assert "chriskiehl.c" not in claims
    assert "chriskiehl.com" not in claims  # not a code extension


def test_url_filter_strips_hostnames():
    """Full URL-like paths should be filtered, not cross-checked as files."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "bootstrap_scan",
        Path(__file__).resolve().parent.parent / "scripts" / "bootstrap-scan.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    claims = mod._extract_path_claims(
        "See https://github.com/foo/bar.py for src, "
        "and getakka.net/articles/streams/introduction.h."
    )
    assert "github.com/foo/bar.py" not in claims
    assert "getakka.net/articles/streams/introduction.h" not in claims


def test_json_extension_wins_over_js():
    """`appsettings.json` must match `.json` not `.js`."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "bootstrap_scan",
        Path(__file__).resolve().parent.parent / "scripts" / "bootstrap-scan.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    claims = mod._extract_path_claims("Check `appsettings.json` first.")
    assert "appsettings.json" in claims
    assert "appsettings.js" not in claims


def test_scan_respects_gitignore(initialised_vault, env):
    """Files in .gitignored paths must NOT show up as bootstrap candidates."""
    _cleanup_conftest_readme(env)
    pd = env["repo"]
    _write(pd / "tracked.md", "# tracked\n")
    _write(pd / ".legacy" / "old.md", "# legacy doc\n")
    _write(pd / "build" / "generated.md", "# gen\n")  # already in SKIP_PATTERNS
    _write(pd / ".gitignore", ".legacy/\n")
    # Commit the gitignore + tracked file so they're "tracked" from git's POV
    import subprocess as sp
    sp.run(["git", "-C", str(pd), "add", ".gitignore", "tracked.md"], check=True)
    sp.run(["git", "-C", str(pd), "commit", "-qm", "ignore legacy"], check=True)

    r = _run(env=os.environ.copy())
    assert r.returncode == 0
    assert "tracked.md" in r.stdout
    assert ".legacy/old.md" not in r.stdout
    assert "build/generated.md" not in r.stdout  # SKIP_PATTERNS also fires


def test_scan_skips_meta_config_dirs(initialised_vault, env):
    """`.claude/`, `.github/`, editor configs etc. are plugin/tool config,
    not project knowledge — should never appear as bootstrap candidates."""
    _cleanup_conftest_readme(env)
    pd = env["repo"]
    _write(pd / "real-doc.md", "# project knowledge\n")
    _write(pd / ".claude" / "skills" / "foo" / "SKILL.md", "# skill\n")
    _write(pd / ".claude" / "settings.json.md", "# config\n")
    _write(pd / ".github" / "ISSUE_TEMPLATE" / "bug.md", "# bug template\n")
    _write(pd / ".vscode" / "README.md", "# vscode\n")
    _write(pd / ".idea" / "notes.md", "# jetbrains\n")
    _write(pd / ".zed" / "notes.md", "# zed\n")
    _write(pd / ".agents" / "main.md", "# agent\n")
    r = _run(env=os.environ.copy())
    assert r.returncode == 0
    assert "real-doc.md" in r.stdout
    for noise in (".claude/", ".github/", ".vscode/", ".idea/", ".zed/", ".agents/"):
        assert noise not in r.stdout, f"{noise} leaked into scan output"


def test_scan_skips_root_ai_tool_config_files(initialised_vault, env):
    """Root-level dotfile AI-tool configs (.impeccable.md, .cursor.md etc.)
    are skill/tool state, not project knowledge — should be skipped."""
    _cleanup_conftest_readme(env)
    pd = env["repo"]
    _write(pd / "real-doc.md", "# project knowledge\n")
    _write(pd / ".impeccable.md", "# impeccable config\n")
    _write(pd / ".cursor.md", "# cursor config\n")
    _write(pd / ".aiderrc.md", "# aider config\n")
    _write(pd / ".copilot.md", "# copilot config\n")
    _write(pd / ".windsurf.md", "# windsurf config\n")
    r = _run(env=os.environ.copy())
    assert r.returncode == 0
    assert "real-doc.md" in r.stdout
    for noise in (".impeccable.md", ".cursor.md", ".aiderrc.md",
                  ".copilot.md", ".windsurf.md"):
        assert noise not in r.stdout, f"{noise} leaked into scan"


def test_scan_includes_untracked_but_not_ignored(initialised_vault, env):
    """Files that exist on disk but aren't yet committed (and aren't
    gitignored) should still appear as candidates."""
    _cleanup_conftest_readme(env)
    pd = env["repo"]
    _write(pd / "fresh-untracked.md", "# new\n")
    # Don't commit — just leave it untracked
    r = _run(env=os.environ.copy())
    assert r.returncode == 0
    assert "fresh-untracked.md" in r.stdout


def test_strataignore_excludes_listed_files(initialised_vault, env):
    """A `.strataignore` at repo root (gitignore syntax) excludes
    matching files from the scan."""
    _cleanup_conftest_readme(env)
    pd = env["repo"]
    _write(pd / "keep.md", "# keep\n")
    _write(pd / "docs" / "legacy" / "old.md", "# old\n")
    _write(pd / "RUNBOOK-old.md", "# runbook\n")
    _write(pd / ".strataignore",
           "docs/legacy/\nRUNBOOK-old.md\n")
    r = _run(env=os.environ.copy())
    assert r.returncode == 0
    assert "keep.md" in r.stdout
    assert "RUNBOOK-old.md" not in r.stdout
    assert "docs/legacy/old.md" not in r.stdout


def test_dot_ignore_file_is_honoured(initialised_vault, env):
    """`.ignore` (ripgrep/fd cross-tool convention) is also honoured."""
    _cleanup_conftest_readme(env)
    pd = env["repo"]
    _write(pd / "keep.md", "# keep\n")
    _write(pd / "vendor-doc.md", "# vendor\n")
    _write(pd / ".ignore", "vendor-doc.md\n")
    r = _run(env=os.environ.copy())
    assert r.returncode == 0
    assert "keep.md" in r.stdout
    assert "vendor-doc.md" not in r.stdout


def test_strataignore_can_negate_a_default(initialised_vault, env):
    """`!pattern` in `.strataignore` re-includes a default-excluded
    file. Demonstrates the layered-precedence design."""
    _cleanup_conftest_readme(env)
    pd = env["repo"]
    # .github/ is excluded by default; the negation should re-include
    # a specific file under it.
    _write(pd / "regular.md", "# normal\n")
    _write(pd / ".github" / "CONTRIBUTING.md", "# contributing\n")
    _write(pd / ".github" / "ISSUE_TEMPLATE" / "bug.md", "# bug\n")
    _write(pd / ".strataignore", "!.github/CONTRIBUTING.md\n")
    r = _run(env=os.environ.copy())
    assert r.returncode == 0
    assert "regular.md" in r.stdout
    assert ".github/CONTRIBUTING.md" in r.stdout
    # The other .github/ file stays excluded
    assert "bug.md" not in r.stdout


def test_strataignore_wins_over_dot_ignore(initialised_vault, env):
    """When both files match, `.strataignore` takes precedence
    (loaded after `.ignore`, so its patterns win)."""
    _cleanup_conftest_readme(env)
    pd = env["repo"]
    _write(pd / "shared.md", "# shared\n")
    _write(pd / ".ignore", "shared.md\n")
    _write(pd / ".strataignore", "!shared.md\n")
    r = _run(env=os.environ.copy())
    assert r.returncode == 0
    assert "shared.md" in r.stdout


def test_json_output_includes_dispatch_groups_by_parent_dir(initialised_vault, env):
    """The JSON `dispatch_groups` field keys by IMMEDIATE PARENT dir so
    sibling files (PLAN/CONTEXT/SPEC in the same initiative folder)
    route to one worker. This is what prevents the duplicate-ADR
    problem from earlier bootstrap passes."""
    _cleanup_conftest_readme(env)
    pd = env["repo"]
    _write(pd / ".planning" / "auth-rewrite" / "PLAN.md", "# plan\n")
    _write(pd / ".planning" / "auth-rewrite" / "SPEC.md", "# spec\n")
    _write(pd / ".planning" / "auth-rewrite" / "CONTEXT.md", "# ctx\n")
    _write(pd / ".planning" / "scheduling" / "PLAN.md", "# sched\n")
    _write(pd / "ROOT.md", "# root\n")
    r = _run("--json", env=os.environ.copy())
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert "dispatch_groups" in data
    dg = data["dispatch_groups"]
    # Same-parent siblings group together
    auth_group = dg.get(".planning/auth-rewrite")
    assert auth_group is not None
    auth_paths = {e["path"] for e in auth_group}
    assert auth_paths == {
        ".planning/auth-rewrite/PLAN.md",
        ".planning/auth-rewrite/SPEC.md",
        ".planning/auth-rewrite/CONTEXT.md",
    }
    # Different initiative is its own group
    assert ".planning/scheduling" in dg
    assert len(dg[".planning/scheduling"]) == 1
    # Root file lands in `(root)` bucket
    assert "(root)" in dg
    assert dg["(root)"][0]["path"] == "ROOT.md"


def test_real_file_claim_still_matches():
    """Sanity — real file refs in docs still get extracted."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "bootstrap_scan",
        Path(__file__).resolve().parent.parent / "scripts" / "bootstrap-scan.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    claims = mod._extract_path_claims(
        "See `services/medication/MedicationService.cs` and ./scripts/deploy.sh"
    )
    assert "services/medication/MedicationService.cs" in claims
    assert "scripts/deploy.sh" in claims


# ---------- --max-group-size dense-folder subdivision ----------

def test_max_group_size_splits_undated_files(initialised_vault, env):
    _cleanup_conftest_readme(env)
    pd = env["repo"]
    for i in range(8):
        _write(pd / "plans" / f"plan-{i}.md", f"# plan {i}\n")
    r = _run("--json", "--max-group-size", "3", env=os.environ.copy())
    assert r.returncode == 0
    data = json.loads(r.stdout)
    groups = data["dispatch_groups"]
    # plans/ has 8 files, split into chunks of 3 → 3, 3, 2
    plans_groups = {k: v for k, v in groups.items() if k.startswith("plans")}
    assert len(plans_groups) == 3
    assert max(len(v) for v in plans_groups.values()) <= 3
    assert sum(len(v) for v in plans_groups.values()) == 8


def test_max_group_size_buckets_by_date_prefix(initialised_vault, env):
    _cleanup_conftest_readme(env)
    pd = env["repo"]
    for i in range(5):
        _write(pd / "specs" / f"2026-04-{i:02}-thing.md", f"# april thing {i}\n")
    for i in range(5):
        _write(pd / "specs" / f"2026-05-{i:02}-thing.md", f"# may thing {i}\n")
    r = _run("--json", "--max-group-size", "8", env=os.environ.copy())
    assert r.returncode == 0
    data = json.loads(r.stdout)
    groups = data["dispatch_groups"]
    # 10 dated files should split by month, not by N-sized chunks
    month_keys = [k for k in groups if k.startswith("specs@2026-")]
    assert any("2026-04" in k for k in month_keys)
    assert any("2026-05" in k for k in month_keys)


def test_max_group_size_below_threshold_unchanged(initialised_vault, env):
    _cleanup_conftest_readme(env)
    pd = env["repo"]
    for i in range(3):
        _write(pd / "tiny" / f"plan-{i}.md", f"# {i}\n")
    r = _run("--json", "--max-group-size", "10", env=os.environ.copy())
    data = json.loads(r.stdout)
    assert "tiny" in data["dispatch_groups"]
    assert len(data["dispatch_groups"]["tiny"]) == 3
    # No sub-group keys for tiny/
    assert "tiny#1" not in data["dispatch_groups"]

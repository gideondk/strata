#!/usr/bin/env python3
"""Strata health check — the post-install "is it actually working?" surface.

Onboarding's hardest friction isn't the install command, it's the silent
uncertainty afterwards: did the venv build? is the vault wired up? will
semantic search work or silently fall back to FTS? `doctor` answers all of
that in one glanceable checklist with a fix hint on every failure.

Exit code: 0 when every REQUIRED check passes, 1 otherwise. Optional gaps
(e.g. semantic search) warn but never fail — the plugin still works without
them. No network, stdlib + the plugin's own modules only.
"""
from __future__ import annotations

import importlib.util
import sys

import lib_loader  # noqa: F401
from lib import (
    _vault_git,
    git_remote,
    is_git_repo,
    memory_dir,
    memory_display,
    plugin_root,
    repo_name,
    vault_is_git_repo,
    vault_root,
    vault_sync_mode,
)

# Mirror init-memory.py — keep the two lists in sync.
REQUIRED_PACKAGES: dict[str, str] = {
    "mcp": "mcp",
    "frontmatter": "python-frontmatter",
    "pathspec": "pathspec",
}
OPTIONAL_PACKAGES: dict[str, str] = {
    "fastembed": "fastembed",
    "numpy": "numpy",
    "tree_sitter_language_pack": "tree-sitter-language-pack",
}

OK, WARN, FAIL = "✓", "⚠", "✗"


class Report:
    """Collects check lines and tracks whether any REQUIRED check failed."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.failed = False

    def ok(self, label: str, detail: str = "") -> None:
        self.lines.append(f"  {OK} {label}" + (f" — {detail}" if detail else ""))

    def warn(self, label: str, hint: str) -> None:
        self.lines.append(f"  {WARN} {label} — {hint}")

    def fail(self, label: str, hint: str) -> None:
        self.failed = True
        self.lines.append(f"  {FAIL} {label} — {hint}")


def _check_packages(r: Report) -> None:
    missing_req = [pkg for mod, pkg in REQUIRED_PACKAGES.items()
                   if importlib.util.find_spec(mod) is None]
    missing_opt = [pkg for mod, pkg in OPTIONAL_PACKAGES.items()
                   if importlib.util.find_spec(mod) is None]
    if missing_req:
        r.fail("runtime packages",
                f"missing {', '.join(missing_req)} — run "
                "bin/run-python.sh -m pip install -r requirements.txt")
    else:
        opt_ok = len(OPTIONAL_PACKAGES) - len(missing_opt)
        r.ok("runtime packages",
             f"{len(REQUIRED_PACKAGES)} required, "
             f"{opt_ok}/{len(OPTIONAL_PACKAGES)} optional present")
    if missing_opt:
        # Surface the specific degradation per missing package rather
        # than a single generic message — the fallbacks differ.
        semantic_missing = [p for p in ("fastembed", "numpy")
                            if p in missing_opt]
        if semantic_missing:
            r.warn("optional packages",
                   f"{'/'.join(semantic_missing)} absent — semantic search "
                   "falls back to FTS5 (still works, just keyword-only)")
        if "tree-sitter-language-pack" in missing_opt:
            r.warn("optional packages",
                    "tree-sitter-language-pack absent — code-graph "
                    "features need Graphify installed (no coarse "
                    "fallback). Install it for out-of-the-box support")


def _check_vault(r: Report) -> bool:
    vroot = vault_root()
    if not vroot.exists():
        r.fail("vault directory",
                f"{vroot} does not exist — set vault_path in plugin config")
        return False
    # Probe writability without leaving litter behind.
    probe = vroot / ".strata-doctor-probe"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError:
        r.fail("vault directory", f"{vroot} is not writable")
        return False
    r.ok("vault directory", str(vroot))
    return True


def _check_namespace(r: Report) -> bool:
    mem = memory_dir()
    if not mem.exists():
        r.fail("repo namespace",
                f"{memory_display()} not initialised — run /strata:init")
        return False
    r.ok("repo namespace", f"{repo_name()} → {memory_display()}")
    return True


def _check_index(r: Report) -> None:
    try:
        import db
        db.reindex(force=False)
        summary = db.vault_summary()
    except Exception as e:  # surface, don't crash
        r.fail("search index", f"could not build/read index: {e}")
        return
    notes = summary.get("notes", 0)
    if notes == 0:
        r.warn("search index",
                "0 notes indexed yet — save a decision or note to populate it")
    else:
        kb = summary.get("bytes", 0) / 1024
        r.ok("search index", f"{notes} note(s) indexed ({kb:.0f} KB)")


def _check_semantic(r: Report) -> None:
    try:
        import embeddings
        if embeddings.available():
            r.ok("semantic search", "embeddings available (hybrid FTS+vector)")
        else:
            r.warn("semantic search",
                    "model not ready — recall uses FTS5 keyword search only")
    except Exception:
        r.warn("semantic search",
                "embeddings layer unavailable — recall uses FTS5 only")


def _check_mcp(r: Report) -> None:
    root = plugin_root()
    server = root / "mcp" / "server.py"
    config = root / "mcp" / ".mcp.json"
    if server.exists() and config.exists():
        r.ok("MCP server", "server.py + .mcp.json present")
    else:
        missing = [p.name for p in (server, config) if not p.exists()]
        r.fail("MCP server", f"missing {', '.join(missing)} in mcp/")


def _check_git(r: Report) -> None:
    if is_git_repo():
        r.ok("git repo", "branch/PR awareness active")
    else:
        r.warn("git repo",
                "not inside a git repo — branch/PR scoping is disabled")


def _check_vault_git(r: Report) -> None:
    """Git-backed vault mode. The classic misconfig — vault_sync=git without
    ever running `strata init --git` — makes every auto-commit a silent no-op,
    so that exact state FAILS rather than warns."""
    mode = vault_sync_mode()
    if mode != "git":
        if vault_is_git_repo():
            r.warn("vault git",
                   "vault is a git repo but vault_sync=manual — writes are "
                   "NOT auto-committed. Set vault_sync=git to enable.")
        return
    if not vault_is_git_repo():
        r.fail("vault git",
               "vault_sync=git but the vault is not a git repo — every "
               "auto-commit is silently skipped. Run `strata init --git`.")
        return
    # Repo existing isn't enough — with no committer identity every
    # auto-commit fails, which is exactly the silent state to surface here.
    ident = _vault_git("var", "GIT_COMMITTER_IDENT")
    if ident is None or ident.returncode != 0:
        r.fail("vault git",
               "git has no committer identity — auto-commits are failing. "
               "Fix: git -C <vault> config user.email you@example.com "
               "(and user.name).")
        return
    remote = git_remote()
    up = _vault_git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    upstream = (up.stdout.strip()
                if up is not None and up.returncode == 0 else "")
    if remote or upstream:
        r.ok("vault git", f"auto-commit on; /strata:sync ↔ {remote or upstream}")
    else:
        r.warn("vault git",
               "auto-commit on, but no remote/upstream configured — "
               "/strata:sync commits locally only. Set git_remote or add "
               "an origin to share.")


def main() -> int:
    r = Report()
    print(f"[strata] doctor — health check for {repo_name()}\n")

    _check_packages(r)
    vault_ok = _check_vault(r)
    if vault_ok:
        _check_namespace(r)
    _check_index(r)
    _check_semantic(r)
    _check_mcp(r)
    _check_git(r)
    _check_vault_git(r)

    print("\n".join(r.lines))
    if r.failed:
        print(f"\n[strata] {FAIL} not healthy — fix the items above, then "
              "re-run /strata:doctor")
        return 1
    print(f"\n[strata] {OK} healthy — ready to save, decide, and recall")
    return 0


if __name__ == "__main__":
    sys.exit(main())

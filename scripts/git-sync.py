#!/usr/bin/env python3
"""Sync the git-backed vault with its remote — the ONLY network path in Strata.

Everything else in this plugin is local: recall reads a local index, writes
commit locally (in `vault_sync=git` mode), and no hook or MCP tool ever opens a
socket. This script is the deliberate exception, and it only runs when the user
types `/strata:sync` (or `strata sync`) by hand — never from a hook, never
automatically. That's what keeps the "nothing in the runtime path touches the
network" guarantee true even with git storage turned on.

Flow: commit anything still pending → `git pull --rebase` → `git push`. On a
rebase conflict it stops and hands you the resolution steps rather than guessing.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import lib_loader  # noqa: F401
from lib import (
    _vault_git,
    git_remote,
    info,
    vault_is_git_repo,
    vault_root,
)


def _run(*args: str):
    """Run git in the vault, echoing the command so the network op is visible."""
    info(f"$ git {' '.join(args)}")
    return _vault_git(*args)


def _current_branch() -> str:
    r = _vault_git("rev-parse", "--abbrev-ref", "HEAD")
    return r.stdout.strip() if r and r.returncode == 0 else ""


def _has_upstream() -> bool:
    r = _vault_git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    return bool(r and r.returncode == 0 and r.stdout.strip())


def _is_dirty() -> bool:
    r = _vault_git("status", "--porcelain")
    return bool(r and r.returncode == 0 and r.stdout.strip())


def _rebase_in_progress() -> bool:
    # `.git/rebase-merge` or `rebase-apply` exists mid-rebase.
    for name in ("rebase-merge", "rebase-apply"):
        r = _vault_git("rev-parse", "--git-path", name)
        if r and r.returncode == 0:
            p = r.stdout.strip()
            # git-path is relative to the vault; resolve against it.
            if (vault_root() / p).exists() or Path(p).exists():
                return True
    return False


def _lint_outgoing(has_upstream: bool) -> list[str]:
    """Secret/PII findings for the notes about to be pushed.

    With an upstream, only the files that changed since it; on a first push
    everything tracked is new to the remote, so scan all markdown. Best-effort:
    a missing lint module or unreadable file never blocks sync by itself.
    """
    if has_upstream:
        r = _vault_git("diff", "--name-only", "@{u}..HEAD")
    else:
        r = _vault_git("ls-files", "*.md")
    if r is None or r.returncode != 0:
        return []
    paths = [p for p in r.stdout.splitlines() if p.strip().endswith(".md")]
    if not paths:
        return []
    try:
        import lint_check
    except Exception:
        return []
    root = vault_root()
    findings: list[str] = []
    for rel in paths:
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue  # deleted in this range — nothing to leak
        for preset in ("secrets", "pii"):
            try:
                for w in lint_check.warn_findings(text, preset):
                    findings.append(f"{rel}: {w}")
            except Exception:
                continue
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Pull + push the git-backed Strata vault (the only network "
                    "operation in Strata; user-invoked only).")
    ap.add_argument("--no-push", action="store_true",
                    help="Pull (and commit locally) but don't push.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Report what would happen; touch no remote.")
    ap.add_argument("--strict", action="store_true",
                    help="Block the push when the secret/PII lint flags "
                         "anything in the notes about to be published. "
                         "Default is warn-and-push.")
    ap.add_argument("--no-lint", action="store_true",
                    help="Skip the pre-push lint pass entirely.")
    args = ap.parse_args()

    if not vault_is_git_repo():
        info("vault is not a git repo. Run `strata init --git` first "
             "(and set vault_sync=git so writes auto-commit).")
        return 2

    branch = _current_branch()
    if not branch or branch == "HEAD":
        info("vault is in a detached-HEAD state — check out a branch before "
             "syncing.")
        return 2

    if _rebase_in_progress():
        info("a rebase is already in progress in the vault. Resolve it first:")
        info(f"  cd {vault_root()}")
        info("  # fix conflicts, then: git rebase --continue")
        info("  # or bail out with:    git rebase --abort")
        return 1

    remote = git_remote()  # explicit config; else rely on the branch upstream
    has_up = _has_upstream()
    if not remote and not has_up:
        info(f"vault is git-backed and on branch '{branch}', but no remote is "
             "configured — committing locally only.")
        if args.dry_run:
            info(f"dry-run: would commit pending changes locally "
                 f"(dirty tree: {'yes' if _is_dirty() else 'no'}); no remote "
                 "to pull/push.")
            return 0
        if _is_dirty():
            _run("add", "-A")
            _run("commit", "-m", "strata: sync local changes")
            info("committed pending local changes. Set a remote (or "
                 "git_remote in config) to pull/push.")
        return 0

    target = f"{remote or 'upstream'} {branch}".strip()
    if args.dry_run:
        info(f"dry-run: would commit pending changes, pull --rebase {target}, "
             f"{'and push' if not args.no_push else 'no push'}.")
        info(f"  dirty tree: {'yes' if _is_dirty() else 'no'}")
        return 0

    # 1. Commit local work first so a rebase never discards it.
    if _is_dirty():
        _run("add", "-A")
        c = _run("commit", "-m", "strata: sync local changes")
        if c is None or c.returncode != 0:
            info("nothing to commit (or commit failed) — continuing.")

    # 2. Pull with rebase (cleaner history than a merge bubble per note).
    pull_args = ["pull", "--rebase"]
    if remote:
        pull_args += [remote, branch]
    pull = _run(*pull_args)
    if pull is None:
        info("git not available.")
        return 2
    if pull.returncode != 0:
        err = (pull.stdout + pull.stderr).lower()
        if "couldn't find remote ref" in err:
            # First sync against an empty remote: nothing to pull yet —
            # fall through to the push, which creates the remote branch.
            info(f"remote has no '{branch}' branch yet — first push.")
        elif _rebase_in_progress() or "conflict" in err:
            info("pull hit a conflict. Nothing was pushed. Resolve by hand:")
            info(f"  cd {vault_root()}")
            info("  # edit the conflicted files, then:")
            info("  git add -A && git rebase --continue")
            info("  # or abandon the pull with: git rebase --abort")
            info("Re-run /strata:sync once the tree is clean.")
            return 1
        else:
            info(f"pull failed:\n{pull.stderr.strip() or pull.stdout.strip()}")
            return 1

    if args.no_push:
        info(f"pulled {target}. Skipped push (--no-push).")
        return 0

    # 3. Lint what's about to leave the machine. SECURITY.md's non-guarantee
    # is "lint catches secrets only if it's run" — sync is the chokepoint
    # where notes go from local to shared, so run it here by default.
    if not args.no_lint:
        findings = _lint_outgoing(has_upstream=_has_upstream())
        if findings:
            for line in findings[:20]:
                info(f"lint: {line}")
            if len(findings) > 20:
                info(f"lint: … and {len(findings) - 20} more")
            if args.strict:
                info("push blocked (--strict). Fix or forget the flagged "
                     "notes, or re-run without --strict to push anyway.")
                return 1
            info("pushing anyway (warn-only; pass --strict to block on this).")

    # 4. Push. Set upstream on first push when we know the remote.
    push_args = ["push"]
    if remote and not has_up:
        push_args = ["push", "-u", remote, branch]
    elif remote:
        push_args += [remote, branch]
    push = _run(*push_args)
    if push is None or push.returncode != 0:
        detail = (push.stderr.strip() or push.stdout.strip()) if push else "git missing"
        info(f"push failed:\n{detail}")
        return 1

    info(f"synced: pulled + pushed {target}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

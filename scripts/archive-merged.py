#!/usr/bin/env python3
"""Move pr-context directories for merged branches into archive/.

Two strategies for detecting "merged":
  - `gh` available + authed → query the repo's merged PRs and match by head ref.
  - fallback → use `git branch --merged main` (or the configured default branch).

Destination: `<vault>/<repo>/archive/<merge-date>--<branch-slug>/`.

Usage:
  python3 archive-merged.py [--dry-run] [--main-branch main] [--strategy gh|git|auto]
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys

import lib_loader  # noqa: F401
from lib import (
    branch_slug,
    ensure_dir,
    info,
    is_git_repo,
    memory_dir,
    project_dir,
    today,
)


def _gh_merged_branches() -> dict[str, str]:
    """Return {branch_slug: merge_date} via `gh pr list --state merged`."""
    if shutil.which("gh") is None:
        return {}
    pd = project_dir()
    if pd is None:
        return {}
    try:
        r = subprocess.run(
            ["gh", "pr", "list", "--state", "merged", "--limit", "200",
             "--json", "headRefName,mergedAt"],
            capture_output=True, text=True, check=False, timeout=15,
            cwd=str(pd),
        )
        if r.returncode != 0:
            return {}
        data = json.loads(r.stdout) if r.stdout.strip() else []
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        return {}
    out: dict[str, str] = {}
    for pr in data:
        head = pr.get("headRefName") or ""
        merged = (pr.get("mergedAt") or "")[:10]
        if head:
            out[branch_slug(head)] = merged or today()
    return out


def _git_merged_branches(main: str) -> dict[str, str]:
    """Fallback: branches reachable from main, excluding main itself."""
    pd = project_dir()
    if pd is None:
        return {}
    try:
        r = subprocess.run(
            ["git", "-C", str(pd), "branch", "--merged", main, "--format=%(refname:short)"],
            capture_output=True, text=True, check=False,
        )
        if r.returncode != 0:
            return {}
    except FileNotFoundError:
        return {}
    out: dict[str, str] = {}
    for line in r.stdout.splitlines():
        b = line.strip()
        if not b or b == main:
            continue
        out[branch_slug(b)] = today()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--main-branch", default="main",
                    help="Branch to compare against in git fallback mode.")
    ap.add_argument("--strategy", default="auto",
                    choices=["auto", "gh", "git"])
    args = ap.parse_args()

    if not is_git_repo():
        print("[strata] not a git repo", file=sys.stderr)
        return 2

    mem = memory_dir()
    pr_root = mem / "pr-context"
    if not pr_root.exists():
        info("no pr-context directory; nothing to archive")
        return 0

    # Detect merged branches
    merged: dict[str, str] = {}
    if args.strategy in ("auto", "gh"):
        merged = _gh_merged_branches()
        if merged:
            info(f"detected {len(merged)} merged branch(es) via gh")
    if not merged and args.strategy in ("auto", "git"):
        merged = _git_merged_branches(args.main_branch)
        if merged:
            info(f"detected {len(merged)} merged branch(es) via git")
    if not merged:
        info("no merged branches detected")
        return 0

    archive_root = mem / "archive"
    moved = 0
    skipped = 0
    for slug_dir in sorted(pr_root.iterdir()):
        if not slug_dir.is_dir():
            continue
        slug = slug_dir.name
        if slug not in merged:
            continue
        merge_date = merged[slug]
        dest_parent = archive_root / f"{merge_date}--{slug}"
        if dest_parent.exists():
            info(f"skip {slug}: archive target already exists")
            skipped += 1
            continue
        if args.dry_run:
            info(f"DRY: would move {slug_dir} → {dest_parent}")
        else:
            ensure_dir(archive_root)
            shutil.move(str(slug_dir), str(dest_parent))
            info(f"archived {slug} → {dest_parent.relative_to(mem)}")
        moved += 1

    info(f"summary: moved={moved} skipped={skipped} "
         f"merged_total={len(merged)}")

    # Refresh the index since the on-disk structure changed
    if moved and not args.dry_run:
        try:
            import importlib.util
            import os
            spec = importlib.util.spec_from_file_location(
                "refresh_index",
                os.path.join(os.path.dirname(__file__), "refresh-index.py"),
            )
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                mod.regenerate_index()
        except Exception as e:
            info(f"index refresh skipped: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

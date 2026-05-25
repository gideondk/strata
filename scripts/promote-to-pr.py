#!/usr/bin/env python3
"""Post a session summary as a comment on the current branch's open PR.

Skill invocation:
    python3 promote-to-pr.py [--pr N] [--dry-run] <<'EOF'
    <body>
    EOF

Defaults to the current branch's open PR. Refuses if there's no PR or no
auth. Always echoes the gh command before running it so the user sees the
mutation.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys

import lib_loader  # noqa: F401
import pr_context as _pr
from lib import current_branch, is_git_repo, project_dir


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pr", type=int, default=None,
                    help="PR number. Default: the open PR for the current branch.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the gh command and body, don't post.")
    args = ap.parse_args()

    if shutil.which("gh") is None:
        print("[strata] gh CLI not installed — cannot post PR comment",
              file=sys.stderr)
        return 2

    if not is_git_repo():
        print("[strata] not a git repo", file=sys.stderr)
        return 2

    body = sys.stdin.read().strip()
    if not body:
        print("[strata] error: empty body on stdin", file=sys.stderr)
        return 2

    pr_number = args.pr
    if pr_number is None:
        ctx = _pr.fetch_for_current_branch()
        if not ctx.available:
            print(f"[strata] no open PR for branch "
                  f"{current_branch()}: {ctx.reason}",
                  file=sys.stderr)
            return 2
        pr_number = ctx.number

    pd = project_dir()
    cmd = ["gh", "pr", "comment", str(pr_number), "--body-file", "-"]
    print(f"[strata] $ {' '.join(cmd)}  (cwd: {pd})")
    print(f"[strata] --- body ({len(body)} chars) ---")
    print(body)
    print("[strata] --- end body ---")

    if args.dry_run:
        print("[strata] dry-run — nothing posted")
        return 0

    r = subprocess.run(cmd, input=body, text=True,
                       capture_output=True,
                       cwd=str(pd) if pd else None)
    if r.returncode != 0:
        print(f"[strata] gh failed: {r.stderr.strip()}", file=sys.stderr)
        return 1

    print(f"[strata] posted to PR #{pr_number}")
    if r.stdout.strip():
        print(r.stdout.strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())

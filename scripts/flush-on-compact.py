#!/usr/bin/env python3
"""PreCompact hook — drop a breadcrumb file before context compaction.

We don't try to summarise the conversation here (that's Claude's job via
`/strata:save`). We just write a timestamped marker so the engineer knows
that compaction happened mid-session and can ask Claude to write a real save
note afterwards.
"""
from __future__ import annotations

import sys

import lib_loader  # noqa: F401
from lib import (
    author_initials,
    branch_slug,
    current_branch,
    ensure_dir,
    is_git_repo,
    pr_context_dir,
    stamp_minute,
    write_text,
)


def main() -> int:
    if not is_git_repo():
        return 0

    slug = branch_slug(current_branch())
    dir_ = pr_context_dir(slug)
    ensure_dir(dir_)

    fname = f"{stamp_minute()}--{author_initials()}--compaction-marker.md"
    path = dir_ / fname
    body = (
        "---\n"
        f"branch: {current_branch()}\n"
        "kind: compaction-marker\n"
        f"author: {author_initials()}\n"
        f"created: {stamp_minute()}\n"
        "---\n\n"
        "# Compaction marker\n\n"
        "Claude Code compacted the session here. The conversation up to this\n"
        "point is no longer in working context. If anything important was\n"
        "discussed, ask the model to summarise it via `/strata:save`.\n"
    )
    write_text(path, body)
    return 0


if __name__ == "__main__":
    sys.exit(main())

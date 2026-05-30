#!/usr/bin/env python3
"""Stop hook — nudge to save session notes when a session ends with
unsaved work.

This is the fallback surface: the primary nudge fires at the commit boundary
(see `on-bash.py`). Here we catch sessions that stopped without a commit but
still produced signal (commits in the window or uncommitted churn). We nudge
once per HEAD sha — committing then stopping won't double-fire because the
commit hook already recorded the sha. Output goes via top-level
`systemMessage` (the field Stop hooks accept)."""
from __future__ import annotations

import contextlib
import json
import sys
import time

import lib_loader  # noqa: F401
from lib import (
    branch_slug,
    current_branch,
    is_git_repo,
    memory_dir,
)

# A note saved this recently means the user already captured the session.
RECENT_SAVE_SECONDS = 30 * 60
# Floor between re-nudges for the *same* HEAD when only uncommitted churn has
# accumulated — keeps a stalled, uncommitted session from nagging every Stop.
MIN_RENUDGE_SECONDS = 10 * 60


def _last_pr_note_mtime(slug: str) -> float | None:
    dir_ = memory_dir() / "pr-context" / slug
    if not dir_.exists():
        return None
    latest = 0.0
    for p in dir_.glob("*.md"):
        try:
            latest = max(latest, p.stat().st_mtime)
        except OSError:
            continue
    return latest or None


def should_nudge(snap: dict) -> tuple[bool, str]:
    """Return (should_nudge, reason). reason is for debugging only."""
    if not is_git_repo():
        return False, "not a git repo"
    if not memory_dir().exists():
        return False, "vault not initialised"
    if not snap.get("available"):
        return False, "no session snapshot"

    commits = snap.get("commits") or []
    uncommitted = snap.get("uncommitted") or []
    if not commits and not uncommitted:
        return False, "no session activity"

    slug = branch_slug(snap.get("branch") or current_branch())
    last = _last_pr_note_mtime(slug)
    if last is not None and (time.time() - last) < RECENT_SAVE_SECONDS:
        return False, "recent save exists"

    # Once per commit boundary: if we already nudged for this HEAD, stay quiet
    # unless enough time has passed AND there's fresh uncommitted work.
    head = snap.get("head_sha")
    if head:
        import nudge_state
        state = nudge_state.load()
        if state.get("sha") == head:
            at = state.get("at") or 0.0
            if (time.time() - at) < MIN_RENUDGE_SECONDS:
                return False, "already nudged for this HEAD"
            if not uncommitted:
                return False, "no new work since last nudge"

    return True, "ok"


def main() -> int:
    # Stop hook receives JSON on stdin; we don't need it.
    with contextlib.suppress(Exception):
        _ = sys.stdin.read()

    try:
        import session_state
        snap = session_state.snapshot()
    except Exception:
        snap = {"available": False}

    nudge, _reason = should_nudge(snap)
    if not nudge:
        return 0

    import nudge_common
    drafted = nudge_common.stash_draft(snap)
    branch = snap.get("branch") or current_branch()
    message = nudge_common.build_message(snap, drafted=drafted, branch=branch)
    sys.stdout.write(json.dumps({"systemMessage": message}))

    head = snap.get("head_sha")
    if head:
        import nudge_state
        nudge_state.record(head)
    return 0


if __name__ == "__main__":
    sys.exit(main())

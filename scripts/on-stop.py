#!/usr/bin/env python3
"""Stop hook — nudge to save session notes on long feature-branch sessions.

Fires only when in a git repo, on a non-trunk branch, vault initialised, no
recent save, and 30-min cooldown elapsed since last nudge. Output goes via
`additionalContext`."""
from __future__ import annotations

import contextlib
import json
import sys
import time
from pathlib import Path

import lib_loader  # noqa: F401
from lib import (
    branch_slug,
    current_branch,
    is_git_repo,
    memory_dir,
    plugin_data_dir,
)

TRUNK_BRANCHES = {"main", "master", "develop", "trunk", "default"}
COOLDOWN_SECONDS = 30 * 60  # 30 minutes


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


def _cooldown_path() -> Path:
    return plugin_data_dir() / ".stop-last"


def _within_cooldown() -> bool:
    p = _cooldown_path()
    if not p.exists():
        return False
    try:
        ts = float(p.read_text().strip())
    except (OSError, ValueError):
        return False
    return (time.time() - ts) < COOLDOWN_SECONDS


def _mark_fired() -> None:
    p = _cooldown_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(time.time()))
    except OSError:
        pass


def should_nudge() -> tuple[bool, str]:
    """Return (should_nudge, reason). reason is for debugging only."""
    if not is_git_repo():
        return False, "not a git repo"
    branch = current_branch()
    if branch in TRUNK_BRANCHES or branch == "unknown":
        return False, f"trunk branch: {branch}"
    if not memory_dir().exists():
        return False, "vault not initialised"
    if _within_cooldown():
        return False, "within cooldown"
    slug = branch_slug(branch)
    last = _last_pr_note_mtime(slug)
    if last is not None and (time.time() - last) < COOLDOWN_SECONDS:
        return False, "recent save exists"
    return True, "ok"


def main() -> int:
    # Stop hook receives JSON on stdin; we don't need it.
    with contextlib.suppress(Exception):
        _ = sys.stdin.read()

    nudge, _reason = should_nudge()
    if not nudge:
        return 0

    _mark_fired()

    # Rich session snapshot: commits + uncommitted + hot paths + topic
    # suggestion. Falls back gracefully if nothing's available.
    summary = ""
    try:
        import session_state
        snap = session_state.snapshot()
        summary = session_state.stop_nudge_text(snap)
    except Exception:
        summary = ""

    # Append a graph-staleness signal when relevant.
    extra = ""
    try:
        import code_graph
        staleness = code_graph.graph_age_relative_to_head()
        if staleness and staleness.get("stale"):
            extra = (
                f"  Also: code graph is stale ({staleness['reason']}) — "
                f"`/strata:graphify` to refresh."
            )
    except Exception:
        pass

    # Stop hooks don't accept hookSpecificOutput.additionalContext — the
    # right top-level field is `systemMessage`.
    if summary:
        message = "💭 Strata: " + summary + extra
    else:
        branch = current_branch()
        message = (
            f"💭 Strata: 30+ min on `{branch}` without a saved note. "
            f"Consider `/strata:save` with a short topic + 3-5 bullets "
            f"covering what was done, decided, and left open." + extra
        )
    sys.stdout.write(json.dumps({"systemMessage": message}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

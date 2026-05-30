#!/usr/bin/env python3
"""PostToolUse(Bash) hook — two jobs:

1. Branch switch → re-prime context with a fresh primer.
2. `git commit` that advances HEAD → nudge to save a note, at the natural
   reflection point. This is the primary save-nudge surface; the Stop hook is
   the fallback for sessions that stop without committing. Dedup is by HEAD
   sha (see `nudge_state.py`), so we nudge once per commit boundary.
"""
from __future__ import annotations

import json
import re
import sys

import lib_loader  # noqa: F401
from lib import info

# Matches the actual switch commands, not e.g. `git log` or `git diff main..HEAD`
SWITCH_RE = re.compile(
    r"""(?xm)
    \bgit\s+
    (?:
        checkout(?!\s+-{1,2}\b)\s+[\w./\-]+      # git checkout <branch>
      | switch\s+[\w./\-]+                       # git switch <branch>
      | worktree\s+add\b                         # git worktree add ...
    )
    """,
)

# `git commit` (incl. `git commit -m`, `--amend`); not `git commit-tree` etc.
COMMIT_RE = re.compile(r"\bgit\s+commit\b")


def _reprime() -> int:
    info("branch switch detected — re-priming context")
    # Reuse prime-context.py to keep one source of truth
    import importlib.util
    import os

    spec = importlib.util.spec_from_file_location(
        "prime_context",
        os.path.join(os.path.dirname(__file__), "prime-context.py"),
    )
    if spec is None or spec.loader is None:
        return 0
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    primer = mod.build_primer()

    out = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": primer,
        }
    }
    sys.stdout.write(json.dumps(out))
    return 0


def _commit_nudge() -> int:
    """Fire the save-nudge once per new HEAD sha after a commit."""
    from lib import memory_dir
    if not memory_dir().exists():
        return 0

    try:
        import session_state
        snap = session_state.snapshot()
    except Exception:
        return 0
    if not snap.get("available"):
        return 0

    head = snap.get("head_sha")
    if not head:
        return 0

    import nudge_state
    if nudge_state.load().get("sha") == head:
        return 0  # already nudged for this commit boundary

    import nudge_common
    drafted = nudge_common.stash_draft(snap)
    message = nudge_common.build_message(
        snap, drafted=drafted, branch=snap.get("branch") or "",
    )
    sys.stdout.write(json.dumps({"systemMessage": message}))
    nudge_state.record(head)
    return 0


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    tool_input = payload.get("tool_input") or {}
    command = tool_input.get("command") or ""
    if not isinstance(command, str):
        return 0

    if SWITCH_RE.search(command):
        return _reprime()
    if COMMIT_RE.search(command):
        return _commit_nudge()
    return 0


if __name__ == "__main__":
    sys.exit(main())

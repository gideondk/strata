#!/usr/bin/env python3
"""PostToolUse(Bash) hook — re-prime context when the user changes branches.

We read the tool input JSON from stdin, check if the command was a branch
switch, and emit a fresh primer if so. Anything else is a no-op.
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


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    tool_input = payload.get("tool_input") or {}
    command = tool_input.get("command") or ""

    if not isinstance(command, str) or not SWITCH_RE.search(command):
        return 0

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


if __name__ == "__main__":
    sys.exit(main())

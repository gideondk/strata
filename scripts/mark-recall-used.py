#!/usr/bin/env python3
"""PostToolUse hook (matcher `mcp__.*recall`): record that the `recall` MCP tool
ran this session.

This is what lifts the vault-grep gate in guard-vault-read.py — once Claude has
actually used recall (the ranked, supersession-aware path), a deliberate raw
grep is allowed as a fallback. Until then, vault grep stays blocked. Mirrors
codebase-memory-mcp's "MARKER" (tool-used) signal.

Best-effort, fail-open. Emits no output (the recall result is unchanged).
"""
from __future__ import annotations

import contextlib
import json
import sys

import lib_loader  # noqa: F401
import vault_guard_state as state


def main() -> int:
    with contextlib.suppress(Exception):
        data = json.load(sys.stdin)
        session_id = str(data.get("session_id") or "_")
        # Matcher already scoped us to recall-ish MCP tools; double-check the
        # name so a loose matcher can't mark on the wrong tool.
        if "recall" in str(data.get("tool_name") or "").lower():
            state.mark(session_id, "recall-used")
    return 0


if __name__ == "__main__":
    sys.exit(main())

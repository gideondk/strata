#!/usr/bin/env python3
"""PreToolUse guard: keep Claude on recall, off raw Read/Grep/Glob of the vault.

The whole point of Strata's retrieval — ranked hybrid recall, supersession
demotion, quarantine of unreviewed (`status: auto`) and invalidated notes — only
applies when memory is read through the `recall` MCP tool. A raw grep of the
vault returns the RAW corpus: superseded and invalidated notes at full weight,
unranked. That silently defeats the moat.

FIRM gate (stronger than codebase-memory-mcp's warn-once variant): a vault
Grep/Glob is DENIED until `recall` has actually been used this session — then
allowed, so a deliberate fallback still works once the proper path has been
exercised. The recall-used marker is set by the PostToolUse hook
`mark-recall-used.py`. A single Read of one note is allowed but gets a one-time
reminder.

Best-effort, fail-open: any error emits nothing (exit 0) and never breaks a tool
call. The plugin's own scripts read the vault via Bash/run-python.sh, not these
tools, so they're unaffected.
"""
from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

import lib_loader  # noqa: F401
import vault_guard_state as state
from lib import vault_root


def _target(tool_input: dict) -> str | None:
    # Read uses file_path; Grep/Glob use path (search root, optional).
    return tool_input.get("file_path") or tool_input.get("path")


def _in_vault(candidate: str) -> bool:
    try:
        target = Path(candidate).expanduser().resolve()
        root = vault_root().resolve()
    except Exception:
        return False
    return target == root or root in target.parents


def main() -> int:
    with contextlib.suppress(Exception):
        data = json.load(sys.stdin)
        tool = data.get("tool_name")
        tool_input = data.get("tool_input") or {}
        session_id = str(data.get("session_id") or "_")
        candidate = _target(tool_input)
        # Grep/Glob with no path search the cwd (the repo), not the vault — leave
        # those alone. Only act when the access points into the vault.
        if not candidate or not _in_vault(candidate):
            return 0

        if tool in ("Grep", "Glob"):
            if state.is_set(session_id, "recall-used"):
                return 0  # recall exercised this session — allow the fallback
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    "Use the `recall` MCP tool to search Strata memory — not a "
                    "raw grep of the vault. Recall is ranked and "
                    "supersession-aware: it demotes superseded/deprecated notes "
                    "and hides invalidated + unreviewed ones, which grep does "
                    "not, so grep can surface a stale note as if current. Raw "
                    "vault grep stays blocked until you've used `recall` once "
                    "this session; after that it's allowed as a fallback."),
            }}))
        elif tool == "Read" and not state.mark_if_unset(session_id, "read"):
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": (
                    "Heads up: reading a Strata vault file directly bypasses "
                    "recall's supersession demotion and the quarantine of "
                    "invalidated/unreviewed notes — a superseded note can look "
                    "current. For anything search- or recall-shaped, prefer the "
                    "`recall` MCP tool. (Shown once per session.)"),
            }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

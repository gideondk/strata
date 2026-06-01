#!/usr/bin/env python3
"""PreToolUse guard: steer Claude off raw Read/Grep/Glob of the vault and onto
recall — using the proven "block-once-then-allow" pattern.

The whole point of Strata's retrieval — ranked hybrid recall, supersession
demotion, quarantine of unreviewed (`status: auto`) and invalidated notes — only
applies when memory is read through the `recall` MCP tool (or `/strata:find`).
A raw grep of the vault returns the RAW corpus: superseded and invalidated notes
at full weight, unranked. That silently defeats the moat.

Pattern (after codebase-memory-mcp's "CBM-first" gate): don't hard-block
forever — that feels broken and removes the legitimate fallback. Instead, the
FIRST time per session Claude greps the vault, DENY with a redirect to recall
(so it learns the tool exists); after that, allow, so a deliberate fallback
still works. A single Read of one note is allowed but gets a one-time reminder.

State is a per-session marker in plugin-data. Best-effort, fail-open: any error
emits nothing (exit 0) and never breaks a tool call. The plugin's own scripts
read the vault via Bash/run-python.sh, not these tools, so they're unaffected.
"""
from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

import lib_loader  # noqa: F401
from lib import plugin_data_dir, vault_root


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


def _gate(session_id: str, kind: str) -> Path:
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_")[:64] or "_"
    return plugin_data_dir() / f"vault-guard-{kind}-{safe}"


def _seen(session_id: str, kind: str) -> bool:
    """Has this steer already fired this session? Marks it if not (so it's a
    once-per-session redirect, never a permanent wall)."""
    g = _gate(session_id, kind)
    if g.exists():
        return True
    with contextlib.suppress(OSError):
        g.parent.mkdir(parents=True, exist_ok=True)
        g.touch()
    return False


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
            if _seen(session_id, "search"):
                return 0  # already redirected this session — preserve fallback
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    "Use the `recall` MCP tool (or `/strata:find`) instead of "
                    "grepping the Strata vault. Recall is ranked and "
                    "supersession-aware: it demotes superseded/deprecated notes "
                    "and hides invalidated + unreviewed ones, which a raw grep "
                    "does not — so grep can surface a stale note as if current. "
                    "(If you genuinely need a raw scan, retry; this redirect "
                    "fires once per session.)"),
            }}))
        elif tool == "Read" and not _seen(session_id, "read"):
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

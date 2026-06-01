"""Tests for the PreToolUse vault-read guard: keep Claude on recall, off raw
Read/Grep/Glob of the vault — block-once-then-allow, never a permanent wall."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GUARD = HERE.parent / "scripts" / "guard-vault-read.py"


def _run(payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(GUARD)],
                          input=json.dumps(payload), capture_output=True,
                          text=True, env=os.environ.copy())


def _grep(path: str, session: str) -> dict:
    return {"session_id": session, "tool_name": "Grep",
            "tool_input": {"pattern": "foo", "path": path}}


def test_first_vault_grep_denied_then_allowed(initialised_vault):
    """Block-once-then-allow: the first vault grep in a session is denied with a
    recall redirect; a second one is allowed (fallback preserved)."""
    vault = os.environ["STRATA_VAULT_PATH"]
    first = _run(_grep(vault, "sess-A"))
    out = json.loads(first.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"
    assert "recall" in out["permissionDecisionReason"].lower()
    # Same session, second attempt → no longer blocked.
    second = _run(_grep(vault, "sess-A"))
    assert second.stdout.strip() == "", "second grep must fall through (allow)"


def test_glob_into_vault_is_denied_first(initialised_vault):
    vault = os.environ["STRATA_VAULT_PATH"]
    r = _run({"session_id": "sess-B", "tool_name": "Glob",
              "tool_input": {"pattern": "**/*.md", "path": vault}})
    assert json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_read_of_vault_note_allowed_but_steered_once(initialised_vault):
    note = str(Path(os.environ["STRATA_VAULT_PATH"]) / "myrepo" / "decisions" / "x.md")
    payload = {"session_id": "sess-C", "tool_name": "Read",
               "tool_input": {"file_path": note}}
    first = _run(payload)
    out = json.loads(first.stdout)["hookSpecificOutput"]
    assert "additionalContext" in out and "permissionDecision" not in out
    assert "supersed" in out["additionalContext"].lower()
    # Reminder is once-per-session — second read is silent.
    assert _run(payload).stdout.strip() == ""


def test_grep_outside_vault_is_left_alone(initialised_vault):
    r = _run(_grep(os.environ["CLAUDE_PROJECT_DIR"], "sess-D"))
    assert r.stdout.strip() == ""  # repo greps untouched


def test_grep_without_path_defers(initialised_vault):
    r = _run({"session_id": "sess-E", "tool_name": "Grep",
              "tool_input": {"pattern": "foo"}})
    assert r.stdout.strip() == ""  # no path → searches cwd, not the vault

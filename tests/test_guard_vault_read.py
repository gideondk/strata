"""Tests for the FIRM vault-read guard: vault Grep/Glob is denied until `recall`
has been used this session, then allowed (fallback preserved). Read is allowed
with a once-per-session reminder."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GUARD = HERE.parent / "scripts" / "guard-vault-read.py"
MARK = HERE.parent / "scripts" / "mark-recall-used.py"


def _run(script: Path, payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(script)],
                          input=json.dumps(payload), capture_output=True,
                          text=True, env=os.environ.copy())


def _grep(path: str, session: str) -> dict:
    return {"session_id": session, "tool_name": "Grep",
            "tool_input": {"pattern": "foo", "path": path}}


def test_vault_grep_denied_until_recall_used(initialised_vault):
    vault = os.environ["STRATA_VAULT_PATH"]
    # Denied on the first attempt…
    out = json.loads(_run(GUARD, _grep(vault, "sess-A")).stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"
    assert "recall" in out["permissionDecisionReason"].lower()
    # …and STILL denied on a retry (firm — no warn-once escape).
    assert json.loads(_run(GUARD, _grep(vault, "sess-A")).stdout
                      )["hookSpecificOutput"]["permissionDecision"] == "deny"
    # Use recall (PostToolUse marker), then the grep falls through (allowed).
    _run(MARK, {"session_id": "sess-A", "tool_name": "mcp__strata__recall",
                "tool_input": {"query": "x"}})
    assert _run(GUARD, _grep(vault, "sess-A")).stdout.strip() == ""


def test_mark_recall_used_writes_session_marker(initialised_vault):
    _run(MARK, {"session_id": "sess-X", "tool_name": "mcp__strata__recall",
                "tool_input": {"query": "x"}})
    marker = Path(os.environ["CLAUDE_PLUGIN_DATA"]) / "vault-guard-recall-used-sess-X"
    assert marker.exists()


def test_glob_into_vault_denied_without_recall(initialised_vault):
    vault = os.environ["STRATA_VAULT_PATH"]
    r = _run(GUARD, {"session_id": "sess-B", "tool_name": "Glob",
                     "tool_input": {"pattern": "**/*.md", "path": vault}})
    assert json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_read_of_vault_note_allowed_but_steered_once(initialised_vault):
    note = str(Path(os.environ["STRATA_VAULT_PATH"]) / "myrepo" / "decisions" / "x.md")
    payload = {"session_id": "sess-C", "tool_name": "Read",
               "tool_input": {"file_path": note}}
    out = json.loads(_run(GUARD, payload).stdout)["hookSpecificOutput"]
    assert "additionalContext" in out and "permissionDecision" not in out
    assert "supersed" in out["additionalContext"].lower()
    assert _run(GUARD, payload).stdout.strip() == ""  # reminder is once per session


def test_grep_outside_vault_is_left_alone(initialised_vault):
    r = _run(GUARD, _grep(os.environ["CLAUDE_PROJECT_DIR"], "sess-D"))
    assert r.stdout.strip() == ""


def test_grep_without_path_defers(initialised_vault):
    r = _run(GUARD, {"session_id": "sess-E", "tool_name": "Grep",
                     "tool_input": {"pattern": "foo"}})
    assert r.stdout.strip() == ""

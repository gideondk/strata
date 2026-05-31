"""Tests for the PreCompact hook — the actionable compaction breadcrumb."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FLUSH = HERE.parent / "scripts" / "flush-on-compact.py"


def _run(stdin: str = "") -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(FLUSH)],
        input=stdin, capture_output=True, text=True, check=False,
        env=os.environ.copy(),
    )


def _markers(vault_repo: Path) -> list[Path]:
    pr = vault_repo / "pr-context"
    return sorted(pr.rglob("*compaction-marker.md")) if pr.exists() else []


def test_marker_written_with_trigger(initialised_vault):
    r = _run('{"trigger": "auto"}')
    assert r.returncode == 0, r.stderr
    markers = _markers(initialised_vault)
    assert markers, "no compaction-marker written"
    text = markers[-1].read_text()
    assert "kind: compaction-marker" in text
    assert "trigger: auto" in text
    assert "compacted the session here (auto)" in text


def test_trigger_defaults_to_unknown_on_empty_stdin(initialised_vault):
    r = _run("")  # malformed/empty stdin must not crash
    assert r.returncode == 0, r.stderr
    text = _markers(initialised_vault)[-1].read_text()
    assert "trigger: unknown" in text


def test_marker_never_dumps_conversation(initialised_vault):
    """The breadcrumb must stay content-free: only git-derived state, never
    arbitrary conversation text piped on stdin."""
    secret = "zsecretconversationmarker"
    r = _run(f'{{"trigger": "manual", "transcript": "{secret}"}}')
    assert r.returncode == 0, r.stderr
    text = _markers(initialised_vault)[-1].read_text()
    assert secret not in text

"""Per-session markers shared by the vault-read guard (PreToolUse) and the
recall-used marker (PostToolUse). One module so the two hooks agree on the
marker path and can't drift. Markers live in plugin-data (disposable, local).
"""
from __future__ import annotations

import contextlib
from pathlib import Path

from lib import plugin_data_dir


def _path(session_id: str, kind: str) -> Path:
    safe = "".join(c for c in str(session_id) if c.isalnum() or c in "-_")[:64] or "_"
    return plugin_data_dir() / f"vault-guard-{kind}-{safe}"


def mark(session_id: str, kind: str) -> None:
    """Record that `kind` happened this session. Best-effort."""
    p = _path(session_id, kind)
    with contextlib.suppress(OSError):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch()


def is_set(session_id: str, kind: str) -> bool:
    return _path(session_id, kind).exists()


def mark_if_unset(session_id: str, kind: str) -> bool:
    """Return whether `kind` was ALREADY set, and set it if not — for
    once-per-session steers."""
    if is_set(session_id, kind):
        return True
    mark(session_id, kind)
    return False

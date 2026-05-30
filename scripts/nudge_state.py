"""Dedup state shared by the two nudge surfaces.

Both the Stop hook (`on-stop.py`) and the commit-boundary PostToolUse hook
(`on-bash.py`) record the HEAD sha they last nudged for. That makes the nudge
fire once per commit boundary instead of on a wall-clock timer — committing is
the natural reflection point, and a second Stop right after a commit stays
silent because the sha already matches.
"""
from __future__ import annotations

import contextlib
import json
import time
from pathlib import Path
from typing import Any

from lib import plugin_data_dir


def _state_path() -> Path:
    return plugin_data_dir() / ".last-nudge.json"


def load() -> dict[str, Any]:
    p = _state_path()
    if not p.exists():
        return {}
    with contextlib.suppress(OSError, ValueError):
        data = json.loads(p.read_text())
        if isinstance(data, dict):
            return data
    return {}


def last_sha() -> str | None:
    sha = load().get("sha")
    return sha if isinstance(sha, str) else None


def last_at() -> float | None:
    at = load().get("at")
    return float(at) if isinstance(at, (int, float)) else None


def record(sha: str) -> None:
    """Stamp the sha we just nudged for. Never raises — a failed write only
    means the next call may re-nudge for the same sha, which is harmless."""
    p = _state_path()
    with contextlib.suppress(OSError):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"sha": sha, "at": time.time()}))

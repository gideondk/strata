"""Local, content-free usage telemetry for the Strata vault.

Answers the questions the system implies but otherwise can't see: *is the vault
actually used? which notes are dead weight?* Logs paths / scopes / events only
— never note content — to an append-only JSONL in plugin-data (disposable, like
the index). No network, stdlib only. Never raises into a caller.
"""
from __future__ import annotations

import contextlib
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

from lib import plugin_data_dir


def _path() -> Path:
    return plugin_data_dir() / "usage.jsonl"


def log_event(event: str, **fields: Any) -> None:
    """Append one event. Best-effort: a failed write is swallowed (telemetry
    must never break a recall or a hook)."""
    rec = {"event": event, "ts": time.time(), **fields}
    p = _path()
    with contextlib.suppress(OSError, TypeError, ValueError):
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")


def log_recall_hits(hits) -> None:
    """Record the notes a recall surfaced. `hits` is an iterable of
    (path, scope, rank)."""
    for path, scope, rank in hits:
        if path:
            log_event("recall_hit", path=path, scope=scope, rank=rank)


def _read(since_days: float | None = None) -> list[dict]:
    p = _path()
    if not p.exists():
        return []
    cutoff = (time.time() - since_days * 86400) if since_days else 0.0
    out: list[dict] = []
    with contextlib.suppress(OSError):
        for line in p.read_text(encoding="utf-8",
                                errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            with contextlib.suppress(ValueError):
                rec = json.loads(line)
                if isinstance(rec, dict) and rec.get("ts", 0) >= cutoff:
                    out.append(rec)
    return out


def recalled_paths(since_days: float = 30) -> set[str]:
    """Paths surfaced by any recall in the window — used to find dead notes."""
    return {e["path"] for e in _read(since_days)
            if e.get("event") == "recall_hit" and e.get("path")}


def summary(since_days: float = 30, top: int = 8) -> dict:
    events = _read(since_days)
    hits = [e for e in events
            if e.get("event") == "recall_hit" and e.get("path")]
    counts = Counter(e["path"] for e in hits)
    nudges = sum(1 for e in events if e.get("event") == "nudge_shown")
    return {
        "since_days": since_days,
        "events": len(events),
        "recall_hits": len(hits),
        "distinct_recalled": len(counts),
        "top_recalled": [{"path": p, "hits": n}
                         for p, n in counts.most_common(top)],
        "nudges_shown": nudges,
    }

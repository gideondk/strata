"""Local, content-free usage telemetry for the Strata vault.

Answers the questions the system implies but otherwise can't see: *is the vault
actually used? which notes are dead weight? what got recalled, when, and why?*
Logs paths / scopes / events — and the recall *query* itself, since the query
is the "why" behind a recall and the audit trail is useless without it — but
never note *content*. Append-only JSONL in plugin-data (disposable, like the
index). No network, stdlib only. Never raises into a caller.

This is best-effort ANALYTICS, not a compliance audit trail. Writes are wrapped
in contextlib.suppress, so a dropped event is silent — fine for "is the vault
used?" telemetry, wrong for anything an auditor must rely on. The durable,
tamper-evident record is the vault itself: git history + per-note frontmatter
provenance (author, timestamps, corrections, supersession). Don't route a
compliance requirement here.
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
    (path, scope, rank). Feeds dead-weight detection (recalled_paths)."""
    for path, scope, rank in hits:
        if path:
            log_event("recall_hit", path=path, scope=scope, rank=rank)


def log_recall(query: str, scope: str | None, hits, mechanism: str) -> None:
    """Record one recall as a single grouped audit event: the query that ran,
    how it was answered (`mechanism`, e.g. "fts", "rrf", "rrf+rerank"), and the
    ranked paths it returned. This is the *what/when/why* audit trail — distinct
    from the per-path recall_hit events that drive dead-weight detection.
    `hits` is an iterable of (path, scope, rank)."""
    returned = [{"path": p, "scope": s, "rank": r}
                for p, s, r in hits if p]
    log_event("recall", query=(query or "").strip()[:300],
              scope=scope or "all", mechanism=mechanism, n=len(returned),
              hits=returned)


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


def recall_stats(since_days: float = 365) -> dict[str, dict]:
    """Per-path recall signal for staleness scoring: hit count and the most
    recent recall timestamp, over a wide window. {path: {hits, last_ts}}."""
    out: dict[str, dict] = {}
    for e in _read(since_days):
        if e.get("event") != "recall_hit":
            continue
        path = e.get("path")
        if not path:
            continue
        rec = out.setdefault(path, {"hits": 0, "last_ts": 0.0})
        rec["hits"] += 1
        ts = float(e.get("ts", 0.0))
        if ts > rec["last_ts"]:
            rec["last_ts"] = ts
    return out


def recent_recalls(since_days: float = 7, limit: int = 10) -> list[dict]:
    """The most recent grouped recall events, newest first — the observability
    audit trail. Each is {ts, query, scope, mechanism, n, hits:[{path,...}]}."""
    recalls = [e for e in _read(since_days) if e.get("event") == "recall"]
    recalls.sort(key=lambda e: e.get("ts", 0), reverse=True)
    return recalls[:limit]


def summary(since_days: float = 30, top: int = 8) -> dict:
    events = _read(since_days)
    hits = [e for e in events
            if e.get("event") == "recall_hit" and e.get("path")]
    counts = Counter(e["path"] for e in hits)
    nudges = sum(1 for e in events if e.get("event") == "nudge_shown")
    saves = [e for e in events if e.get("event") == "note_saved"]
    via_draft = sum(1 for e in saves if e.get("via_draft"))
    # RAW counts only — do NOT divide saves_via_draft by nudges_shown for an
    # "accept rate": the denominators don't match (a nudge fires without a
    # stashed draft, and a draft can be saved without a nudge). A true
    # accept-rate needs paired draft-offered/draft-accepted events, which the
    # deferred graduation policy will add. Per-kind counts seed that policy.
    by_kind = Counter(str(e.get("kind") or "?") for e in saves)
    return {
        "since_days": since_days,
        "events": len(events),
        "recall_hits": len(hits),
        "distinct_recalled": len(counts),
        "top_recalled": [{"path": p, "hits": n}
                         for p, n in counts.most_common(top)],
        "nudges_shown": nudges,
        "notes_saved": len(saves),
        "saves_via_draft": via_draft,
        "saves_by_kind": dict(by_kind),
    }

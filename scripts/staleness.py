"""Importance-weighted staleness scoring for durable vault notes — replaces
the crude ">30d old, never recalled" heuristic.

Ebbinghaus-style exponential decay (FadeMem arXiv:2601.18642, SSGM
arXiv:2603.11768): hot notes decay slowly, cold old ones fast. Derived on
demand — no counters, no sidecar table — so the vault stays git/Obsidian-clean.

Two signals, deliberately scoped (full rationale in the shared-vault-fix commit):
- Age uses the note's frontmatter `date:`/`created:`, NOT filesystem mtime —
  mtime resets to sync time, making a freshly-synced vault look all-fresh.
- Recall comes from the local, per-machine usage ledger; it can only *lower*
  staleness, never raise it, so a team-hot note I never recall is at worst an
  advisory "review?", never an auto-archive.
"""
from __future__ import annotations

import math
import re
import time
from datetime import datetime, timezone
from pathlib import Path

_DATE_KEYS = ("date", "created", "updated", "created_at")
# Frontmatter stamps are either YYYY-MM-DD (today()) or YYYY-MM-DD-HHMM
# (stamp_minute()). Match the leading date, optional -HHMM.
_STAMP_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:-(\d{2})(\d{2}))?")

# Durable scopes worth scoring. pr-context / propositions are intentionally
# excluded: branch context is meant to age out, and propositions track their
# own open/settled lifecycle.
DURABLE_SCOPES = ("decisions", "domain", "lessons", "procedural")

# Retention half-life-ish constant in days. ~90d means a never-recalled note
# is ~63% decayed (staleness ~0.63) at one tau, ~86% at two tau.
TAU_DAYS = 90.0


def _parse_stamp(value: str) -> float | None:
    """Parse a frontmatter date stamp (YYYY-MM-DD or YYYY-MM-DD-HHMM) to a UTC
    epoch. Returns None if it doesn't match."""
    m = _STAMP_RE.match(str(value).strip().strip("'\""))
    if not m:
        return None
    y, mo, d, hh, mm = m.groups()
    try:
        dt = datetime(int(y), int(mo), int(d), int(hh or 0), int(mm or 0),
                      tzinfo=timezone.utc)
    except ValueError:
        return None
    return dt.timestamp()


def edit_epoch(abs_path: Path, fallback_mtime: float) -> float:
    """Sync-stable 'last edited' epoch for a note: the frontmatter date field,
    falling back to filesystem mtime only when none is parseable. Reads just
    the frontmatter block (cheap) — durable scopes are a bounded set."""
    try:
        head = abs_path.read_text(encoding="utf-8", errors="replace")[:600]
    except OSError:
        return fallback_mtime
    best: float | None = None
    for line in head.splitlines():
        if line.strip() in ("---", "") and best is not None:
            break
        key, _, val = line.partition(":")
        if key.strip().lower() in _DATE_KEYS and val.strip():
            ts = _parse_stamp(val)
            if ts is not None:
                # Prefer the most specific/earliest matching key; `updated`
                # beats `created` beats `date` only if later — take the max so
                # an explicit `updated` wins.
                best = ts if best is None else max(best, ts)
    return best if best is not None else fallback_mtime


def score(mtime: float, *, now: float, hits: int = 0,
          last_recall_ts: float = 0.0, tau_days: float = TAU_DAYS) -> float:
    """Staleness in [0, 1]: 0 = fresh/active, 1 = stale (review/archive).

    retention = exp(-age / (tau * importance)); staleness = 1 - retention,
    where `age` is measured from the most recent of (modified, last recalled)
    and `importance` rises with recall frequency so hot notes decay slower.
    """
    last_touch = max(mtime, last_recall_ts)
    age_days = max(0.0, (now - last_touch) / 86400.0)
    importance = 1.0 + math.log1p(max(0, hits))  # 1 hit→1.69x, 10→3.4x slower
    effective_tau = tau_days * importance
    retention = math.exp(-age_days / effective_tau)
    return 1.0 - retention


def rank_stale(limit: int = 10, threshold: float = 0.66,
               scopes: tuple[str, ...] = DURABLE_SCOPES) -> list[dict]:
    """Durable notes ranked by staleness (most stale first), filtered to those
    at or above `threshold`. Best-effort — returns [] if the index or ledger
    is unavailable. Each entry: {path, title, scope, staleness, age_days, hits}.
    """
    try:
        import db
        import usage
        from lib import memory_dir
    except Exception:
        return []

    now = time.time()
    try:
        recall = usage.recall_stats()
    except Exception:
        recall = {}
    mem = memory_dir()

    rows: list[dict] = []
    try:
        placeholders = ",".join("?" for _ in scopes)
        with db.connect() as conn:
            for r in conn.execute(
                f"SELECT path, title, scope, mtime FROM files "
                f"WHERE scope IN ({placeholders})",
                tuple(scopes),
            ).fetchall():
                rec = recall.get(r["path"], {})
                # Sync-stable age: frontmatter date, mtime only as fallback.
                edited = edit_epoch(mem / r["path"], float(r["mtime"] or now))
                s = score(edited, now=now,
                          hits=int(rec.get("hits", 0)),
                          last_recall_ts=float(rec.get("last_ts", 0.0)))
                if s >= threshold:
                    rows.append({
                        "path": r["path"],
                        "title": r["title"] or r["path"],
                        "scope": r["scope"],
                        "staleness": round(s, 3),
                        "age_days": round((now - edited) / 86400.0, 1),
                        "hits": int(rec.get("hits", 0)),
                    })
    except Exception:
        return []

    rows.sort(key=lambda d: d["staleness"], reverse=True)
    return rows[:limit]

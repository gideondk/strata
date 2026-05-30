"""Deferred questions awaiting human input — the "question" leg of the
notify / question / review model.

Built over EXISTING vault state, not a new store (per the research: a deferred
question IS a durable open proposition that resurfaces by aging). Surfaced
pull-based by `/strata:dashboard`'s "Awaiting your input" section and, batched
and default-silent, by the commit/Stop nudge. Nothing here creates a new
interruption on its own — it only rides a nudge that was already going to fire,
or a pull.
"""
from __future__ import annotations

import contextlib
import time

import db
import lib_loader  # noqa: F401

# A proposition younger than this isn't "lingering" yet — don't nag about it.
QUESTION_AGE_DAYS = 1

# Statuses that represent an unresolved question. The dashboard shows all of
# these; the nudge narrows to open/contested (converging is trending to a
# resolution — nagging about it is noise).
QUESTION_STATUSES = ("open", "contested", "converging")


def auto_notes(limit: int = 20) -> list[dict]:
    """Staged auto-captured notes (`status: auto`) awaiting human review — keep
    (edit) or discard (`/strata:forget`). The quarantine tier of the autonomy
    line. Hook-safe (never raises)."""
    now = time.time()
    out: list[dict] = []
    with contextlib.suppress(Exception), db.connect() as conn:
        for r in conn.execute(
            "SELECT path, title, scope, mtime FROM files "
            "WHERE status = 'auto' ORDER BY mtime DESC LIMIT ?",
            (limit,),
        ):
            out.append({
                "kind": "auto",
                "path": r["path"],
                "title": r["title"],
                "scope": r["scope"],
                "age_days": int((now - (r["mtime"] or now)) // 86400),
            })
    return out


def aging_questions(min_age_days: int = QUESTION_AGE_DAYS,
                    statuses: tuple[str, ...] = QUESTION_STATUSES) -> list[dict]:
    """Propositions in one of `statuses` older than `min_age_days`, oldest
    first. Runs inside the Stop/PostToolUse hooks, so it must never raise —
    any failure degrades to an empty queue rather than crashing the hook."""
    now = time.time()
    cutoff = now - min_age_days * 86400
    out: list[dict] = []
    placeholders = ", ".join("?" for _ in statuses)
    with contextlib.suppress(Exception), db.connect() as conn:
        rows = conn.execute(
            "SELECT path, title, status, mtime FROM files "
            "WHERE scope = 'propositions' "
            f"AND status IN ({placeholders}) "
            "ORDER BY mtime",
            tuple(statuses),
        ).fetchall()
        for r in rows:
            if r["mtime"] <= cutoff:
                out.append({
                    "kind": "question",
                    "path": r["path"],
                    "title": r["title"],
                    "status": r["status"],
                    "age_days": int((now - r["mtime"]) // 86400),
                })
    return out

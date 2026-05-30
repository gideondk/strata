"""Shared logic for the two nudge surfaces — the Stop hook and the
commit-boundary PostToolUse hook. Keeping the draft-threshold and message
wording here means both surfaces phrase the offer identically and never drift.
"""
from __future__ import annotations


def should_draft(snap: dict) -> bool:
    """Whether the session has enough signal to stash a pre-filled draft
    instead of just the one-liner nudge. Thresholds aim for ~once per real
    work session, near-zero on tiny commits, never on pure noise.

    Triggers (any of):
      • 3+ commits in the session window
      • 1+ commit + 3+ uncommitted files (mid-flight feature work)
      • 8+ uncommitted files (substantial work-in-progress on a branch)
    """
    if not snap.get("available"):
        return False
    commits = len(snap.get("commits") or [])
    uncommitted = len(snap.get("uncommitted") or [])
    if commits >= 3:
        return True
    if commits >= 1 and uncommitted >= 3:
        return True
    return uncommitted >= 8


def stash_draft(snap: dict) -> bool:
    """Stash a pre-filled draft in plugin-data when the session crosses the
    signal threshold. Returns whether a draft was written. The vault is NOT
    touched — the user accepts via `/strata:save --apply-draft`. Never raises.
    """
    if not should_draft(snap):
        return False
    try:
        import draft_store
        import session_state
        from lib import branch_slug
        draft_store.stash_draft(
            topic=snap.get("suggested_topic") or "session-summary",
            branch_slug=branch_slug(snap.get("branch") or ""),
            body=session_state.draft_note_body(snap),
        )
        return True
    except Exception:
        return False


def _graph_staleness_suffix() -> str:
    try:
        import code_graph
        st = code_graph.graph_age_relative_to_head()
        if st and st.get("stale"):
            return (f"  Also: code graph is stale ({st['reason']}) — "
                    f"`/strata:graphify` to refresh.")
    except Exception:
        pass
    return ""


def _open_questions_suffix() -> str:
    """Batched, default-silent reminder of lingering open questions. Rides an
    already-firing nudge (a coarse breakpoint) instead of interrupting on its
    own — empty string when nothing has aged into the queue."""
    try:
        import inbox
        # Nudge only about open/contested questions — converging is trending
        # to a resolution, so nagging about it is noise.
        qs = inbox.aging_questions(statuses=("open", "contested"))
        if not qs:
            return ""
        n = len(qs)
        return (f"  📥 {n} question{'s' if n != 1 else ''} awaiting your "
                f"input — `/strata:dashboard` to weigh in.")
    except Exception:
        return ""


def build_message(snap: dict, *, drafted: bool, branch: str) -> str:
    """Compose the user-facing nudge. `drafted` toggles the apply-draft hint."""
    import session_state
    summary = session_state.stop_nudge_text(snap)
    extra = _graph_staleness_suffix() + _open_questions_suffix()
    if drafted:
        return (
            "💭 Strata: " + summary +
            "  A draft is ready — run `/strata:save --apply-draft` to save it "
            "as-is (or `--apply-draft --edit` to revise first)." + extra
        )
    if summary:
        return "💭 Strata: " + summary + extra
    return (
        f"💭 Strata: long session on `{branch}` without a saved note. "
        f"Consider `/strata:save` with a short topic + 3-5 bullets covering "
        f"what was done, decided, and left open." + extra
    )

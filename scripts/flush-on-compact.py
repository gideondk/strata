#!/usr/bin/env python3
"""PreCompact hook — drop an actionable recovery breadcrumb before compaction.

We don't summarise the conversation (no LLM in a hook, no chat content in a
synced vault) — that's `/strata:save`'s job. We fold in the content-free git
snapshot (branch, session commits, uncommitted edits, hot paths, suggested
topic) so the post-compaction session can reconstruct what was in flight.

Why a breadcrumb and not auto re-priming: neither PreCompact nor PostCompact
can inject context (verified), so the marker is the only recovery path.
"""
from __future__ import annotations

import contextlib
import json
import sys

import lib_loader  # noqa: F401
from lib import (
    author_initials,
    branch_slug,
    current_branch,
    ensure_dir,
    is_git_repo,
    pr_context_dir,
    stamp_minute,
    write_text,
)


def _trigger() -> str:
    """PreCompact stdin carries a `trigger` of "manual" or "auto". Best-effort
    — absent or malformed input just yields "unknown"."""
    with contextlib.suppress(Exception):
        data = json.load(sys.stdin)
        if isinstance(data, dict):
            return str(data.get("trigger") or "unknown")
    return "unknown"


def _state_section() -> str:
    """Render the content-free session snapshot as markdown bullets. Empty
    string if nothing useful is available (not a git repo, no activity)."""
    try:
        import session_state
        snap = session_state.snapshot()
    except Exception:
        return ""
    if not snap.get("available"):
        return ""

    lines: list[str] = []
    commits = snap.get("commits") or []
    uncommitted = snap.get("uncommitted") or []
    hot = snap.get("hot_paths") or []
    topic = snap.get("suggested_topic") or ""

    if commits:
        lines.append(f"- **{len(commits)} commit(s) this session:**")
        for c in commits[:5]:
            subj = (c.get("subject") or c.get("message") or "").strip()
            sha = (c.get("sha") or c.get("hash") or "").strip()
            lines.append(f"  - `{sha}` {subj}" if sha else f"  - {subj}")
    if uncommitted:
        lines.append(f"- **{len(uncommitted)} uncommitted edit(s):** "
                     + ", ".join(f"`{f.get('path', '?')}`"
                                 for f in uncommitted[:6]))
    if hot:
        lines.append("- **Hot paths:** "
                     + ", ".join(f"`{p}`" for p in hot[:5]))
    if not lines:
        return ""

    recover = (f"\n## Recover\n\nAsk Claude to `/strata:save --topic {topic}`"
               if topic else
               "\n## Recover\n\nAsk Claude to `/strata:save` the in-flight work")
    return "\n## In flight at compaction\n\n" + "\n".join(lines) + "\n" + recover


def main() -> int:
    if not is_git_repo():
        return 0

    trigger = _trigger()
    slug = branch_slug(current_branch())
    dir_ = pr_context_dir(slug)
    ensure_dir(dir_)

    fname = f"{stamp_minute()}--{author_initials()}--compaction-marker.md"
    path = dir_ / fname
    body = (
        "---\n"
        f"branch: {current_branch()}\n"
        "kind: compaction-marker\n"
        f"author: {author_initials()}\n"
        f"created: {stamp_minute()}\n"
        f"trigger: {trigger}\n"
        "---\n\n"
        "# Compaction marker\n\n"
        f"Claude Code compacted the session here ({trigger}). The conversation\n"
        "up to this point is no longer in working context. The session state\n"
        "below is reconstructed from git — use it to save what mattered.\n"
        + _state_section()
    )
    write_text(path, body)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Regenerate docs/memory/INDEX.md from the on-disk content.

INDEX.md is a quick-scan summary used by SessionStart and by `/strata:find`
as a starting point. It's regenerated on every save/decide/init and is safe to
clobber.
"""
from __future__ import annotations

import os
import sys

import lib_loader  # noqa: F401
from lib import first_heading, info, memory_dir, memory_display


def _vinfo(msg: str) -> None:
    """Index-regeneration chatter (fts5 counts, regenerated files) — internal
    side-effect noise that clutters the transcript on every save/decide. Silent
    unless STRATA_VERBOSE is set; the caller's one-line receipt is the signal."""
    if os.environ.get("STRATA_VERBOSE"):
        info(msg)


def _section(title: str, items: list[str]) -> str:
    if not items:
        return ""
    return f"## {title}\n\n" + "\n".join(items) + "\n\n"


def _list_md(subdir: str, *, descending: bool = False,
             exclude: set[str] | None = None) -> list[str]:
    mem = memory_dir()
    d = mem / subdir
    if not d.exists():
        return []
    excl = exclude or set()
    files = [p for p in d.glob("*.md")
             if p.name not in ("README.md", "INDEX.md")
             and p.relative_to(mem).as_posix() not in excl]
    files.sort(reverse=descending)
    out = []
    for f in files:
        title = first_heading(f) or f.stem
        rel = f.relative_to(mem).as_posix()
        out.append(f"- [`{rel}`]({rel}) — {title}")
    return out


def _pr_contexts() -> list[str]:
    mem = memory_dir()
    d = mem / "pr-context"
    if not d.exists():
        return []
    out = []
    for sub in sorted(p for p in d.iterdir() if p.is_dir()):
        notes = sorted(sub.glob("*.md"))
        if not notes:
            continue
        latest = notes[-1]
        rel = latest.relative_to(mem).as_posix()
        out.append(
            f"- **{sub.name}** — {len(notes)} note(s), latest: "
            f"[`{rel}`]({rel})"
        )
    return out


def regenerate_index() -> None:
    mem = memory_dir()
    if not mem.exists():
        info("memory dir missing; nothing to index")
        return

    # Reindex FTS5 first so downstream queries (drift, hot files, ADR
    # linkage) see fresh state.
    try:
        import db as _db
        counts = _db.reindex(force=False)
        _vinfo(
            f"fts5: indexed={counts['indexed']} "
            f"removed={counts['removed']} unchanged={counts['unchanged']}"
        )
    except Exception as e:
        info(f"fts5 reindex skipped: {e}")

    # INDEX.md is now the dashboard — full state at a glance. Renders in
    # Obsidian, syncs with the vault, no separate UI surface.
    try:
        import dashboard
        body = dashboard.build_dashboard()
    except Exception as e:
        info(f"dashboard build failed, falling back to stub: {e}")
        body = ("# Memory Index\n\n_dashboard generation failed; "
                "vault is intact._\n")

    (mem / "INDEX.md").write_text(body + "\n", encoding="utf-8")
    _vinfo(f"regenerated {memory_display()}INDEX.md")

    # index.html — the richer, glanceable team surface (open it via file://).
    # Written atomically (tmp + os.replace) so a browser reload never catches a
    # half-written file. Best-effort: a render failure must not break the write.
    try:
        import os

        import dashboard as _dash
        html_body = _dash.build_dashboard_html()
        tmp = mem / "index.html.tmp"
        tmp.write_text(html_body, encoding="utf-8")
        os.replace(tmp, mem / "index.html")
        _vinfo(f"regenerated {memory_display()}index.html")
    except Exception as e:
        info(f"index.html generation skipped: {e}")


def main() -> int:
    regenerate_index()
    return 0


if __name__ == "__main__":
    sys.exit(main())

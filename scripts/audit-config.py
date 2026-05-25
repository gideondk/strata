#!/usr/bin/env python3
"""Audit project Claude Code config (CLAUDE.md, .claude/settings.json,
.claude/skills/, .claude/agents/, .claudeignore) for drift. Read-only;
flags items older than --stale-days (default 180)."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import lib_loader  # noqa: F401
from lib import project_dir

STALE_DAYS_DEFAULT = 180


def _age_days(p: Path) -> int:
    return int((time.time() - p.stat().st_mtime) / 86400)


def _check_file(pd: Path, rel: str, stale_days: int,
                lines: list[str]) -> int:
    """Append a status line for `rel`. Return 1 if stale or 0 otherwise."""
    p = pd / rel
    if not p.exists():
        lines.append(f"- `{rel}` — _(not present)_")
        return 0
    age = _age_days(p)
    size = p.stat().st_size
    marker = " 🔴 STALE" if age > stale_days else ""
    lines.append(f"- `{rel}` — {size:,} bytes, last touched {age}d ago{marker}")
    return 1 if age > stale_days else 0


def _check_dir(pd: Path, rel: str, stale_days: int,
               lines: list[str]) -> int:
    """Check a directory of skills or agents. Return count of stale items."""
    d = pd / rel
    lines.append(f"### `{rel}`")
    if not d.exists():
        lines.append("- _(not present)_")
        return 0
    entries = sorted([p for p in d.iterdir() if p.is_dir()])
    if not entries:
        lines.append("- _(empty)_")
        return 0
    stale_count = 0
    lines.append(f"- {len(entries)} item(s)")
    for entry in entries:
        skill_md = entry / "SKILL.md"
        agent_md = entry / "AGENT.md"
        marker_file = skill_md if skill_md.exists() else (
            agent_md if agent_md.exists() else entry
        )
        try:
            age = _age_days(marker_file)
        except OSError:
            continue
        stale = age > stale_days
        marker = " 🔴 STALE" if stale else ""
        lines.append(f"  - `{entry.name}/` — {age}d{marker}")
        if stale:
            stale_count += 1
    return stale_count


def _parse_settings(pd: Path, lines: list[str]) -> None:
    settings = pd / ".claude" / "settings.json"
    if not settings.exists():
        return
    try:
        data = json.loads(settings.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        lines.append(f"  - _settings.json unreadable: {e}_")
        return
    enabled = data.get("enabledPlugins") or []
    hooks = data.get("hooks") or {}
    permissions = data.get("permissions") or {}
    lines.append(f"  - enabled plugins: {len(enabled)}")
    if enabled:
        for p in enabled[:5]:
            lines.append(f"    - {p}")
    lines.append(f"  - user-defined hook events: {len(hooks)}")
    if permissions:
        lines.append(f"  - permission rules: {len(permissions)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stale-days", type=int, default=STALE_DAYS_DEFAULT,
                    help="Threshold for flagging an item as stale.")
    args = ap.parse_args()

    pd = project_dir()
    if pd is None:
        print("[strata] not in a project (no CLAUDE_PROJECT_DIR / git repo)",
              file=sys.stderr)
        return 2

    lines: list[str] = [
        "# Claude Code config audit",
        f"_project: `{pd}`_",
        f"_stale threshold: {args.stale_days} days_",
        "",
        "## Top-level files",
    ]
    stale_total = 0
    stale_total += _check_file(pd, "CLAUDE.md", args.stale_days, lines)
    stale_total += _check_file(pd, ".claude/settings.json", args.stale_days,
                                lines)
    _parse_settings(pd, lines)
    stale_total += _check_file(pd, ".claudeignore", args.stale_days, lines)
    lines.append("")

    stale_total += _check_dir(pd, ".claude/skills", args.stale_days, lines)
    lines.append("")
    stale_total += _check_dir(pd, ".claude/agents", args.stale_days, lines)
    lines.append("")

    lines.append("## Summary")
    if stale_total == 0:
        lines.append("_All configs are within the review window — good._")
    else:
        lines.append(
            f"_{stale_total} stale item(s). Per Anthropic's guidance, do a "
            "meaningful configuration review every 3-6 months - instructions "
            "optimized for older models can work against newer ones._"
        )

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())

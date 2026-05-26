"""SessionStart primer formatting — legend, economy, by-file index.

Strata-flavoured adaptation of the structured-context-summary pattern.
We stay markdown-native: IDs are note paths (not numeric), types come
from each note's `kind:` frontmatter, and file grouping is built from
the `source_file:` field (which may be a string or a list).

The three additions over the previous primer:
- a one-line `Legend` so readers can decode the icons cold,
- a one-line `Context economy` so the value of trusting the primer
  is visible (skim vs full-read cost),
- a `Files with recent context` section that inverts notes → source
  file so users landing in `Foo.cs` immediately see which notes
  touched it.

All vault data comes from the SQLite db (`db.py`). `reindex()` is the
authority for the source_file inverse index — this module just
formats what's already there. That keeps SessionStart fast on warm
vaults (one tiny query each) and means the by-file section reflects
exactly what the rest of Strata sees.
"""
from __future__ import annotations

from pathlib import Path

# Icon set covers Strata's actual frontmatter `kind:` values plus the
# session-flavour tags that show up in note titles. Anything unknown
# gets the generic 📄 — better to render an unknown note than to
# silently drop it.
KIND_ICONS: dict[str, str] = {
    "session":     "🎯",
    "decision":    "⚖️",
    "adr":         "⚖️",
    "domain":      "📚",
    "procedural":  "📝",
    "handoff":     "🎓",
    "lesson":      "🎓",
    "proposition": "🌱",
    "bugfix":      "🔴",
    "feature":     "🟣",
    "refactor":    "🔄",
    "change":      "✅",
    "discovery":   "🔵",
}


def kind_icon(kind: str | None) -> str:
    if not kind:
        return "📄"
    return KIND_ICONS.get(str(kind).strip().lower(), "📄")


def legend_line() -> str:
    return (
        "Legend: "
        "🎯 session  ⚖️ decision  📚 domain  "
        "📝 procedural  🎓 lesson  🌱 proposition"
    )


# ---------- internal helpers ------------------------------------------


# Used to derive a kind icon when a note's frontmatter doesn't declare
# `kind:` — the scope dir is the next best signal.
_SCOPE_TO_KIND: dict[str, str] = {
    "decisions":    "decision",
    "domain":       "domain",
    "pr-context":   "session",
    "lessons":      "lesson",
    "procedural":   "procedural",
    "propositions": "proposition",
}


def _scope_kind(scope: str | None) -> str:
    """Best-guess kind from scope when frontmatter doesn't declare one."""
    if not scope:
        return ""
    return _SCOPE_TO_KIND.get(scope, "")


def _approx_tokens(n_bytes: int) -> int:
    """Rough chars-to-tokens. 4 bytes/token is the standard English
    heuristic; markdown is slightly denser but the variance is
    rounding-error vs. the primer's other estimates."""
    return max(1, n_bytes // 4)


# ---------- public formatters -----------------------------------------


def compute_economy(mem_dir: Path | None = None) -> dict:
    """Return primer-level token economics from the db.

    Skim cost ≈ what Claude reads when the primer summarises a note
    (frontmatter + heading + a sentence or two — modelled as 500 bytes
    per note, capped at file size). Full cost is the sum of all
    indexed file sizes. Savings = body content Claude can avoid
    pulling in when the primer + a targeted Read suffice.

    `mem_dir` is accepted for API compatibility but ignored — the db
    is the source of truth. The argument stays in the signature so
    callers can keep passing it for clarity.
    """
    del mem_dir
    try:
        import db
        summary = db.vault_summary()
        # Per-note skim cap requires the count + total; for the cap,
        # we model skim as min(500, avg_per_note) * notes. Cheaper than
        # a second SQL pass and within rounding error.
        notes = summary["notes"]
        full_bytes = summary["bytes"]
    except Exception:
        return {"notes": 0, "skim_tokens": 0, "full_tokens": 0,
                "savings_pct": 0}

    if not notes or not full_bytes:
        return {"notes": notes, "skim_tokens": 0, "full_tokens": 0,
                "savings_pct": 0}

    avg = full_bytes // notes if notes else 0
    skim_bytes = notes * min(500, avg)
    skim = _approx_tokens(skim_bytes)
    full = _approx_tokens(full_bytes)
    savings = round(100 * (1 - skim / full)) if full else 0
    return {
        "notes": notes,
        "skim_tokens": skim,
        "full_tokens": full,
        "savings_pct": savings,
    }


def format_economy(econ: dict) -> str:
    if not econ.get("notes"):
        return ""
    return (
        f"Context economy: {econ['notes']} notes • "
        f"skim {econ['skim_tokens']:,}t • "
        f"full read {econ['full_tokens']:,}t • "
        f"{econ['savings_pct']}% savings"
    )


def index_by_source_file(
    mem_dir: Path | None = None,
    limit: int = 6,
) -> list[dict]:
    """Inverse index: top source-code files → notes that reference them.

    Returns the db's `source_file_index` shape: each entry is a dict
    `{source_file, note_count, notes: [{path, title, kind, scope}, ...]}`.
    Ranking is by note count, then most-recent mtime. Capped at
    `limit` files (6 by default) so the primer stays compact.

    `mem_dir` is accepted for API compatibility but ignored — the db
    is the source of truth.
    """
    del mem_dir
    try:
        import db
        return db.source_file_index(limit=limit)
    except Exception:
        return []


def format_files_section(
    mem_dir: Path,
    file_index: list[dict],
    notes_per_file: int = 3,
) -> str:
    """Render the by-file section. Each source file gets a bullet with
    its most-recent note refs nested below (kind icon + relative path
    + title).

    `mem_dir` is currently unused but kept in the signature so callers
    don't need to know whether the index is db- or filesystem-backed.
    """
    del mem_dir
    if not file_index:
        return ""

    lines: list[str] = ["### Files with recent context", ""]
    for entry in file_index:
        src_file = entry["source_file"]
        notes = entry["notes"][:notes_per_file]
        lines.append(f"- `{src_file}`")
        for n in notes:
            kind = n.get("kind") or _scope_kind(n.get("scope"))
            title = n.get("title") or Path(n["path"]).stem
            lines.append(
                f"  - {kind_icon(str(kind))} "
                f"`{n['path']}` — {title}"
            )
    return "\n".join(lines)

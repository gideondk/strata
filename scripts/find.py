#!/usr/bin/env python3
"""Search the Strata vault for a query.

Pure-Python full-text walk — no SQLite, no FTS engine, no third-party libs.
This is the literal-string fallback; for ranked or semantic queries from
Claude, prefer the `recall` MCP tool which fuses FTS5 and semantic search.

Output is structured for Claude to read:
    PATH:LINE  <one-line excerpt>
grouped by file, ranked by hit count.
"""
from __future__ import annotations

import argparse
import re
import sys

import lib_loader  # noqa: F401
from lib import first_heading, memory_dir

MAX_FILES = 20
MAX_HITS_PER_FILE = 5
EXCERPT_CHARS = 140


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="+", help="search terms (AND across terms)")
    ap.add_argument("--scope", default="all",
                    choices=["all", "decisions", "lessons", "domain",
                             "pr-context"])
    ap.add_argument("--case-sensitive", action="store_true")
    args = ap.parse_args()

    mem = memory_dir()
    if not mem.exists():
        print("[strata] no memory directory", file=sys.stderr)
        return 1

    root = mem if args.scope == "all" else mem / args.scope
    if not root.exists():
        print(f"[strata] scope not found: {args.scope}", file=sys.stderr)
        return 1

    flags = 0 if args.case_sensitive else re.IGNORECASE
    patterns = [re.compile(re.escape(t), flags) for t in args.query]

    hits_by_file: dict = {}
    for path in root.rglob("*.md"):
        if path.name in ("README.md", "INDEX.md"):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        # AND: every pattern must occur somewhere in the file
        if not all(p.search(text) for p in patterns):
            continue

        lines = text.splitlines()
        per_file: list[tuple[int, str]] = []
        for ln, line in enumerate(lines, 1):
            if any(p.search(line) for p in patterns):
                snippet = line.strip()
                if len(snippet) > EXCERPT_CHARS:
                    snippet = snippet[: EXCERPT_CHARS - 1] + "…"
                per_file.append((ln, snippet))
                if len(per_file) >= MAX_HITS_PER_FILE:
                    break
        if per_file:
            hits_by_file[path] = per_file

    if not hits_by_file:
        print(f"[strata] no matches for: {' '.join(args.query)}")
        return 0

    ranked = sorted(
        hits_by_file.items(),
        key=lambda kv: (-len(kv[1]), kv[0].as_posix()),
    )[:MAX_FILES]

    for path, lines in ranked:
        rel = path.relative_to(mem).as_posix()
        title = first_heading(path) or path.stem
        print(f"\n### `{rel}` — {title}  ({len(lines)} hit(s))")
        for ln, snippet in lines:
            print(f"  L{ln}: {snippet}")

    total = sum(len(v) for v in hits_by_file.values())
    shown = sum(len(v) for _, v in ranked)
    if shown < total or len(hits_by_file) > MAX_FILES:
        print(
            f"\n[strata] showing {shown}/{total} hits across "
            f"{min(len(hits_by_file), MAX_FILES)}/{len(hits_by_file)} files"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

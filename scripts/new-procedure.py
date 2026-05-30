#!/usr/bin/env python3
"""Create a procedural note. Body on stdin; frontmatter built from args."""
from __future__ import annotations

import argparse
import sys

import lib_loader  # noqa: F401
from lib import (
    author_name,
    ensure_dir,
    memory_dir,
    origin_branch,
    safe_slug,
    today,
    write_text,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True)
    ap.add_argument("--source-file", default=None,
                    help="Project-relative path the procedure was extracted from.")
    args = ap.parse_args()

    body = sys.stdin.read().strip()
    if not body:
        print("[strata] error: empty body on stdin", file=sys.stderr)
        return 2

    slug = safe_slug(args.title)
    dir_ = memory_dir() / "procedural"
    ensure_dir(dir_)
    path = dir_ / f"{slug}.md"
    if path.exists():
        i = 2
        while (dir_ / f"{slug}-{i}.md").exists():
            i += 1
        path = dir_ / f"{slug}-{i}.md"

    fm = ["---",
          f"title: {args.title}",
          "kind: procedure",
          "status: stable",
          f"author: {author_name()}",
          f"created: {today()}"]
    ob = origin_branch()
    if ob:
        fm.append(f"branch: {ob}")
    if args.source_file:
        fm.append(f"source_file: {args.source_file}")
    fm.append("---\n\n")

    write_text(path, "\n".join(fm) + body + "\n")
    print(f"[strata] procedure created: {path}")

    import importlib.util
    import os
    spec = importlib.util.spec_from_file_location(
        "refresh_index",
        os.path.join(os.path.dirname(__file__), "refresh-index.py"),
    )
    if spec and spec.loader:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.regenerate_index()
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Create / update a proposition note. Captures open questions and
contested positions before they settle into decisions or lessons.

Lifecycle in frontmatter `status:`
  open                    initial state
  contested               actively debated; multiple positions
  converging              one position is gaining; no decision yet
  settled-as-decision     → forward link `settled_as: decisions/<adr>.md`
  refuted-as-lesson       → forward link `refuted_as: lessons/<note>.md`
"""
from __future__ import annotations

import argparse
import sys

import frontmatter

import lib_loader  # noqa: F401
from lib import (
    author_name,
    ensure_dir,
    memory_dir,
    origin_branch,
    safe_resolve,
    safe_slug,
    today,
    write_text,
)

VALID_STATUS = {"open", "contested", "converging",
                "settled-as-decision", "refuted-as-lesson"}


def _refresh_index() -> None:
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", default=None,
                    help="Short phrase stating the open question. "
                         "Required for create; ignored for --update.")
    ap.add_argument("--status", default="open", choices=sorted(VALID_STATUS))
    ap.add_argument("--update", default=None,
                    help="Vault-relative path of an existing proposition "
                         "to update (bumps status / adds settled/refuted link).")
    ap.add_argument("--settled-as", default=None,
                    help="ADR path (e.g. decisions/2026-05-25-foo.md) that "
                         "settled this proposition. Sets status accordingly.")
    ap.add_argument("--refuted-as", default=None,
                    help="Lesson path (e.g. lessons/2026-05-25-foo.md) that "
                         "refuted this proposition.")
    args = ap.parse_args()

    mem = memory_dir()
    body = sys.stdin.read().strip() if not sys.stdin.isatty() else ""

    if args.update:
        # Mutate an existing proposition's frontmatter
        try:
            path = safe_resolve(args.update, mem)
        except Exception as e:
            print(f"[strata] error: {e}", file=sys.stderr)
            return 2
        if not path.exists():
            print(f"[strata] proposition not found: {args.update}",
                  file=sys.stderr)
            return 2
        post = frontmatter.load(path)
        if args.settled_as:
            post.metadata["status"] = "settled-as-decision"
            post.metadata["settled_as"] = args.settled_as
            post.metadata["settled_at"] = today()
        elif args.refuted_as:
            post.metadata["status"] = "refuted-as-lesson"
            post.metadata["refuted_as"] = args.refuted_as
            post.metadata["refuted_at"] = today()
        else:
            post.metadata["status"] = args.status
        post.metadata["updated"] = today()
        if body:
            post.content = body
        write_text(path, frontmatter.dumps(post) + "\n")
        print(f"[strata] proposition updated: {args.update} "
              f"→ status={post.metadata['status']}")
        _refresh_index()
        return 0

    # Create new proposition — title required
    if not args.title:
        print("[strata] error: --title required when creating a proposition",
              file=sys.stderr)
        return 2
    if not body:
        body = (f"# {args.title}\n\n"
                "## What we're trying to figure out\n\n"
                "## Positions on the table\n\n"
                "- Position A: ...\n"
                "- Position B: ...\n\n"
                "## What evidence would settle this\n\n"
                "- ...\n")

    slug = safe_slug(args.title)
    dir_ = mem / "propositions"
    ensure_dir(dir_)
    path = dir_ / f"{today()}-{slug}.md"
    if path.exists():
        i = 2
        while (dir_ / f"{today()}-{slug}-{i}.md").exists():
            i += 1
        path = dir_ / f"{today()}-{slug}-{i}.md"

    fm_meta = {
        "title": args.title,
        "status": args.status,
        "author": author_name(),
        "created": today(),
    }
    ob = origin_branch()
    if ob:
        fm_meta["branch"] = ob
    post = frontmatter.Post(content=body.lstrip(), **fm_meta)
    write_text(path, frontmatter.dumps(post) + "\n")
    print(f"[strata] proposition created: {path.relative_to(mem)}")
    _refresh_index()
    return 0


if __name__ == "__main__":
    sys.exit(main())

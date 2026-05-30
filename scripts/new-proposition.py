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

# Stances that mean someone is actively contesting → bump open → contested.
VALID_STANCE = ("for", "against", "alternative", "refine")
_CONTESTING = frozenset({"against", "alternative"})

_DEBATE_HEADER = "## Debate log"


def _append_position(content: str, stance: str, author: str, date: str,
                     prose: str) -> str:
    """Append one attributed, dated position as an H3 entry under a
    '## Debate log' section. Append-only — never rewrites prior positions, so
    an earlier draft can't be silently overwritten before convergence."""
    entry = f"### {stance} — {author}, {date}\n\n{prose.strip()}\n"
    base = content.rstrip()
    # Line-anchored, not substring — a '## Debate log' inside a code fence or
    # quote in the body must not be mistaken for the real section header.
    has_section = any(line.strip() == _DEBATE_HEADER
                      for line in content.splitlines())
    if has_section:
        return f"{base}\n\n{entry}"
    return f"{base}\n\n{_DEBATE_HEADER}\n\n{entry}"


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
    ap.add_argument("--position", action="store_true",
                    help="Append a position to an existing proposition's "
                         "'## Debate log' (requires --update). Prose on stdin; "
                         "categorise with --stance. Append-only — never "
                         "rewrites prior positions. An against/alternative "
                         "stance bumps an open proposition to contested.")
    ap.add_argument("--stance", default="for", choices=VALID_STANCE,
                    help="Position stance (with --position). for | against | "
                         "alternative | refine.")
    args = ap.parse_args()

    # --position is an append-to-an-existing-note action; guard the foot-guns
    # before any path runs (else it would silently create a new note, or drop
    # a co-passed settle/refute).
    if args.position:
        if not args.update:
            print("[strata] error: --position requires --update <path>",
                  file=sys.stderr)
            return 2
        if args.settled_as or args.refuted_as:
            print("[strata] error: --position can't be combined with "
                  "--settled-as/--refuted-as. Add the position first, then "
                  "promote in a separate call.", file=sys.stderr)
            return 2

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

        # Append-a-position mode: add to the debate log, never clobber.
        if args.position:
            if not body:
                print("[strata] error: --position needs the position prose on "
                      "stdin", file=sys.stderr)
                return 2
            post.content = _append_position(
                post.content, args.stance, author_name(), today(), body)
            cur = str(post.metadata.get("status") or "open")
            if args.stance in _CONTESTING and cur == "open":
                cur = "contested"
            post.metadata["status"] = cur  # always present, even if note had none
            post.metadata["updated"] = today()
            write_text(path, frontmatter.dumps(post) + "\n")
            print(f"[strata] position ({args.stance}) added to {args.update} "
                  f"→ status={post.metadata['status']}")
            _refresh_index()
            return 0

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

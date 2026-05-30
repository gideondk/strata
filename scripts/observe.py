#!/usr/bin/env python3
"""Auto-capture a grounded OBSERVATION into the staging lane (`status: auto`).

This is the safe autonomous-write lane (see the autonomy-line ADR): an agent
may write a low-stakes, grounded, reversible observation WITHOUT human
confirmation — because markdown+git make it trivially revertible and it never
ratifies a decision. The note lands in pr-context with `status: auto`,
announces itself, and sits in the review queue (`/strata:dashboard`) until a
human keeps it (edit) or discards it (`/strata:forget`).

HARD GUARDRAILS (structural, not advisory):
  - **Observation-only.** This writes to pr-context, never to
    decisions/domain/propositions. Decisions are human-ratified — that's the
    moat; an agent cannot reach those scopes through this script at all.
  - **Grounding required.** Refuses without `--source-file` or `--commit`, so an
    auto-note is always anchored to a verifiable artifact (Copilot-Memory's
    "grounding, not confidence" rule).
"""
from __future__ import annotations

import argparse
import sys

import frontmatter

import lib_loader  # noqa: F401
from lib import (
    author_initials,
    author_name,
    branch_slug,
    current_branch,
    ensure_dir,
    is_git_repo,
    origin_branch,
    pr_context_dir,
    safe_slug,
    stamp_minute,
    write_text,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", required=True,
                    help="Short topic — used in the filename.")
    ap.add_argument("--source-file", action="append", default=[],
                    help="Project-relative path(s) this observation is grounded "
                         "in. Repeatable / comma-joined. Required unless "
                         "--commit is given.")
    ap.add_argument("--commit", default=None,
                    help="Commit sha this observation is grounded in. Required "
                         "unless --source-file is given.")
    ap.add_argument("--project-dir", default=None,
                    help="Override the project root (same as STRATA_PROJECT_DIR).")
    args = ap.parse_args()

    if args.project_dir:
        import os
        os.environ["STRATA_PROJECT_DIR"] = args.project_dir

    expanded: list[str] = []
    for entry in args.source_file:
        for piece in (s.strip() for s in entry.split(",")):
            if piece and piece not in expanded:
                expanded.append(piece)
    args.source_file = expanded

    # GROUNDING GUARDRAIL — an auto-write must be anchored to a real artifact.
    if not args.source_file and not args.commit:
        print("[strata] error: an auto-observation must be grounded — pass "
              "--source-file <path> and/or --commit <sha>", file=sys.stderr)
        return 2

    body = sys.stdin.read().strip()
    if not body:
        print("[strata] error: empty observation on stdin", file=sys.stderr)
        return 2

    slug = branch_slug(current_branch()) if is_git_repo() else "_no-branch"
    init = author_initials()
    when = stamp_minute()
    dir_ = pr_context_dir(slug)
    ensure_dir(dir_)
    path = dir_ / f"{when}--{safe_slug(init)}--{safe_slug(args.topic)}.md"

    # Build frontmatter via the YAML lib (NOT hand-built strings): this quotes
    # scalars so a colon-bearing topic ("fix: x") can't break parsing into
    # status=None, and a newline in --topic can't inject a second `status:` key.
    # Both would silently defeat the recall quarantine.
    meta: dict = {
        "kind": "observation",
        "status": "auto",          # quarantine tier — awaits human review
        "source": "git-derived",   # provenance: outranked by user-stated notes
        "author": author_name(),
        "author_initials": init,
        "topic": args.topic,
        "created": when,
    }
    ob = origin_branch()
    if ob:
        meta["branch"] = ob
    if args.commit:
        meta["grounded_in"] = args.commit
    if args.source_file:
        meta["source_file"] = (
            args.source_file if len(args.source_file) > 1 else args.source_file[0]
        )
    post = frontmatter.Post(content=body, **meta)
    write_text(path, frontmatter.dumps(post) + "\n")
    print(f"[strata] auto-captured observation (status: auto) → {path}")
    print("[strata] review it at /strata:dashboard — keep by editing, or "
          "/strata:forget to discard")

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

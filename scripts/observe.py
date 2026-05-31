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
import contextlib
import re
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

# Auto-discard floor: an observation that lexically overlaps an existing staged
# one above this Jaccard threshold is dropped instead of queued, so the
# quarantine lane can't fill with redundant re-captures (the "third bucket"
# beside keep/discard). Deterministic + offline — no embeddings dependency.
_DEDUP_JACCARD = 0.85
_DEDUP_MIN_TOKENS = 5


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _is_near_duplicate(body: str, dir_) -> bool:
    """True if `body` overlaps an existing `status: auto` observation in `dir_`
    above the Jaccard floor. Best-effort: any read/parse failure → not a dup."""
    new = _tokens(body)
    if len(new) < _DEDUP_MIN_TOKENS:
        return False  # too short to judge similarity reliably
    with contextlib.suppress(Exception):
        for f in dir_.glob("*.md"):
            with contextlib.suppress(Exception):
                post = frontmatter.load(f)
                if post.metadata.get("status") != "auto":
                    continue
                other = _tokens(post.content)
                if not other:
                    continue
                if len(new & other) / len(new | other) >= _DEDUP_JACCARD:
                    return True
    return False


def capture(topic: str, body: str, *, source_file: list[str] | None = None,
            commit: str | None = None) -> tuple[int, str]:
    """Write a grounded staged observation. The single guarded code path —
    shared by the observe CLI and `save-note.py --observe`, so the grounding +
    quarantine guardrails can't diverge. Returns (exit_code, message).

    HARD GUARDRAILS: grounding required (source_file or commit), non-empty body,
    and observation-only (this only ever writes pr-context with status:auto;
    no scope parameter exists, so it can never reach decisions/domain)."""
    expanded: list[str] = []
    for entry in (source_file or []):
        for piece in (s.strip() for s in entry.split(",")):
            if piece and piece not in expanded:
                expanded.append(piece)

    if not expanded and not commit:
        return 2, ("[strata] error: an auto-observation must be grounded — pass "
                   "--source-file <path> and/or --commit <sha>")
    body = (body or "").strip()
    if not body:
        return 2, "[strata] error: empty observation on stdin"

    slug = branch_slug(current_branch()) if is_git_repo() else "_no-branch"
    init = author_initials()
    when = stamp_minute()
    dir_ = pr_context_dir(slug)
    ensure_dir(dir_)

    # Auto-discard floor: don't queue a near-duplicate of an existing staged
    # observation — that just turns the quarantine into a redundant backlog.
    if _is_near_duplicate(body, dir_):
        return 0, ("[strata] skipped: near-duplicate of an existing staged "
                   "observation — not captured")

    path = dir_ / f"{when}--{safe_slug(init)}--{safe_slug(topic)}.md"

    # Build frontmatter via the YAML lib (NOT hand-built strings): this quotes
    # scalars so a colon-bearing topic ("fix: x") can't break parsing into
    # status=None, and a newline in topic can't inject a second `status:` key.
    # Both would silently defeat the recall quarantine.
    meta: dict = {
        "kind": "observation",
        "status": "auto",          # quarantine tier — awaits human review
        "source": "git-derived",   # provenance: outranked by user-stated notes
        "author": author_name(),
        "author_initials": init,
        "topic": topic,
        "created": when,
    }
    ob = origin_branch()
    if ob:
        meta["branch"] = ob
    if commit:
        meta["grounded_in"] = commit
    if expanded:
        meta["source_file"] = expanded if len(expanded) > 1 else expanded[0]
    post = frontmatter.Post(content=body, **meta)
    composed = frontmatter.dumps(post)
    # Secret/PII pre-step on the autonomous lane too (warn-only; the agent
    # writes these without a human in the loop, so it's the path most likely to
    # persist a secret unreviewed). Scans the composed doc so a secret in the
    # topic is caught, not just the body. Best-effort; never blocks.
    with contextlib.suppress(Exception):
        import lint_check
        lint_check.emit_warnings(composed, label="observation")
    write_text(path, composed + "\n")

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
    return 0, f"[strata] auto-captured observation (status: auto) → {path}"


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

    rc, msg = capture(args.topic, sys.stdin.read(),
                      source_file=args.source_file, commit=args.commit)
    print(msg, file=sys.stderr if rc else sys.stdout)
    if rc == 0 and msg.startswith("[strata] auto-captured"):
        print("[strata] review it at /strata:dashboard — keep by editing, or "
              "/strata:forget to discard")
    return rc


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Walk aging pr-context branch dirs, promote durable notes into lessons/.

Rule-based, no LLM. A pr-context note becomes a lesson when:
  - branch dir mtime > --age-days old (default 60)
  - note kind in {handoff, decision-draft, review}
  - note has source_file frontmatter OR is referenced by ≥1 other note

Otherwise it stays where it is.

Dry-run by default. Pass --apply to perform the moves + index refresh.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

import frontmatter

import lib_loader  # noqa: F401
from lib import lessons_dir, memory_dir, safe_slug, today, write_text

PROMOTE_KINDS = {"handoff", "decision-draft", "review"}


def _scan(age_days: int) -> list[tuple[Path, dict[str, Any], str]]:
    """Return (src_path, meta, reason) for each promotable note."""
    mem = memory_dir()
    pr_root = mem / "pr-context"
    if not pr_root.is_dir():
        return []
    cutoff = time.time() - age_days * 86400
    out: list[tuple[Path, dict[str, Any], str]] = []
    for branch_dir in sorted(pr_root.iterdir()):
        if not branch_dir.is_dir():
            continue
        try:
            mtime = branch_dir.stat().st_mtime
        except OSError:
            continue
        if mtime >= cutoff:
            continue
        for f in sorted(branch_dir.glob("*.md")):
            if f.name in ("README.md", "INDEX.md"):
                continue
            try:
                post = frontmatter.load(f)
            except Exception:
                continue
            kind = str(post.metadata.get("kind") or "").lower()
            if kind not in PROMOTE_KINDS:
                continue
            reason_bits: list[str] = []
            if kind in PROMOTE_KINDS:
                reason_bits.append(f"kind={kind}")
            reason_bits.append(f"branch dir {int((time.time()-mtime)//86400)}d old")
            out.append((f, dict(post.metadata), ", ".join(reason_bits)))
    return out


def _target(meta: dict[str, Any], src: Path) -> Path:
    topic = meta.get("topic") or src.stem
    created = str(meta.get("created") or "")
    date = created[:10] if len(created) >= 10 else today()
    if not (len(date) == 10 and date[4] == "-" and date[7] == "-"):
        date = today()
    return lessons_dir() / f"{date}-{safe_slug(topic)}.md"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--age-days", type=int, default=60,
                    help="pr-context branch dirs older than this are "
                         "scanned for promotion (default 60).")
    ap.add_argument("--apply", action="store_true",
                    help="Perform moves. Default is dry-run.")
    args = ap.parse_args()

    matches = _scan(args.age_days)
    if not matches:
        print(f"[strata] nothing to consolidate "
              f"(no pr-context dirs older than {args.age_days}d "
              "with promotable notes).")
        return 0

    plans: list[tuple[Path, Path, str]] = []
    for src, meta, reason in matches:
        tgt = _target(meta, src)
        i = 2
        while tgt.exists() or any(t == tgt for _, t, _ in plans):
            tgt = tgt.with_name(f"{tgt.stem}-{i}.md")
            i += 1
        plans.append((src, tgt, reason))

    verb = "Moving" if args.apply else "Would move"
    print(f"[strata] {len(plans)} note(s) to promote → lessons/")
    print()
    mem = memory_dir()
    for src, tgt, reason in plans:
        print(f"  {verb}:  {src.relative_to(mem)}")
        print(f"        →  {tgt.relative_to(mem)}   ({reason})")

    if not args.apply:
        print()
        print("[strata] dry-run only. Re-run with --apply to perform.")
        return 0

    lessons_dir().mkdir(parents=True, exist_ok=True)
    for src, tgt, _ in plans:
        # Annotate the moved note: was branch-scoped, now durable.
        post = frontmatter.load(src)
        post.metadata["consolidated_from"] = str(src.relative_to(mem))
        post.metadata["consolidated_at"] = today()
        write_text(tgt, frontmatter.dumps(post) + "\n")
        src.unlink()

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

    print()
    print(f"[strata] consolidation complete. {len(plans)} note(s) promoted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

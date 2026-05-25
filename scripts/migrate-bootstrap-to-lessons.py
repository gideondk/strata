#!/usr/bin/env python3
"""One-shot: move bootstrap-origin notes (identified by `source_file:`
frontmatter) out of pr-context/<branch>/ into lessons/.
Dry-run by default; --apply performs."""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Any

import frontmatter

import lib_loader  # noqa: F401
from lib import lessons_dir, memory_dir, safe_slug


def _scan_pr_context() -> list[tuple[Path, dict[str, Any]]]:
    # `source_file` is the bootstrap provenance marker — live-work
    # saves don't carry it, so this heuristic is safe.
    out: list[tuple[Path, dict[str, Any]]] = []
    pr_root = memory_dir() / "pr-context"
    if not pr_root.is_dir():
        return out
    for branch_dir in sorted(pr_root.iterdir()):
        if not branch_dir.is_dir():
            continue
        for f in sorted(branch_dir.glob("*.md")):
            if f.name in ("README.md", "INDEX.md"):
                continue
            try:
                post = frontmatter.load(f)
            except Exception:
                continue
            if post.metadata.get("source_file"):
                out.append((f, dict(post.metadata)))
    return out


def _target_filename(meta: dict[str, Any], src: Path) -> str:
    """Date-prefixed, topic-slugged. Mirrors save-note.py --scope lessons."""
    topic = meta.get("topic") or "untitled"
    created = str(meta.get("created") or "")
    date = created[:10] if len(created) >= 10 else src.stem[:10]
    if not (len(date) == 10 and date[4] == "-" and date[7] == "-"):
        date = "2026-01-01"  # last-resort placeholder
    return f"{date}-{safe_slug(topic)}.md"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="Actually perform the moves. Default is dry-run.")
    args = ap.parse_args()

    matches = _scan_pr_context()
    if not matches:
        print("[strata] no bootstrap-extracted notes found in pr-context/. "
              "Nothing to migrate.")
        return 0

    lessons = lessons_dir()
    plans: list[tuple[Path, Path]] = []
    for src, meta in matches:
        target_name = _target_filename(meta, src)
        target = lessons / target_name
        # Collision-suffix
        i = 2
        while target.exists() or any(t == target for _, t in plans):
            target = lessons / f"{target_name[:-3]}-{i}.md"
            i += 1
        plans.append((src, target))

    verb = "Moving" if args.apply else "Would move"
    print(f"[strata] {len(plans)} bootstrap-origin note(s) to migrate.")
    print()
    for src, target in plans:
        rel_src = src.relative_to(memory_dir())
        rel_tgt = target.relative_to(memory_dir())
        print(f"  {verb}:  {rel_src}")
        print(f"        →  {rel_tgt}")

    if not args.apply:
        print()
        print("[strata] dry-run only. Re-run with --apply to perform moves.")
        return 0

    lessons.mkdir(parents=True, exist_ok=True)
    for src, target in plans:
        shutil.move(str(src), str(target))

    # Refresh index so the moved notes are still discoverable
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
    print(f"[strata] migration complete. {len(plans)} note(s) moved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

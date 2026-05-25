#!/usr/bin/env python3
"""git mv .planning/<x> .attic/<x> + commit. Refuses unless every
file is bootstrap-processed (SHA matches state). Dry-run by default."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import lib_loader  # noqa: F401
from lib import is_git_repo, memory_dir, project_dir


def _bootstrap_state() -> dict:
    p = memory_dir() / ".bootstrap-state.json"
    if not p.exists():
        return {"processed_files": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"processed_files": {}}


def _file_sha(p: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _unprocessed(pd: Path, subdir: str) -> list[str]:
    """Return paths in `subdir` that haven't been bootstrap-processed
    (or that have changed since processing)."""
    state = _bootstrap_state()["processed_files"]
    base = (pd / subdir).resolve()
    out: list[str] = []
    for f in base.rglob("*.md"):
        if not f.is_file():
            continue
        rel = f.relative_to(pd).as_posix()
        meta = state.get(rel)
        if meta is None or meta.get("sha256") != _file_sha(f):
            out.append(rel)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("subdir",
                    help="Project-relative subdir to archive, "
                         "e.g. .planning/auth-rewrite")
    ap.add_argument("--apply", action="store_true",
                    help="Perform the git mv + commit. Default is dry-run.")
    ap.add_argument("--force", action="store_true",
                    help="Archive even if some files are unprocessed by "
                         "bootstrap. NOT recommended — knowledge in those "
                         "files won't have been migrated to the vault.")
    args = ap.parse_args()

    if not is_git_repo():
        print("[strata] error: not a git repo", file=sys.stderr)
        return 2
    pd = project_dir()
    if pd is None:
        print("[strata] error: no project dir", file=sys.stderr)
        return 2

    src = (pd / args.subdir).resolve()
    try:
        src.relative_to(pd.resolve())
    except ValueError:
        print(f"[strata] error: path escapes project: {args.subdir}",
              file=sys.stderr)
        return 2
    if not src.is_dir():
        print(f"[strata] error: not a directory: {args.subdir}",
              file=sys.stderr)
        return 2

    unprocessed = _unprocessed(pd, args.subdir)
    if unprocessed and not args.force:
        print(f"[strata] refusing to archive — {len(unprocessed)} file(s) "
              "in this subdir aren't bootstrap-processed:",
              file=sys.stderr)
        for u in unprocessed[:10]:
            print(f"  ?  {u}", file=sys.stderr)
        if len(unprocessed) > 10:
            print(f"  ?  (+{len(unprocessed) - 10} more)", file=sys.stderr)
        print()
        print("Run `/strata:bootstrap` over this subdir first, OR pass "
              "--force if you accept that those files won't be in the vault.",
              file=sys.stderr)
        return 2

    # Build target path under .attic/, preserving the same leaf name
    leaf = Path(args.subdir).name
    target = pd / ".attic" / leaf
    target_rel = target.relative_to(pd).as_posix()

    if target.exists():
        # Suffix-collide to keep history
        i = 2
        while (pd / ".attic" / f"{leaf}-{i}").exists():
            i += 1
        target = pd / ".attic" / f"{leaf}-{i}"
        target_rel = target.relative_to(pd).as_posix()

    verb = "Will move" if not args.apply else "Moving"
    print(f"[strata] {verb}:")
    print(f"  {args.subdir}")
    print(f"  → {target_rel}")
    print(f"  ({len(unprocessed)} unprocessed file{'s' if len(unprocessed) != 1 else ''}"
          f"{' — forced' if args.force and unprocessed else ''})")
    print()

    if not args.apply:
        print("[strata] dry-run only. Re-run with --apply to perform "
              "the git mv + commit.")
        return 0

    # git mv (creates dirs as needed)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["git", "-C", str(pd), "mv", args.subdir, target_rel],
            check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"[strata] git mv failed: {e.stderr}", file=sys.stderr)
        return 1

    msg = f"chore: archive planning {args.subdir} → {target_rel}"
    try:
        subprocess.run(
            ["git", "-C", str(pd), "commit", "-qm", msg],
            check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"[strata] git commit failed: {e.stderr}", file=sys.stderr)
        return 1

    print(f"[strata] archived: {args.subdir} → {target_rel}")
    print(f"[strata] committed: {msg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

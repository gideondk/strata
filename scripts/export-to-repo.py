#!/usr/bin/env python3
"""Copy a vault file into the host repo (default docs/adr/) for git-blameable
audit history. Lints --strict first; user runs git add / commit themselves.
Two-step with --dry-run."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import lib_loader  # noqa: F401
from lib import UnsafePathError, is_git_repo, memory_dir, project_dir, safe_resolve


def _lint(src: Path, preset: str) -> int:
    """Run memory-lint against the source file. Returns its exit code."""
    here = Path(__file__).resolve().parent
    lint = here / "memory-lint.py"
    r = subprocess.run(
        [sys.executable, str(lint), "--scope", str(src),
         "--preset", preset, "--strict"],
        capture_output=False,
    )
    return r.returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True,
                    help="Vault-relative path, e.g. 'decisions/...md'")
    ap.add_argument("--dest", default="docs/adr/",
                    help="Repo-relative destination directory (default docs/adr/)")
    ap.add_argument("--preset", default="secrets,pii",
                    help="Lint presets to enforce before copying")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    pd = project_dir()
    if pd is None or not is_git_repo():
        print("[strata] not in a git repo — refusing to export",
              file=sys.stderr)
        return 2

    mem = memory_dir()
    try:
        src = safe_resolve(args.source, mem)
    except UnsafePathError as e:
        print(f"[strata] {e}", file=sys.stderr)
        return 2
    if not src.exists() or not src.is_file():
        print(f"[strata] source not found: {src}", file=sys.stderr)
        return 2

    # Lint with --strict so the export is a deliberate clean snapshot
    print(f"[strata] lint {src} (preset: {args.preset}, strict)")
    rc = _lint(src, args.preset)
    if rc != 0:
        print(f"[strata] lint failed (exit {rc}) — refusing to export",
              file=sys.stderr)
        return 1

    try:
        dest_dir = safe_resolve(args.dest, pd) if not Path(args.dest).is_absolute() \
            else (_ for _ in ()).throw(UnsafePathError("absolute dest refused"))
    except UnsafePathError as e:
        print(f"[strata] {e}", file=sys.stderr)
        return 2

    dest = dest_dir / src.name
    print(f"[strata] $ cp {src} {dest}")

    if args.dry_run:
        print("[strata] dry-run — nothing copied")
        return 0

    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(src), str(dest))
    print(f"[strata] exported to {dest.relative_to(pd)}")
    print(f"[strata] next: git add {dest.relative_to(pd)} && "
          f"git commit -m 'docs: promote ADR {src.stem}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())

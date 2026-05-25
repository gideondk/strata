#!/usr/bin/env python3
"""Move vault file to `.trash/` + append JSONL audit entry. Recoverable.
Mandatory --reason. Use for erasure requests, accidental PHI, retracted
notes. Audit log captures who/when/why/SHA256 of moved file."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time

import lib_loader  # noqa: F401
from lib import (
    UnsafePathError,
    author_name,
    memory_dir,
    safe_resolve,
    stamp_minute,
)


def _sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", required=True,
                    help="Vault-relative path to forget.")
    ap.add_argument("--reason", required=True,
                    help="Why — recorded in the audit log. Required.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.reason.strip():
        print("[strata] --reason must not be empty", file=sys.stderr)
        return 2

    mem = memory_dir()
    if not mem.exists():
        print("[strata] no vault initialised", file=sys.stderr)
        return 2

    try:
        src = safe_resolve(args.path, mem)
    except UnsafePathError as e:
        print(f"[strata] {e}", file=sys.stderr)
        return 2

    if not src.exists() or not src.is_file():
        print(f"[strata] not a file: {args.path}", file=sys.stderr)
        return 2

    # Compute audit fingerprint before any move
    sha = _sha256(src)
    size = src.stat().st_size
    when_minute = stamp_minute()
    when_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Destination inside vault — `.trash/<timestamp>--<orig-flattened>.md`
    trash_root = mem / ".trash"
    flat_name = args.path.replace("/", "__")
    dest = trash_root / f"{when_minute}--{flat_name}"

    audit_entry = {
        "ts": when_iso,
        "action": "forget",
        "src": args.path,
        "dest": dest.relative_to(mem).as_posix(),
        "size": size,
        "sha256": sha,
        "by": author_name(),
        "reason": args.reason.strip(),
    }

    print(f"[strata] $ mv {src} {dest}")
    print(f"[strata] audit: {json.dumps(audit_entry, indent=None)}")

    if args.dry_run:
        print("[strata] dry-run — nothing moved")
        return 0

    trash_root.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))

    audit_log = mem / ".audit.log"
    with audit_log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(audit_entry) + "\n")

    print(f"[strata] forgotten — moved to {dest.relative_to(mem)}")
    print(f"[strata] audit appended to {audit_log.relative_to(mem)}")

    # Refresh the index so search stops returning the moved file
    try:
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
    except Exception as e:
        print(f"[strata] index refresh skipped: {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())

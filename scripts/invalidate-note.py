#!/usr/bin/env python3
"""Mark a note `status: invalidated`. Required `--reason`, optional
`--replaced-by`. Note stays readable; default search filters it out."""
from __future__ import annotations

import argparse
import sys

import frontmatter

import lib_loader  # noqa: F401
from lib import author_name, memory_dir, safe_resolve, today, write_text


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
    ap.add_argument("note",
                    help="Vault-relative path, e.g. domain/order-aggregate.md")
    ap.add_argument("--reason", required=True,
                    help="Why this note is no longer current. Required — "
                         "the audit trail is the point of invalidation.")
    ap.add_argument("--replaced-by", default=None,
                    help="Optional vault-relative path of the successor note.")
    args = ap.parse_args()

    mem = memory_dir()
    try:
        path = safe_resolve(args.note, mem)
    except Exception as e:
        print(f"[strata] error: {e}", file=sys.stderr)
        return 2
    if not path.exists() or not path.is_file():
        print(f"[strata] error: note not found: {args.note}", file=sys.stderr)
        return 2

    post = frontmatter.load(path)
    post.metadata["status"] = "invalidated"
    post.metadata["invalidated_at"] = today()
    post.metadata["invalidated_by"] = author_name()
    post.metadata["invalidation_reason"] = args.reason
    if args.replaced_by:
        post.metadata["replaced_by"] = args.replaced_by

    write_text(path, frontmatter.dumps(post) + "\n")
    print(f"[strata] invalidated: {args.note}")
    print(f"[strata] reason: {args.reason}")
    if args.replaced_by:
        print(f"[strata] replaced by: {args.replaced_by}")
    _refresh_index()
    return 0


if __name__ == "__main__":
    sys.exit(main())

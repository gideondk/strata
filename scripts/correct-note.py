#!/usr/bin/env python3
"""Edit a vault note. Body via stdin, fields via --set k=v.
Logs each correction to a `corrections:` frontmatter list."""
from __future__ import annotations

import argparse
import contextlib
import sys

import frontmatter

import lib_loader  # noqa: F401
from lib import author_name, memory_dir, safe_resolve, today, write_text


def _refresh_index() -> None:
    """Run refresh-index.py so the FTS index sees the change."""
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


def _record_correction(meta: dict, reason: str | None) -> None:
    """Append a `corrections:` log entry to the note's frontmatter."""
    entry = {
        "at": today(),
        "by": author_name(),
    }
    if reason:
        entry["reason"] = reason
    log = meta.get("corrections") or []
    if not isinstance(log, list):
        log = []
    log.append(entry)
    meta["corrections"] = log
    meta["updated"] = today()


def _parse_kv(spec: str) -> tuple[str, str]:
    if "=" not in spec:
        raise SystemExit(
            f"[strata] error: --set expects key=value, got {spec!r}"
        )
    k, v = spec.split("=", 1)
    return k.strip(), v.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("note",
                    help="Vault-relative path, e.g. domain/order-aggregate.md")
    ap.add_argument("--set", action="append", default=[],
                    metavar="KEY=VALUE",
                    help="Update one frontmatter field. Repeatable.")
    ap.add_argument("--reason", default=None,
                    help="Explanation logged in the corrections list. "
                         "Strongly recommended.")
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

    # Field updates first
    for spec in args.set:
        k, v = _parse_kv(spec)
        post.metadata[k] = v

    # Body replacement (if stdin is non-empty)
    if not sys.stdin.isatty():
        new_body = sys.stdin.read()
        if new_body.strip():
            post.content = new_body.rstrip() + "\n"

    if not args.set and (sys.stdin.isatty() or not new_body.strip()):
        print("[strata] error: nothing to change — provide --set "
              "or pipe a new body on stdin",
              file=sys.stderr)
        return 2

    _record_correction(post.metadata, args.reason)

    # Secret/PII pre-step (warn-only; never blocks). A correction can introduce
    # a credential via --set or a pasted body, so scan the composed document —
    # same guarantee /strata:save and /strata:decide already give.
    composed = frontmatter.dumps(post)
    with contextlib.suppress(Exception):
        import lint_check
        lint_check.emit_warnings(composed, label="correction")

    write_text(path, composed + "\n")
    print(f"[strata] corrected: {args.note}")
    if args.reason:
        print(f"[strata] reason logged: {args.reason}")
    _refresh_index()
    return 0


if __name__ == "__main__":
    sys.exit(main())

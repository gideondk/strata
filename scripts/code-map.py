#!/usr/bin/env python3
"""CLI shim for code_graph.project."""
from __future__ import annotations

import argparse
import sys

import code_graph
import lib_loader  # noqa: F401


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--focus", action="append", default=[],
                    help="Symbol name(s) to centre on. Repeatable.")
    ap.add_argument("--budget", type=int, default=1000,
                    help="Target token budget (soft cap). Default 1000.")
    ap.add_argument("--include-docs", action="store_true",
                    help="Include `file_type=document` nodes (default code-only).")
    args = ap.parse_args()

    out = code_graph.project(
        focus=args.focus or None,
        budget=args.budget,
        include_docs=args.include_docs,
    )
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Create a new ADR (Markdown Architectural Decision Record).

Skill invocation:
    python3 new-decision.py --title "<title>" \
        [--status proposed|accepted|...] \
        [--supersedes "2026-05-19-old-decision" [--supersedes ...]]
Body on stdin. If stdin is empty, we write the MADR template instead.

Filename: `YYYY-MM-DD-<title-slug>.md` in `<vault>/<repo>/decisions/`.

When `--supersedes` is given, we also update the predecessor ADR's
`superseded_by:` frontmatter list so the chain is bidirectional and survives
re-indexing on any machine.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
from pathlib import Path

import frontmatter

import lib_loader  # noqa: F401
from lib import (
    author_name,
    ensure_dir,
    memory_dir,
    origin_branch,
    plugin_root,
    safe_slug,
    today,
    write_text,
)

VALID_STATUS = {"proposed", "accepted", "rejected", "deprecated", "superseded"}


def _link_predecessor(mem: Path, pred_ref: str, new_path_rel: str) -> str | None:
    """Resolve a predecessor reference and write `superseded_by` into its
    frontmatter. Returns the predecessor's vault-relative path on success.
    """
    candidates = [
        pred_ref,
        pred_ref if pred_ref.endswith(".md") else f"{pred_ref}.md",
        f"decisions/{pred_ref}",
        f"decisions/{pred_ref}.md" if not pred_ref.endswith(".md")
        else f"decisions/{pred_ref}",
    ]
    target: Path | None = None
    for c in candidates:
        p = (mem / c).resolve()
        try:
            p.relative_to(mem.resolve())
        except ValueError:
            continue
        if p.exists():
            target = p
            break
    if target is None:
        print(f"[strata] warning: predecessor not found: {pred_ref}",
              file=sys.stderr)
        return None

    post = frontmatter.load(target)
    raw_sb = post.metadata.get("superseded_by") or []
    superseded_by: list[str]
    if isinstance(raw_sb, str):
        superseded_by = [raw_sb]
    elif isinstance(raw_sb, list):
        superseded_by = [str(x) for x in raw_sb]
    else:
        superseded_by = []
    if new_path_rel not in superseded_by:
        superseded_by.append(new_path_rel)
    post.metadata["superseded_by"] = superseded_by
    # Bump status if it was still "accepted"/"proposed"
    if post.metadata.get("status") in (None, "proposed", "accepted"):
        post.metadata["status"] = "superseded"
    target.write_text(frontmatter.dumps(post), encoding="utf-8")
    return target.relative_to(mem).as_posix()


def _template_body(title: str) -> str:
    tpl = plugin_root() / "templates" / "decision.md"
    if tpl.exists():
        return tpl.read_text(encoding="utf-8").replace("<TITLE>", title)
    return f"# {title}\n\n## Context\n\n## Decision\n\n## Consequences\n"


_SYMBOL_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_.]{2,})`")


def _verify_symbols(body: str, strict: bool) -> int:
    """If graph.json is present, check that backtick-quoted identifiers in
    the ADR body resolve to known Graphify nodes.

    Returns: 0 if clean / no graph, 1 if unresolved symbols found in strict mode.
    """
    try:
        import code_graph as _cg
    except ImportError:
        return 0
    if _cg.graph_path() is None:
        return 0  # no graph → nothing to verify against

    candidates = set(_SYMBOL_RE.findall(body))
    # Skip purely lowercase short words (e.g. `the`, `null`) and code keywords.
    filtered = [
        c for c in candidates
        if any(ch.isupper() for ch in c) or "_" in c or "." in c
    ]
    if not filtered:
        return 0

    unresolved: list[str] = []
    for sym in sorted(filtered):
        if not _cg.resolve_symbol(sym):
            # Also try the trailing leaf for dotted forms
            leaf = sym.rsplit(".", 1)[-1]
            if leaf != sym and _cg.resolve_symbol(leaf):
                continue
            unresolved.append(sym)

    if not unresolved:
        return 0

    print(f"[strata] symbol check: {len(unresolved)} unresolved "
          f"identifier(s) — not found in graph.json:", file=sys.stderr)
    for sym in unresolved:
        print(f"  ?  `{sym}`", file=sys.stderr)
    if strict:
        print("[strata] --strict-symbols set: refusing to write ADR",
              file=sys.stderr)
        return 1
    print("[strata] (warning only — use --strict-symbols to block)",
          file=sys.stderr)
    return 0


def _slim(c: dict) -> dict:
    """JSON-safe candidate subset for --check-only output."""
    return {
        "path": c["path"],
        "title": c["title"],
        "status": c["status"],
        "semantic": c["semantic"],
        "exact_title": c["exact_title"],
        "fts": c["fts"],
    }


def _dedup_gate(title: str, body: str, *, check_only: bool, ack_new: bool,
                no_dedup: bool, supersedes: list[str]) -> tuple[int, bool]:
    """Recall-before-write gate. Returns (exit_code, should_return).

    should_return True means main() must return exit_code immediately
    (a block, or a --check-only run that already emitted its JSON).
    """
    # Superseding IS the resolution to a collision, and --no-dedup is the
    # explicit escape hatch (batch flows like bootstrap pass it).
    skip = no_dedup or bool(supersedes)

    if skip:
        if check_only:
            print(json.dumps({"recommendation": "clear", "candidates": []}))
            return 0, True
        return 0, False

    import dedup
    # Keep stdout pristine for --check-only: retrieval may load an ONNX model
    # or reindex, so route any incidental chatter to stderr — only the final
    # json.dumps below writes to real stdout.
    with contextlib.redirect_stdout(sys.stderr):
        candidates = dedup.find_similar_decisions(title, body)
        verdict, top = dedup.classify(candidates)

    if check_only:
        print(json.dumps({
            "recommendation": verdict,
            "candidates": [_slim(c) for c in candidates[:5]],
        }))
        return 0, True

    if verdict == "block" and not ack_new:
        slug = Path(top["path"]).stem if top else "<slug>"
        print("[strata] dedup: this looks like an EXISTING decision —",
              file=sys.stderr)
        print(f"    {top['path']}  ({dedup.reason(top)})", file=sys.stderr)
        print("  Pick one:", file=sys.stderr)
        print(f"    • supersede it:      re-run with --supersedes {slug}",
              file=sys.stderr)
        print("    • update it instead: edit that note (don't fork a parallel ADR)",
              file=sys.stderr)
        print("    • genuinely new:     re-run with --ack-new", file=sys.stderr)
        print("  Refusing to write a likely duplicate (--no-dedup bypasses).",
              file=sys.stderr)
        return 3, True

    if verdict == "warn" and top:
        print(f"[strata] dedup: similar existing decision — {top['path']} "
              f"({dedup.reason(top)}). Proceeding; supersede or merge if it's "
              f"the same choice.", file=sys.stderr)
    return 0, False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True)
    ap.add_argument("--status", default="proposed")
    ap.add_argument("--supersedes", action="append", default=[],
                    help="Predecessor ADR (slug, filename, or relative path). "
                         "Repeatable.")
    ap.add_argument("--check-only", action="store_true",
                    help="Run the recall-before-write dedup check and print a "
                         "JSON report ({recommendation, candidates}) WITHOUT "
                         "writing. Used by /strata:decide to adjudicate "
                         "ADD/UPDATE/SUPERSEDE/NO-OP before creating an ADR.")
    ap.add_argument("--ack-new", action="store_true",
                    help="Acknowledge that this decision is genuinely distinct "
                         "from any near-duplicate the dedup gate found, and "
                         "write it anyway.")
    ap.add_argument("--no-dedup", action="store_true",
                    help="Skip the recall-before-write dedup gate entirely "
                         "(batch/non-interactive flows like bootstrap).")
    ap.add_argument("--strict-symbols", action="store_true",
                    help="If graph.json is present, refuse to write the ADR "
                         "when backtick-quoted identifiers in the body don't "
                         "resolve to known Graphify nodes (catches typos).")
    ap.add_argument("--project-dir", default=None,
                    help="Override the project root used for namespace "
                         "resolution. Same effect as setting STRATA_PROJECT_DIR. "
                         "Use this when invoking new-decision.py from a "
                         "directory other than the target project's repo root.")
    ap.add_argument("--source-file", action="append", default=[],
                    help="Provenance: project-relative path(s) of source "
                         "doc(s) this ADR was extracted from. Repeatable, "
                         "or pass a comma-joined list. Recorded as a list "
                         "in frontmatter so multi-source consolidation "
                         "(bootstrap-worker grouping) keeps full provenance.")
    args = ap.parse_args()

    if args.project_dir:
        os.environ["STRATA_PROJECT_DIR"] = args.project_dir

    # Accept comma-joined values too, and dedupe while preserving order.
    expanded: list[str] = []
    for entry in args.source_file:
        for piece in (s.strip() for s in entry.split(",")):
            if piece and piece not in expanded:
                expanded.append(piece)
    args.source_file = expanded

    if args.status not in VALID_STATUS:
        print(f"[strata] error: --status must be one of {sorted(VALID_STATUS)}",
              file=sys.stderr)
        return 2

    raw_body = sys.stdin.read().strip()

    # Recall-before-write: surface near-duplicate decisions before one lands.
    # Runs on the human-authored body (not the template), so the semantic
    # signal isn't skewed by boilerplate.
    code, should_return = _dedup_gate(
        args.title, raw_body,
        check_only=args.check_only, ack_new=args.ack_new,
        no_dedup=args.no_dedup, supersedes=args.supersedes,
    )
    if should_return:
        return code

    body = raw_body or _template_body(args.title)

    # Symbol cross-check against Graphify (no-op if graph.json absent)
    rc = _verify_symbols(body, strict=args.strict_symbols)
    if rc != 0:
        return rc

    slug = safe_slug(args.title)
    when = today()
    dir_ = memory_dir() / "decisions"
    ensure_dir(dir_)
    fname = f"{when}-{slug}.md"
    path: Path = dir_ / fname

    if path.exists():
        # Collision — same title same day. Suffix with -2, -3, …
        i = 2
        while (dir_ / f"{when}-{slug}-{i}.md").exists():
            i += 1
        path = dir_ / f"{when}-{slug}-{i}.md"

    # Build the frontmatter as a real YAML block via the frontmatter lib so
    # the supersedes list serialises cleanly.
    fm_meta: dict = {
        "title": args.title,
        "status": args.status,
        "date": when,
        "author": author_name(),
        "supersedes": list(args.supersedes),
        "superseded_by": [],
    }
    ob = origin_branch()
    if ob:
        fm_meta["branch"] = ob
    if args.source_file:
        # Store as a list when there are multiple sources so multi-file
        # consolidation keeps complete provenance in the frontmatter.
        fm_meta["source_file"] = (
            args.source_file if len(args.source_file) > 1 else args.source_file[0]
        )
        fm_meta["extracted_at"] = when
        fm_meta["extracted_by"] = author_name()
    post = frontmatter.Post(content=body.lstrip(), **fm_meta)
    composed = frontmatter.dumps(post)
    # Secret/PII pre-step (warn-only; never blocks). Scans the composed doc so a
    # secret in the title/frontmatter is caught too, not just the body.
    import contextlib
    with contextlib.suppress(Exception):
        import lint_check
        lint_check.emit_warnings(composed, label="decision")

    write_text(path, composed + "\n")
    print(f"[strata] decision created: {path}")

    # Bidirectional supersession: update each predecessor's frontmatter so
    # the link survives re-indexing.
    new_rel = path.relative_to(memory_dir()).as_posix()
    for pred in args.supersedes:
        linked = _link_predecessor(memory_dir(), pred, new_rel)
        if linked:
            print(f"[strata] linked predecessor: {linked}")

    # Refresh index
    import importlib.util
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

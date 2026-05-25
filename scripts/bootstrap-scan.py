#!/usr/bin/env python3
"""Mechanical scan for files to seed the vault with. Claude does the
extraction; this just enumerates candidates with age + freshness signals.
Idempotent via SHA256-tracking in `.bootstrap-state.json`."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pathspec

import lib_loader  # noqa: F401
from lib import is_git_repo, memory_dir, project_dir

# Module-level: lookup of {project-relative path → last-commit ISO datetime}.
# Populated once per scan invocation by _batch_git_mtimes(). Avoids the N
# subprocess forks the previous per-file _git_last_modified used.
_MTIME_CACHE: dict[str, str | None] = {}

# Doc-claim extraction logic lives in `doc_claims` so plan_correlate.py
# can reuse the regex tuning (longest-extension-first, URL filter, etc.)
# without duplicating. Imported below module-level constants because
# lib_loader needs to run first to put scripts/ on sys.path.
from doc_claims import extract_path_claims as _extract_path_claims  # noqa: E402
from doc_claims import extract_symbol_claims as _extract_symbol_claims  # noqa: E402

# Sane defaults, loaded as the lowest-priority ignore-spec layer.
# Users override per-repo via `.strataignore` (highest precedence) or
# `.ignore` (cross-tool convention from ripgrep/fd). Negation works:
# `!pattern` in `.strataignore` re-includes a default-excluded path.
DEFAULT_IGNORE_LINES = [
    # Build / vendored / cache — almost never bootstrap-worthy
    "node_modules/",
    ".git/",
    "dist/",
    "build/",
    "target/",
    ".venv/",
    "venv/",
    "__pycache__/",
    ".next/",
    ".nuxt/",
    ".cache/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    "coverage/",
    ".coverage/",
    "htmlcov/",
    # Plugin / tool meta-scaffolding (override with !.claude/ etc. if needed)
    ".claude/",
    ".github/",
    ".gitlab/",
    ".vscode/",
    ".idea/",
    ".zed/",
    ".agents/",
    # Outputs we generate
    "graphify-out/",
    ".strata/",
    # Common AI-tool config files at repo root
    ".impeccable.md",
    ".cursor.md",
    ".cursorrules",
    ".aider.conf.yml",
    ".aiderrc.md",
    ".copilot.md",
    ".windsurf.md",
    # Common low-signal root files
    "CHANGELOG.md",
    "LICENSE.md",
]


def _build_ignore_spec(pd: Path) -> pathspec.PathSpec:
    """Combined gitwildmatch PathSpec for bootstrap exclusion.

    Layered, lowest precedence first → later patterns override earlier ones
    (including `!negation`, gitignore-style):
      1. DEFAULT_IGNORE_LINES (hardcoded sane defaults)
      2. .ignore (ripgrep/fd cross-tool convention)
      3. .strataignore (tool-specific, highest)
    """
    lines = list(DEFAULT_IGNORE_LINES)
    for filename in (".ignore", ".strataignore"):
        f = pd / filename
        if f.exists():
            with contextlib.suppress(OSError):
                lines.extend(f.read_text(encoding="utf-8").splitlines())
    return pathspec.PathSpec.from_lines("gitwildmatch", lines)

# Hard size cap by default — auto-generated docs can be huge and aren't
# useful as memory seeds.
DEFAULT_MAX_SIZE = 200_000

# Age bucket thresholds (days). Anything > ANCIENT_DAYS is "ancient".
FRESH_DAYS = 90
AGING_DAYS = 365
OLD_DAYS = 730  # 2 years; older than this = ancient


def _age_bucket(age_days: int | None) -> str:
    if age_days is None:
        return "untracked"
    if age_days < FRESH_DAYS:
        return "fresh"
    if age_days < AGING_DAYS:
        return "aging"
    if age_days < OLD_DAYS:
        return "old"
    return "ancient"


def _bucket_marker(bucket: str) -> str:
    return {
        "fresh": "🟢",
        "aging": "🟡",
        "old": "🟠",
        "ancient": "🔴",
        "untracked": "⚪",
    }.get(bucket, "")


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _state_path() -> Path:
    return memory_dir() / ".bootstrap-state.json"


def _load_state() -> dict:
    p = _state_path()
    if not p.exists():
        return {"processed_files": {}, "graphify_built": False}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"processed_files": {}, "graphify_built": False}


def _save_state(state: dict) -> None:
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _list_git_visible_files(pd: Path) -> list[str] | None:
    """Return tracked + untracked-but-not-ignored files via two `git
    ls-files` calls. Returns None if `pd` isn't a git repo (caller falls
    back to rglob)."""
    try:
        check = subprocess.run(
            ["git", "-C", str(pd), "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, check=False, timeout=5,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return None
    if check.returncode != 0 or check.stdout.strip() != "true":
        return None

    out: list[str] = []
    for args in (["ls-files"], ["ls-files", "--others", "--exclude-standard"]):
        try:
            r = subprocess.run(
                ["git", "-C", str(pd), *args],
                capture_output=True, text=True, check=False, timeout=30,
            )
        except (subprocess.SubprocessError, FileNotFoundError):
            continue
        if r.returncode == 0:
            out.extend(line for line in r.stdout.splitlines() if line)
    return out


def _walk_all_markdown(pd: Path, max_size: int) -> list[Path]:
    """Find every .md file under pd, minus the layered ignore spec
    (defaults + .ignore + .strataignore), oversize files, and anything
    ignored by .gitignore. Walks via `git ls-files` when in a git repo;
    falls back to rglob otherwise."""
    git_files = _list_git_visible_files(pd)
    if git_files is not None:
        candidates = (
            pd / rel for rel in git_files if rel.endswith(".md")
        )
    else:
        candidates = (p for p in pd.rglob("*.md"))

    spec = _build_ignore_spec(pd)
    out: list[Path] = []
    seen: set[Path] = set()
    for p in candidates:
        if p in seen:
            continue
        seen.add(p)
        if not p.is_file():
            continue
        rel = p.relative_to(pd).as_posix()
        if spec.match_file(rel):
            continue
        try:
            if p.stat().st_size > max_size:
                continue
        except OSError:
            continue
        out.append(p)
    return sorted(out)


def _group_by_top_dir(pd: Path, files: list[Path]) -> dict[str, list[Path]]:
    """Group files by their top-level directory (or '(root)' for root files).

    Result is ordered: root first, then directories alphabetically.
    """
    groups: dict[str, list[Path]] = {}
    for f in files:
        rel = f.relative_to(pd).as_posix()
        if "/" in rel:
            top = rel.split("/", 1)[0]
            key = f"{top}/"
        else:
            key = "(root)"
        groups.setdefault(key, []).append(f)
    # Sort: root first, then alphabetical
    ordered: dict[str, list[Path]] = {}
    if "(root)" in groups:
        ordered["(root)"] = groups.pop("(root)")
    for k in sorted(groups):
        ordered[k] = groups[k]
    return ordered


def _group_by_parent_dir(pd: Path, files: list[Path]) -> dict[str, list[Path]]:
    """Group files by their immediate parent directory.

    This is the dispatch-grouping key for the bootstrap workflow. Sibling
    files in the same folder (e.g. `.planning/x/PLAN.md`, `.../CONTEXT.md`,
    `.../SPEC.md`) are almost always about the same initiative — group
    them so one worker handles the set and writes one consolidated note
    instead of N near-duplicates. Root files go to a `(root)` bucket.
    """
    groups: dict[str, list[Path]] = {}
    for f in files:
        rel = f.relative_to(pd).as_posix()
        parent = rel.rsplit("/", 1)[0] if "/" in rel else "(root)"
        groups.setdefault(parent, []).append(f)
    ordered: dict[str, list[Path]] = {}
    if "(root)" in groups:
        ordered["(root)"] = groups.pop("(root)")
    for k in sorted(groups):
        ordered[k] = groups[k]
    return ordered


def _git_ls_files(pd: Path) -> set[str]:
    """Return the set of git-tracked file paths in the repo. One subprocess
    call regardless of how many docs we then verify against it."""
    try:
        r = subprocess.run(
            ["git", "-C", str(pd), "ls-files"],
            capture_output=True, text=True, check=False, timeout=30,
        )
        if r.returncode != 0:
            return set()
        return {line for line in r.stdout.splitlines() if line}
    except (subprocess.SubprocessError, FileNotFoundError):
        return set()


def _verify_paths(claims: list[str], git_files: set[str]) -> tuple[list[str], list[str]]:
    """Return (verified, missing). A claim verifies if there's an exact
    or basename-suffix match in git_files."""
    if not git_files:
        return [], list(claims)
    by_basename = {gf.rsplit("/", 1)[-1] for gf in git_files}
    verified: list[str] = []
    missing: list[str] = []
    for c in claims:
        if c in git_files:
            verified.append(c)
            continue
        # Basename match: doc says `Widget.cs`, repo has `services/x/Widget.cs`
        basename = c.rsplit("/", 1)[-1]
        if basename in by_basename:
            verified.append(c)
            continue
        # Suffix match: doc says `src/orders/Widget.cs`,
        # repo has it under a deeper path
        if any(gf.endswith("/" + c) for gf in git_files):
            verified.append(c)
            continue
        missing.append(c)
    return verified, missing


def _verify_symbols(claims: list[str], pd: Path) -> tuple[list[str], list[str]]:
    """Return (verified, missing). Uses graph.json if present, else skips
    (returns empty verified/missing) — we don't run unbounded greps."""
    if not claims:
        return [], []
    try:
        import code_graph
        if code_graph.graph_path() is None:
            return [], []
        verified: list[str] = []
        missing: list[str] = []
        for sym in claims:
            if code_graph.resolve_symbol(sym):
                verified.append(sym)
                continue
            leaf = sym.rsplit(".", 1)[-1]
            if leaf != sym and code_graph.resolve_symbol(leaf):
                verified.append(sym)
                continue
            missing.append(sym)
        return verified, missing
    except Exception:
        return [], []


def _verify_file(f: Path, pd: Path, git_files: set[str]) -> dict:
    """Verify one doc's claims. Returns dict with verified/missing claims
    and a freshness score (0-1) when applicable."""
    try:
        text = f.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {
            "freshness": None,
            "paths_verified": [],
            "paths_missing": [],
            "symbols_verified": [],
            "symbols_missing": [],
        }
    p_claims = _extract_path_claims(text)
    s_claims = _extract_symbol_claims(text)
    p_ok, p_miss = _verify_paths(p_claims, git_files)
    s_ok, s_miss = _verify_symbols(s_claims, pd)
    total_claims = len(p_ok) + len(p_miss) + len(s_ok) + len(s_miss)
    if total_claims == 0:
        freshness = None
    else:
        freshness = round(
            (len(p_ok) + len(s_ok)) / total_claims, 2
        )
    return {
        "freshness": freshness,
        "paths_verified": p_ok,
        "paths_missing": p_miss,
        "symbols_verified": s_ok,
        "symbols_missing": s_miss,
    }


def _batch_git_mtimes(pd: Path) -> dict[str, str]:
    """One git log call → {project-relative path → ISO datetime of last
    commit that touched it}. Replaces the N-subprocess-fork version.

    Strategy: `git log --name-only --format=COMMIT:%cI` lists each commit
    followed by the files it touched. Walk newest → oldest and record the
    first commit-time we see for each path.
    """
    out: dict[str, str] = {}
    try:
        r = subprocess.run(
            ["git", "-C", str(pd), "log",
             "--name-only", "--format=COMMIT:%cI", "--no-renames"],
            capture_output=True, text=True, check=False, timeout=60,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return out
    if r.returncode != 0:
        return out
    current_ts: str | None = None
    for line in r.stdout.splitlines():
        if line.startswith("COMMIT:"):
            current_ts = line[len("COMMIT:"):].strip()
        elif line and current_ts and line not in out:
            out[line] = current_ts
    return out


def _git_last_modified(pd: Path, rel: str) -> str | None:
    """Look up cached mtime built by _batch_git_mtimes."""
    return _MTIME_CACHE.get(rel)


def _age_days(iso_dt: str | None) -> int | None:
    if not iso_dt:
        return None
    try:
        dt = datetime.fromisoformat(iso_dt)
    except ValueError:
        return None
    delta = datetime.now(timezone.utc) - dt
    return max(0, int(delta.total_seconds() // 86400))


def _entry(pd: Path, f: Path, state: dict) -> dict:
    rel = f.relative_to(pd).as_posix()
    meta = state["processed_files"].get(rel) or {}
    already = False
    if meta:
        with contextlib.suppress(OSError):
            already = meta.get("sha256") == _sha256(f)
    try:
        size = f.stat().st_size
    except OSError:
        size = 0
    last_mod = _git_last_modified(pd, rel)
    age = _age_days(last_mod)
    bucket = _age_bucket(age)
    return {
        "path": rel,
        "size": size,
        "processed": already,
        "processed_at": meta.get("processed_at"),
        "last_modified": last_mod,
        "age_days": age,
        "age_bucket": bucket,
    }


_DATE_RE = re.compile(r"(\d{4}-\d{2})")


def _subdivide_dense_groups(
    groups: dict[str, list[dict]], max_size: int,
) -> dict[str, list[dict]]:
    """Split any group with more than `max_size` files into sub-groups.

    Strategy:
      1. If at least half the files have a `YYYY-MM` prefix in the
         basename, split by that prefix (e.g. all 2026-04-* files go
         together, all 2026-05-* together). Preserves dated-initiative
         affinity.
      2. Otherwise, chunk into max_size-sized batches and tag with `#N`.

    The result lets a worker see a smaller, more cohesive set so the
    "at most 3-6 notes per group" cap retains more information.
    """
    out: dict[str, list[dict]] = {}
    for parent, files in groups.items():
        if len(files) <= max_size:
            out[parent] = files
            continue

        # Try date-prefix bucketing first.
        by_month: dict[str, list[dict]] = {}
        unmatched: list[dict] = []
        for f in files:
            base = f["path"].rsplit("/", 1)[-1]
            m = _DATE_RE.match(base)
            if m:
                by_month.setdefault(m.group(1), []).append(f)
            else:
                unmatched.append(f)

        # If most files matched, use date buckets.
        if sum(len(v) for v in by_month.values()) >= len(files) // 2:
            for month, bucket in sorted(by_month.items()):
                key = f"{parent}@{month}"
                # Recurse: a month bucket might itself be huge.
                if len(bucket) > max_size:
                    for i in range(0, len(bucket), max_size):
                        out[f"{key}#{i // max_size + 1}"] = bucket[i:i + max_size]
                else:
                    out[key] = bucket
            if unmatched:
                # Any non-dated stragglers get their own sub-group.
                for i in range(0, len(unmatched), max_size):
                    out[f"{parent}@misc#{i // max_size + 1}"] = unmatched[i:i + max_size]
            continue

        # Fall through: plain N-sized chunks.
        for i in range(0, len(files), max_size):
            out[f"{parent}#{i // max_size + 1}"] = files[i:i + max_size]

    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unprocessed", action="store_true",
                    help="Show only files not yet bootstrapped (or modified "
                         "since last bootstrap).")
    ap.add_argument("--json", action="store_true",
                    help="Machine-readable JSON output instead of markdown.")
    ap.add_argument("--mark", type=str, default=None,
                    help="Mark a file (project-relative path) as processed "
                         "with its current SHA256.")
    ap.add_argument("--max-size", type=int, default=DEFAULT_MAX_SIZE,
                    help=f"Skip markdown files larger than this many bytes "
                         f"(default {DEFAULT_MAX_SIZE}). Auto-generated "
                         "docs are usually huge and noisy.")
    ap.add_argument("--max-age-days", type=int, default=None,
                    help="Skip files whose last git commit is older than "
                         "this many days. Useful to bootstrap only fresh "
                         "docs first; defaults to no limit (all ages shown "
                         "with bucket markers).")
    ap.add_argument("--bucket",
                    choices=["fresh", "aging", "old", "ancient", "untracked"],
                    default=None,
                    help="Limit to a single age bucket. Useful for staged "
                         "bootstrap: --bucket fresh first, then aging, etc.")
    ap.add_argument("--verify", action="store_true",
                    help="Cross-check each doc's claims (file path mentions, "
                         "backtick-quoted symbols) against `git ls-files` "
                         "and graph.json. Slower but tells you which docs "
                         "actually describe code that still exists.")
    ap.add_argument("--min-freshness", type=float, default=None,
                    help="With --verify, only show files whose freshness "
                         "score >= this threshold (0.0-1.0).")
    ap.add_argument("--max-group-size", type=int, default=None,
                    help="When a parent-dir group has more than N files, "
                         "split it into sub-groups so each worker has a "
                         "manageable set. Sub-groups are split by YYYY-MM "
                         "date prefix when filenames are dated, else into "
                         "N-sized chunks. Prevents the at-most-3-notes-per-"
                         "group rule from losing information on dense "
                         "plans/specs folders.")
    args = ap.parse_args()

    if not is_git_repo():
        print("[strata] not a git repo", file=sys.stderr)
        return 2

    pd = project_dir()
    if pd is None:
        print("[strata] no project dir", file=sys.stderr)
        return 2

    state = _load_state()

    # --mark: update state for one file and exit
    if args.mark:
        p = pd / args.mark
        if not p.exists() or not p.is_file():
            print(f"[strata] file not found: {args.mark}", file=sys.stderr)
            return 2
        state["processed_files"][args.mark] = {
            "sha256": _sha256(p),
            "processed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        _save_state(state)
        print(f"[strata] marked as processed: {args.mark}")
        return 0

    files = _walk_all_markdown(pd, args.max_size)
    grouped = _group_by_top_dir(pd, files)

    # Pre-fetch once: git ls-files (for path verification) + git mtimes
    # (for age buckets). Both replace what was previously N subprocess
    # forks per file with one call each.
    git_files: set[str] = _git_ls_files(pd) if args.verify else set()
    _MTIME_CACHE.clear()
    _MTIME_CACHE.update(_batch_git_mtimes(pd))

    # Parallelise the per-file work — _entry does SHA256, mtime lookup,
    # and (with --verify) claim extraction + verification. IO-bound +
    # subprocess-bound work parallelises well across threads.
    def _process_file(f: Path) -> dict | None:
        e = _entry(pd, f, state)
        if args.unprocessed and e["processed"]:
            return None
        if args.max_age_days is not None and e["age_days"] is not None \
                and e["age_days"] > args.max_age_days:
            return None
        if args.bucket is not None and e["age_bucket"] != args.bucket:
            return None
        if args.verify:
            v = _verify_file(f, pd, git_files)
            e.update(v)
            if args.min_freshness is not None and v["freshness"] is not None \
                    and v["freshness"] < args.min_freshness:
                return None
        return e

    groups: dict[str, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        for top, paths in grouped.items():
            results = list(pool.map(_process_file, paths))
            entries = [r for r in results if r is not None]
            if entries:
                groups[top] = entries

    graph_present = (pd / "graphify-out" / "graph.json").exists()
    total = sum(len(v) for v in groups.values())
    total_all = sum(len(v) for v in grouped.values())

    # Dispatch grouping: parent-dir keyed. Sibling files in the same
    # folder are almost always about the same initiative — the parent
    # agent should dispatch one worker per group so the worker sees the
    # whole set and writes one consolidated note instead of N duplicates.
    dispatch_groups: dict[str, list[dict]] = {}
    for entries in groups.values():
        for e in entries:
            p = e["path"]
            parent = p.rsplit("/", 1)[0] if "/" in p else "(root)"
            dispatch_groups.setdefault(parent, []).append(e)
    # Optional: subdivide dense groups so the per-group note cap doesn't
    # collapse 30 distinct initiatives into 3-6 notes.
    if args.max_group_size and args.max_group_size > 0:
        dispatch_groups = _subdivide_dense_groups(
            dispatch_groups, args.max_group_size
        )

    # Order: root first, then alphabetical
    dispatch_groups_ordered: dict[str, list[dict]] = {}
    if "(root)" in dispatch_groups:
        dispatch_groups_ordered["(root)"] = dispatch_groups.pop("(root)")
    for k in sorted(dispatch_groups):
        dispatch_groups_ordered[k] = dispatch_groups[k]

    if args.json:
        out = {
            "project": str(pd),
            "vault_namespace": memory_dir().name,
            "graphify_built": graph_present,
            "candidates": groups,
            "dispatch_groups": dispatch_groups_ordered,
            "total_files": total,
            "total_files_all": total_all,
        }
        print(json.dumps(out, indent=2))
        return 0

    # Human-readable markdown
    lines: list[str] = [
        "# Strata bootstrap candidates",
        f"_project: `{pd}`_",
        f"_vault namespace: `{memory_dir().name}`_",
        f"_graphify built: {'yes' if graph_present else 'no — consider /strata:graphify first'}_",
        f"_scope: every `*.md` under project root, minus skipped paths, "
        f"under {args.max_size:,} bytes_",
        "",
        "_Age buckets_: 🟢 fresh (<90d) - 🟡 aging (90-365d) - "
        "🟠 old (1-2y) - 🔴 ancient (>2y) - ⚪ untracked",
        "",
    ]
    # Aggregate bucket counts for the summary
    bucket_counts: dict[str, int] = {}
    for top, entries in groups.items():
        lines.append(f"## `{top}`  ({len(entries)} files)")
        for e in entries:
            mark = _bucket_marker(e["age_bucket"])
            age_str = (
                f"{e['age_days']}d" if e["age_days"] is not None
                else "untracked"
            )
            done = " ✓ already processed" if e["processed"] else ""
            fresh_str = ""
            if args.verify and e.get("freshness") is not None:
                fresh_pct = int(e["freshness"] * 100)
                fresh_str = f" - freshness: {fresh_pct}%"
                if e["paths_missing"]:
                    fresh_str += (
                        f" (missing paths: "
                        f"{', '.join(f'`{p}`' for p in e['paths_missing'][:3])}"
                        f"{', ...' if len(e['paths_missing']) > 3 else ''})"
                    )
            lines.append(
                f"- {mark} `{e['path']}`  ({e['size']:,} bytes - {age_str})"
                f"{fresh_str}{done}"
            )
            bucket_counts[e["age_bucket"]] = (
                bucket_counts.get(e["age_bucket"], 0) + 1
            )
        lines.append("")

    if not groups:
        if args.unprocessed and total_all > 0:
            lines.append(
                f"_All {total_all} markdown file(s) already processed. "
                "Drop --unprocessed to see them, or edit one to resurface._"
            )
        else:
            lines.append(
                "_No markdown candidates found. Either the repo has no "
                "docs to bootstrap, or everything matches skip patterns._"
            )
    else:
        lines.append("---")
        bucket_summary = "  ".join(
            f"{_bucket_marker(b)} {n}"
            for b, n in [
                ("fresh", bucket_counts.get("fresh", 0)),
                ("aging", bucket_counts.get("aging", 0)),
                ("old", bucket_counts.get("old", 0)),
                ("ancient", bucket_counts.get("ancient", 0)),
                ("untracked", bucket_counts.get("untracked", 0)),
            ]
            if n > 0
        )
        lines.append(
            f"**Summary**: {total} candidate(s) across {len(groups)} "
            f"location(s).  {bucket_summary}"
        )
        if bucket_counts.get("old", 0) or bucket_counts.get("ancient", 0):
            lines.append("")
            lines.append(
                "⚠ Some docs are 1+ year old. Treat them with suspicion — "
                "draft as **lessons** (retrospective) rather than "
                "authoritative ADRs / domain notes. Cross-check claims "
                "against current code before promoting. Use "
                "`--bucket fresh` first, then `--bucket aging`, etc., "
                "to stage the bootstrap by confidence level."
            )
        lines.append("")
        lines.append(
            "Next: walk each file, extract appropriate notes, autonomously "
            "invoke `strata:domain`, `strata:decide`, or "
            "`strata:save`. Mark each via: "
            "`bootstrap-scan.py --mark <relative-path>`"
        )

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Cross-check a planning subdir's path/symbol claims against git
history and graph.json. Outputs a completion estimate per subdir.
See docs/guide/bootstrap.md for the classification verdicts."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import doc_claims
import lib_loader  # noqa: F401
from lib import is_git_repo, project_dir

# Don't try to correlate against URLs / Graphify-only / external paths.
# Same `looks_like_url` filter as doc_claims, plus a guard that the path
# starts with a plausible repo-rooted directory (not absolute, not `..`).


def _is_repo_relative(p: str) -> bool:
    if not p:
        return False
    if p.startswith("/") or p.startswith(".."):
        return False
    return "/" in p or "." in p.rsplit("/", 1)[-1]


def _git_log_for_path(pd: Path, path: str) -> dict[str, Any]:
    """Run git log for one path, return commit metadata + line stats.

    Uses --follow so renames are tracked. Returns empty-ish dict when
    nothing matches (path never existed under this name).
    """
    try:
        r = subprocess.run(
            ["git", "-C", str(pd), "log", "--follow",
             "--format=%H|%cI|%s", "--numstat", "--",  path],
            capture_output=True, text=True, check=False, timeout=10,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return {"commit_count": 0, "first_commit": None,
                "last_commit": None, "lines_added": 0, "lines_removed": 0}
    if r.returncode != 0 or not r.stdout.strip():
        return {"commit_count": 0, "first_commit": None,
                "last_commit": None, "lines_added": 0, "lines_removed": 0}

    commits: list[dict[str, str]] = []
    lines_added = 0
    lines_removed = 0
    for line in r.stdout.splitlines():
        if "|" in line and line.count("|") >= 2:
            sha, date, subject = line.split("|", 2)
            commits.append({"sha": sha[:10], "date": date, "subject": subject})
        elif line.strip():
            parts = line.split("\t")
            if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                lines_added += int(parts[0])
                lines_removed += int(parts[1])

    if not commits:
        return {"commit_count": 0, "first_commit": None,
                "last_commit": None, "lines_added": 0, "lines_removed": 0}
    # `git log` returns newest-first
    return {
        "commit_count": len(commits),
        "first_commit": commits[-1],
        "last_commit": commits[0],
        "lines_added": lines_added,
        "lines_removed": lines_removed,
    }


def _path_exists_now(pd: Path, path: str) -> bool:
    try:
        r = subprocess.run(
            ["git", "-C", str(pd), "cat-file", "-e", f"HEAD:{path}"],
            capture_output=True, text=True, check=False, timeout=5,
        )
        return r.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def _resolve_symbol_safely(sym: str) -> bool:
    try:
        import code_graph
        if code_graph.graph_path() is None:
            return False
        if code_graph.resolve_symbol(sym):
            return True
        leaf = sym.rsplit(".", 1)[-1]
        if leaf != sym and code_graph.resolve_symbol(leaf):
            return True
    except Exception:
        return False
    return False


def correlate(subdir: str) -> dict[str, Any]:
    pd = project_dir()
    if pd is None or not is_git_repo():
        return {"error": "not a git repo"}

    base = (pd / subdir).resolve()
    try:
        base.relative_to(pd.resolve())
    except ValueError:
        return {"error": f"path escapes project: {subdir}"}
    if not base.is_dir():
        return {"error": f"not a directory: {subdir}"}

    md_files = sorted(p for p in base.rglob("*.md") if p.is_file())
    if not md_files:
        return {"error": f"no .md files in {subdir}"}

    all_paths: set[str] = set()
    all_symbols: set[str] = set()
    for f in md_files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        all_paths.update(doc_claims.extract_path_claims(text))
        all_symbols.update(doc_claims.extract_symbol_claims(text))

    path_claims: dict[str, dict[str, Any]] = {}
    for path in sorted(all_paths):
        if not _is_repo_relative(path):
            continue
        info = _git_log_for_path(pd, path)
        info["exists_now"] = _path_exists_now(pd, path)
        path_claims[path] = info

    symbol_claims: dict[str, dict[str, Any]] = {}
    for sym in sorted(all_symbols):
        symbol_claims[sym] = {"resolved_in_graph": _resolve_symbol_safely(sym)}

    n_paths = len(path_claims)
    n_paths_with_evidence = sum(1 for v in path_claims.values()
                                if v["commit_count"] > 0)
    n_paths_existing = sum(1 for v in path_claims.values() if v["exists_now"])
    n_syms = len(symbol_claims)
    n_syms_resolved = sum(1 for v in symbol_claims.values()
                          if v["resolved_in_graph"])

    completion: float | None = None
    if n_paths + n_syms > 0:
        # Weight paths and symbols equally
        evidence = n_paths_existing + n_syms_resolved
        completion = round(evidence / (n_paths + n_syms), 2)

    return {
        "subdir": subdir,
        "files_in_plan": [str(f.relative_to(pd)) for f in md_files],
        "path_claims": path_claims,
        "symbol_claims": symbol_claims,
        "summary": {
            "paths_mentioned": n_paths,
            "paths_with_evidence": n_paths_with_evidence,
            "paths_existing_now": n_paths_existing,
            "symbols_mentioned": n_syms,
            "symbols_resolved": n_syms_resolved,
            "completion_estimate": completion,
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    """Compact markdown report. Used by CLI default + MCP tool."""
    if "error" in report:
        return f"_plan_correlate: {report['error']}_"

    s = report["summary"]
    lines: list[str] = []
    lines.append(f"# Plan correlation — `{report['subdir']}`")
    lines.append("")
    lines.append(f"_Files in plan: {len(report['files_in_plan'])} — "
                 f"{', '.join(report['files_in_plan'])}_")
    lines.append("")
    pct = (f"{int(s['completion_estimate'] * 100)}%"
           if s['completion_estimate'] is not None else "n/a")
    lines.append(
        f"**Completion estimate: {pct}**  "
        f"({s['paths_existing_now']}/{s['paths_mentioned']} paths exist, "
        f"{s['symbols_resolved']}/{s['symbols_mentioned']} symbols resolve)"
    )
    lines.append("")

    if report["path_claims"]:
        lines.append("## Paths")
        for path, info in report["path_claims"].items():
            mark = "✓" if info["exists_now"] else "✗"
            cc = info["commit_count"]
            if cc == 0:
                detail = "no commits"
            else:
                lc = info["last_commit"]
                detail = (f"{cc} commits, last: "
                          f"{lc['date'][:10]} ({lc['subject'][:50]})")
            lines.append(f"- {mark} `{path}` — {detail}")
        lines.append("")

    if report["symbol_claims"]:
        lines.append("## Symbols")
        for sym, info in report["symbol_claims"].items():
            mark = "✓" if info["resolved_in_graph"] else "?"
            lines.append(f"- {mark} `{sym}`")
        lines.append("")

    # Verdict hint for the worker
    c = s["completion_estimate"]
    if c is None:
        lines.append("_Verdict: no testable claims — classify by content alone._")
    elif c >= 0.8:
        lines.append("_Verdict: high evidence — ADR `accepted` or `stable` domain._")
    elif c >= 0.4:
        lines.append("_Verdict: partial evidence — ADR `proposed` or mixed lesson._")
    else:
        lines.append("_Verdict: low evidence — treat as lesson "
                     "('we considered this in...'), not authoritative._")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("subdir",
                    help="Planning subdir (project-relative), "
                         "e.g. .planning/auth-rewrite")
    ap.add_argument("--json", action="store_true",
                    help="Machine-readable JSON instead of markdown.")
    args = ap.parse_args()

    report = correlate(args.subdir)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render_markdown(report))
    return 0 if "error" not in report else 1


if __name__ == "__main__":
    sys.exit(main())

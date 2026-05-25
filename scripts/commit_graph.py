"""Behavioural-code-analysis signal: per-file churn and ADR↔commit linkage.

Per Tornhill's Code Maat work — file churn (commits in a window) is a
strong second signal alongside structural in-degree. A hub that's also
hot is high-value; a hub that's been stable for years is safe.

We also surface ADR↔commit linkage: when a commit message mentions an
ADR slug (`decisions/<date>-<slug>` or just `<slug>`), that commit
counts as an implementation of the ADR.
"""
from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

import lib_loader  # noqa: F401
from lib import project_dir

# Module-level cache keyed by (.git/HEAD mtime, query) — cheap invalidation
# when there's new activity.
_CHURN_CACHE: dict[tuple[float, str, int], int] = {}
_ADR_LINKAGE_CACHE: dict[tuple[float, int], dict[str, list[dict]]] = {}


def _head_mtime(pd: Path) -> float:
    head = pd / ".git" / "HEAD"
    try:
        return head.stat().st_mtime
    except OSError:
        return 0.0


def _git(pd: Path, *args: str, timeout: int = 10) -> str:
    try:
        r = subprocess.run(
            ["git", "-C", str(pd), *args],
            capture_output=True, text=True, check=False, timeout=timeout,
        )
        return r.stdout if r.returncode == 0 else ""
    except (subprocess.SubprocessError, FileNotFoundError):
        return ""


def churn(path: str, days: int = 90) -> int:
    """Commits touching `path` (project-relative) in the last `days`.

    `path` is exact — uses `git log --follow -- <path>`. Returns 0 when
    not in a repo or path doesn't exist.
    """
    pd = project_dir()
    if pd is None:
        return 0
    key = (_head_mtime(pd), path, days)
    cached = _CHURN_CACHE.get(key)
    if cached is not None:
        return cached
    since = time.strftime(
        "%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - days * 86400)
    )
    out = _git(pd, "log", "--follow", f"--since={since}",
               "--format=%H", "--", path)
    n = len([line for line in out.splitlines() if line.strip()])
    _CHURN_CACHE[key] = n
    return n


def hotspots(days: int = 90, top: int = 20) -> list[dict]:
    """Top-N files by commit count in the window. One subprocess call.

    Returns: [{path, commits}], descending. Used by `/strata:review`
    and as a tiebreaker in `code_map` ranking.
    """
    pd = project_dir()
    if pd is None:
        return []
    since = time.strftime(
        "%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - days * 86400)
    )
    out = _git(pd, "log", f"--since={since}", "--name-only",
               "--format=", "--no-renames")
    counts: dict[str, int] = {}
    for line in out.splitlines():
        line = line.strip()
        if line:
            counts[line] = counts.get(line, 0) + 1
    return [{"path": p, "commits": c}
            for p, c in sorted(counts.items(), key=lambda kv: -kv[1])[:top]]


_SLUG_RE = re.compile(
    r"decisions/(\d{4}-\d{2}-\d{2}-[a-z0-9._-]+)(?:\.md)?",
    re.IGNORECASE,
)


def adr_implementations(adr_slugs: list[str],
                        limit: int = 500) -> dict[str, list[dict]]:
    """For each ADR slug provided, find recent commits whose message
    mentions it.

    `adr_slugs` is a list of bare slugs (e.g. `2026-05-24-use-postgres`)
    OR full vault paths (e.g. `decisions/2026-05-24-use-postgres.md`) —
    we normalise.

    Returns: {slug: [{sha, date, subject}, ...]} for slugs that had hits.
    One git log call regardless of how many slugs.
    """
    pd = project_dir()
    if pd is None or not adr_slugs:
        return {}

    key = (_head_mtime(pd), limit)
    cache = _ADR_LINKAGE_CACHE.get(key)
    if cache is None:
        out = _git(pd, "log", f"-{limit}", "--format=%H|%cI|%s",
                   timeout=15)
        cache = {}
        for line in out.splitlines():
            if line.count("|") >= 2:
                sha, date, subject = line.split("|", 2)
                for m in _SLUG_RE.finditer(subject):
                    s = m.group(1).lower().rstrip(".md")
                    cache.setdefault(s, []).append({
                        "sha": sha[:10], "date": date, "subject": subject,
                    })
        _ADR_LINKAGE_CACHE[key] = cache

    result: dict[str, list[dict]] = {}
    for raw in adr_slugs:
        slug = raw.lower()
        if "/" in slug:
            slug = slug.rsplit("/", 1)[-1]
        if slug.endswith(".md"):
            slug = slug[:-3]
        if slug in cache:
            result[slug] = cache[slug]
    return result


def commits_since_path_was_written(path: str, since_iso: str) -> int:
    """Count commits touching `path` since `since_iso`. Used by drift
    detection — when a note's `created:` is N months old and the
    code beneath it has churned heavily since, flag it.
    """
    pd = project_dir()
    if pd is None:
        return 0
    out = _git(pd, "log", "--follow", f"--since={since_iso}",
               "--format=%H", "--", path)
    return len([line for line in out.splitlines() if line.strip()])

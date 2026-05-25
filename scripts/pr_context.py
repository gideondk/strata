"""Fetch the current branch's open PR via `gh` and format it.

Shared by `prime-context.py` (SessionStart hook) and the `current_pr` MCP tool.

Degrades gracefully when:
  - `gh` is not on PATH
  - `gh` is not authenticated
  - The branch has no open PR
  - We're not in a git repo

Token budget: ~2 KB for the formatted primer block, ~6 KB for the full
structured response from the MCP tool.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

import lib_loader  # noqa: F401
from lib import current_branch, is_git_repo, project_dir


@dataclass
class PRContext:
    available: bool
    reason: str = ""  # populated when available=False
    number: int = 0
    title: str = ""
    state: str = ""
    body: str = ""
    url: str = ""
    author: str = ""
    requested_reviewers: list[str] | None = None
    labels: list[str] | None = None
    is_draft: bool = False
    comments: list[dict[str, Any]] | None = None
    review_comments: list[dict[str, Any]] | None = None


def _gh_available() -> tuple[bool, str]:
    if shutil.which("gh") is None:
        return False, "gh CLI not installed"
    try:
        r = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0:
            return False, "gh not authenticated (try `gh auth login`)"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False, "gh auth check failed"
    return True, ""


def _gh_json(args: list[str], timeout: float = 10) -> Any:
    pd = project_dir()
    cmd = ["gh", *args]
    r = subprocess.run(
        cmd,
        capture_output=True, text=True, timeout=timeout,
        cwd=str(pd) if pd else None,
    )
    if r.returncode != 0:
        raise RuntimeError(f"gh failed: {r.stderr.strip()}")
    return json.loads(r.stdout) if r.stdout.strip() else None


def fetch_for_current_branch(comment_limit: int = 5,
                              review_comment_limit: int = 10) -> PRContext:
    """Return the current branch's open PR context (or a reason it's absent)."""
    if not is_git_repo():
        return PRContext(available=False, reason="not a git repo")

    ok, why = _gh_available()
    if not ok:
        return PRContext(available=False, reason=why)

    branch = current_branch()
    if branch in ("unknown", "HEAD") or branch.startswith("detached@"):
        return PRContext(available=False, reason="no branch")

    try:
        prs = _gh_json([
            "pr", "list", "--head", branch, "--state", "open",
            "--json", "number,title,state,body,url,author,isDraft,labels,"
                       "comments,reviews",
            "--limit", "1",
        ])
    except Exception as e:
        return PRContext(available=False, reason=f"gh pr list: {e}")

    if not prs:
        return PRContext(available=False, reason=f"no open PR for branch {branch}")

    pr = prs[0]
    comments = pr.get("comments") or []
    reviews = pr.get("reviews") or []

    # Flatten review comments out of `reviews` (top-level reviews carry a body)
    review_blobs: list[dict[str, Any]] = []
    for rv in reviews:
        if rv.get("body"):
            review_blobs.append({
                "author": (rv.get("author") or {}).get("login", "?"),
                "body": rv["body"],
                "state": rv.get("state", ""),
                "createdAt": rv.get("submittedAt") or rv.get("createdAt"),
            })

    return PRContext(
        available=True,
        number=pr["number"],
        title=pr.get("title") or "",
        state=pr.get("state") or "",
        body=pr.get("body") or "",
        url=pr.get("url") or "",
        author=(pr.get("author") or {}).get("login", ""),
        labels=[lbl.get("name") for lbl in (pr.get("labels") or [])
                if lbl.get("name")],
        is_draft=bool(pr.get("isDraft")),
        comments=[
            {
                "author": (c.get("author") or {}).get("login", "?"),
                "body": c.get("body") or "",
                "createdAt": c.get("createdAt"),
            }
            for c in comments[-comment_limit:]
        ],
        review_comments=review_blobs[-review_comment_limit:],
    )


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def _truncate(text: str, n: int) -> str:
    text = text.strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def format_for_primer(pr: PRContext, body_chars: int = 800,
                      comment_chars: int = 200) -> str:
    """A compact, ~2KB primer block. Returns "" when there's no PR."""
    if not pr.available:
        return ""

    out: list[str] = []
    push = out.append
    draft = " (draft)" if pr.is_draft else ""
    push(f"### Open PR #{pr.number} — {pr.title}{draft}")
    meta = [f"by @{pr.author}"] if pr.author else []
    if pr.labels:
        meta.append("labels: " + ", ".join(pr.labels))
    if meta:
        push("_" + "  ·  ".join(meta) + "_")
    push("")

    if pr.body:
        push(_truncate(pr.body, body_chars))
        push("")

    all_comments = (pr.review_comments or []) + (pr.comments or [])
    if all_comments:
        push(f"#### Recent comments ({len(all_comments)})")
        for c in all_comments[-5:]:
            who = c.get("author", "?")
            when = (c.get("createdAt") or "")[:10]
            body = _truncate(c.get("body") or "", comment_chars)
            push(f"- **@{who}** ({when}): {body}")
        push("")

    push(f"_pr url: {pr.url}_")
    return "\n".join(out) + "\n"


def format_full(pr: PRContext) -> str:
    """Detailed format for the MCP tool — no truncation on body, more comments."""
    if not pr.available:
        return f"_(no PR context: {pr.reason})_"

    out: list[str] = []
    push = out.append
    draft = " (draft)" if pr.is_draft else ""
    push(f"# PR #{pr.number}: {pr.title}{draft}")
    if pr.author:
        push(f"_by @{pr.author}_  ·  state: {pr.state}  ·  {pr.url}")
    if pr.labels:
        push(f"_labels: {', '.join(pr.labels)}_")
    push("")

    if pr.body:
        push("## Description")
        push(pr.body)
        push("")

    if pr.review_comments:
        push(f"## Reviews ({len(pr.review_comments)})")
        for c in pr.review_comments:
            push(f"- **@{c['author']}** ({c.get('state','?')}, {c.get('createdAt','')[:10]}):")
            push(f"  {c['body']}")
        push("")

    if pr.comments:
        push(f"## Comments ({len(pr.comments)})")
        for c in pr.comments:
            push(f"- **@{c['author']}** ({c.get('createdAt','')[:10]}):")
            push(f"  {c['body']}")
        push("")

    return "\n".join(out)

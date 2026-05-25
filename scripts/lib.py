"""Shared helpers for Strata plugin scripts.

Stdlib only. No network. No third-party imports anywhere in this plugin.
Every script that needs project paths, git info, or filename helpers imports
from here.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def project_dir() -> Path | None:
    """Repo / project root. Returns None when not running in a project.

    Resolution order:
      1. STRATA_PROJECT_DIR env var (explicit override for bootstrap workers
         and out-of-cwd invocations — set this when calling a write script
         from a directory other than the repo root, e.g. when the plugin's
         own repo is your cwd but you're writing notes for another project).
      2. CLAUDE_PROJECT_DIR (set by Claude Code).
      3. cwd, but only if it looks like a git repo.
    """
    d = (
        os.environ.get("STRATA_PROJECT_DIR")
        or os.environ.get("CLAUDE_PROJECT_DIR")
    )
    if d:
        return Path(d)
    cwd = Path(os.getcwd())
    if (cwd / ".git").exists():
        return cwd
    return None


def vault_root() -> Path:
    """The user's Strata vault — outside any repo, sync'd by the user's
    chosen mechanism (Obsidian Sync, Syncthing, git, iCloud, …).

    Resolution order:
      1. STRATA_VAULT_PATH env var (explicit override, set by user
         shell or the run-python.sh wrapper from userConfig)
      2. CLAUDE_PLUGIN_OPTION_VAULT_PATH (Claude Code auto-export of
         the userConfig value — most common path in production)
      3. ~/StrataVault/ (default)
    """
    raw = (
        os.environ.get("STRATA_VAULT_PATH")
        or os.environ.get("CLAUDE_PLUGIN_OPTION_VAULT_PATH")
    )
    if raw:
        return Path(os.path.expanduser(raw)).resolve()
    return (Path.home() / "StrataVault").resolve()


def repo_name() -> str:
    """Namespace for the current project inside the vault.

    Strategy:
      1. STRATA_REPO_NAME env var (explicit override)
      2. CLAUDE_PLUGIN_OPTION_REPO_NAME (auto-exported userConfig)
      3. git remote URL last path component (so forks/clones agree)
      4. project directory basename
      5. `_default` when not in a project
    """
    override = (
        os.environ.get("STRATA_REPO_NAME")
        or os.environ.get("CLAUDE_PLUGIN_OPTION_REPO_NAME")
    )
    if override and override.strip():
        return _slug(override.strip())

    pd = project_dir()
    if pd is None:
        return "_default"

    # Prefer the remote name (stable across clones) over the directory name.
    remote = _git("config", "--get", "remote.origin.url")
    if remote:
        # Strip .git suffix, take the last path segment
        name = remote.rstrip("/").rsplit("/", 1)[-1]
        if name.endswith(".git"):
            name = name[:-4]
        if name:
            return _slug(name)

    return _slug(pd.name)


def _slug(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", text)
    s = re.sub(r"-+", "-", s).strip("-.")
    return s or "_default"


def memory_dir() -> Path:
    """The repo-scoped memory directory inside the vault.

    `<vault_root>/<repo_name>/`

    All scopes (decisions/, lessons/, domain/, pr-context/) live below this.
    Cross-repo notes live under `<vault_root>/_shared/` and are queried
    separately by the MCP server (not via this function).
    """
    return vault_root() / repo_name()


class UnsafePathError(ValueError):
    """Raised when a path escapes the sandbox or follows a symlink."""


def safe_resolve(rel_or_abs: str | Path, root: Path) -> Path:
    """Resolve a path under `root` safely.

    Rejects:
      - absolute paths
      - traversal (`..`)
      - symlinks anywhere along the resolved path
      - anything resolving outside `root`

    Returns the resolved absolute Path. Raises UnsafePathError if any check
    fails. The path may or may not exist — the caller decides.
    """
    if isinstance(rel_or_abs, str):
        if not rel_or_abs:
            raise UnsafePathError("empty path")
        # Reject absolute via string check first (Path.is_absolute() on the
        # joined result wouldn't catch the user-supplied intent).
        if rel_or_abs.startswith("/") or (len(rel_or_abs) > 1
                                          and rel_or_abs[1] == ":"):
            raise UnsafePathError(f"absolute path refused: {rel_or_abs}")
        p = Path(rel_or_abs)
    else:
        p = rel_or_abs

    if p.is_absolute():
        raise UnsafePathError(f"absolute path refused: {p}")
    if any(part == ".." for part in p.parts):
        raise UnsafePathError(f"traversal refused: {p}")

    # Walk every component of the (root, candidate) path BEFORE resolving,
    # so we can detect symlinks before resolve() silently follows them.
    current = root
    for part in p.parts:
        current = current / part
        if current.is_symlink():
            raise UnsafePathError(f"symlink in path refused: {current.name}")

    root_resolved = root.resolve()
    candidate = (root / p).resolve()

    try:
        candidate.relative_to(root_resolved)
    except ValueError as e:
        raise UnsafePathError(f"escapes sandbox: {p}") from e

    return candidate


def shared_dir() -> Path:
    """Cross-repo shared notes — vocabulary that spans projects."""
    return vault_root() / "_shared"


def memory_display() -> str:
    """Short display path for log messages — `<repo>/` inside the vault."""
    return f"{repo_name()}/"


def plugin_data_dir() -> Path:
    """Per-plugin private data dir managed by Claude Code. Falls back to a
    .strata/ inside the project for off-Claude runs (tests, manual calls)."""
    d = os.environ.get("CLAUDE_PLUGIN_DATA")
    if d:
        return Path(d)
    pd = project_dir()
    if pd is not None:
        return pd / ".strata"
    return Path.cwd() / ".strata"


def plugin_root() -> Path:
    """Plugin install dir. Falls back to the dir containing this file's parent."""
    d = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if d:
        return Path(d)
    return Path(__file__).resolve().parent.parent


def _git(*args: str, check: bool = False) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(project_dir()), *args],
            capture_output=True, text=True, check=check
        )
        return out.stdout.strip()
    except FileNotFoundError:
        return ""


def current_branch() -> str:
    """Best-effort current branch name.

    Handles three awkward cases:
    - Fresh repo with no commits → `rev-parse --abbrev-ref HEAD` returns "HEAD",
      so we fall back to `git symbolic-ref --short HEAD`.
    - Detached HEAD → returns "HEAD"; we surface the short SHA instead.
    - Not a repo → "unknown".
    """
    if not is_git_repo():
        return "unknown"
    b = _git("rev-parse", "--abbrev-ref", "HEAD")
    if b and b != "HEAD":
        return b
    sym = _git("symbolic-ref", "--short", "HEAD")
    if sym:
        return sym
    sha = _git("rev-parse", "--short", "HEAD")
    return f"detached@{sha}" if sha else "unknown"


def is_git_repo() -> bool:
    return _git("rev-parse", "--is-inside-work-tree") == "true"


def branch_slug(branch: str) -> str:
    """Stable filesystem slug for a branch name.

    `feat/user-auth` → `feat-user-auth`, `release/v1.2` → `release-v1.2`.
    """
    s = branch.replace("/", "-").replace("\\", "-")
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "unknown"


def safe_slug(text: str, max_len: int = 48) -> str:
    """Filename-safe slug. Cuts on word boundary so we don't get
    truncations like `legacy.vi` from `legacy.visitsacl-service`."""
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", text.lower())
    s = re.sub(r"-+", "-", s).strip("-")
    if len(s) <= max_len:
        return s or "note"
    cut = s[:max_len]
    # Slice at the rightmost separator (`-` or `.`) before the limit,
    # but only if it's past the halfway mark — otherwise we'd shorten
    # too aggressively. Strip any trailing punctuation.
    last_sep = max(cut.rfind("-"), cut.rfind("."))
    if last_sep > max_len // 2:
        cut = cut[:last_sep]
    cut = cut.rstrip(".-")
    return cut or "note"


def author_name() -> str:
    n = _git("config", "user.name")
    return n or os.environ.get("USER", "unknown")


def author_email() -> str:
    return _git("config", "user.email") or ""


def author_initials() -> str:
    """Two-or-three-letter initials from `user.name`. Falls back to login."""
    name = author_name()
    parts = [p for p in re.split(r"\s+", name.strip()) if p]
    if not parts:
        return os.environ.get("USER", "anon")[:3].lower()
    if len(parts) == 1:
        return parts[0][:3].lower()
    initials = "".join(p[0] for p in parts if p and p[0].isalpha())[:3]
    return (initials or parts[0][:3]).lower()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def stamp_minute(dt: datetime | None = None) -> str:
    """`YYYY-MM-DD-HHMM` — used in pr-context filenames."""
    return (dt or now_utc()).strftime("%Y-%m-%d-%H%M")


def today() -> str:
    return now_utc().strftime("%Y-%m-%d")


def first_heading(path: Path) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("# "):
                    return line[2:].strip()
    except OSError:
        pass
    return ""


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def pr_context_dir(slug: str | None = None) -> Path:
    return memory_dir() / "pr-context" / (slug or branch_slug(current_branch()))


def lessons_dir() -> Path:
    """Retrospective notes — durable, not branch-scoped.

    Bootstrap-extracted "we considered this in 2026..." content lands
    here, not in `pr-context/<branch>/` which is for in-flight branch
    work. Historical knowledge has no current branch.
    """
    return memory_dir() / "lessons"


def write_text(path: Path, content: str) -> None:
    ensure_dir(path.parent)
    path.write_text(content, encoding="utf-8")


def info(msg: str) -> None:
    print(f"[strata] {msg}", file=sys.stderr)


def emit(msg: str) -> None:
    """Plain stdout — used by SessionStart hook to inject context."""
    sys.stdout.write(msg)
    if not msg.endswith("\n"):
        sys.stdout.write("\n")

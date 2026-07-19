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


def vault_sync_mode() -> str:
    """How the vault is version-controlled: `'git'` or `'manual'` (default).

    In `'git'` mode, each confirmed write is committed to the vault's own
    git repo — locally, never over the network. Pull/push is never
    automatic; only the user-invoked `strata sync` touches a remote. In
    `'manual'` mode (the default), Strata writes plain files and leaves
    all version control to whatever the user already uses (Obsidian Sync,
    Syncthing, iCloud, or their own git commits).
    """
    raw = (
        os.environ.get("STRATA_VAULT_SYNC")
        or os.environ.get("CLAUDE_PLUGIN_OPTION_VAULT_SYNC")
        or "manual"
    ).strip().lower()
    return "git" if raw == "git" else "manual"


def git_remote() -> str:
    """Remote name that `strata sync` pulls from / pushes to. Empty string
    means use the vault repo's own configured upstream (origin / tracking
    branch)."""
    return (
        os.environ.get("STRATA_GIT_REMOTE")
        or os.environ.get("CLAUDE_PLUGIN_OPTION_GIT_REMOTE")
        or ""
    ).strip()


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


# --- Vault git backend -------------------------------------------------------
# Optional: when `vault_sync_mode() == "git"` the vault directory is itself a
# git repo, and each confirmed write is committed locally. All of the below is
# LOCAL ONLY — no fetch, pull, or push. The network path lives exclusively in
# `strata sync`, which the user invokes by hand. This keeps the "nothing in the
# runtime path opens a socket" guarantee intact even with git storage enabled.


def _vault_git(*args: str) -> subprocess.CompletedProcess | None:
    """Run a git command against the vault root. Returns None if git is
    missing. Never raises.

    LC_ALL=C pins git's messages to English: callers (git-sync, doctor)
    branch on strings like "couldn't find remote ref", which are gettext-
    translated under a user locale and would break the match."""
    try:
        return subprocess.run(
            ["git", "-C", str(vault_root()), *args],
            capture_output=True, text=True,
            env={**os.environ, "LC_ALL": "C"},
        )
    except (FileNotFoundError, OSError):
        return None


def vault_is_git_repo() -> bool:
    r = _vault_git("rev-parse", "--is-inside-work-tree")
    return bool(r and r.returncode == 0 and r.stdout.strip() == "true")


# Regenerable or machine-local artifacts that must never be committed/synced:
# INDEX.md is rewritten on every save (pure churn + a conflict magnet), the
# bootstrap state is per-machine onboarding SHA tracking, and .obsidian/ is
# app-local UI state.
_VAULT_GITIGNORE = (
    "# Strata — regenerable / machine-local artifacts. Do not sync these.\n"
    "INDEX.md\n"
    "index.html\n"
    ".bootstrap-state.json\n"
    ".obsidian/\n"
    ".DS_Store\n"
)
# Append-only audit logs union-merge so two people's writes never conflict.
# `.audit.log` is named explicitly — it's JSONL content without the extension
# (forget.py appends to it), so the glob alone would miss the one file this
# guarantee exists for.
_VAULT_GITATTRIBUTES = (
    "# Append-only audit logs: union-merge so concurrent writes never "
    "conflict.\n"
    "*.jsonl merge=union\n"
    ".audit.log merge=union\n"
)


def scaffold_vault_git_files() -> list[str]:
    """Write `.gitignore` + `.gitattributes` at the vault root. Idempotent —
    existing files are left untouched. Returns the names actually created."""
    root = vault_root()
    ensure_dir(root)
    created: list[str] = []
    for name, body in ((".gitignore", _VAULT_GITIGNORE),
                       (".gitattributes", _VAULT_GITATTRIBUTES)):
        p = root / name
        if not p.exists():
            p.write_text(body, encoding="utf-8")
            created.append(name)
    return created


def vault_git_autocommit(paths, message: str) -> bool:
    """Commit the given vault paths locally when the vault is git-backed.

    Best-effort and LOCAL ONLY (no push): a git failure or a non-git vault
    never breaks the write it follows. A no-op (returns False) unless
    `vault_sync_mode()` is `"git"` and the vault is a git repo. Paths that
    resolve outside the vault are refused. Returns True iff a commit landed.
    """
    if vault_sync_mode() != "git" or not vault_is_git_repo():
        return False
    root = vault_root()
    rels: list[str] = []
    for p in paths:
        try:
            # strict=False: a `forget` move leaves the source path gone, but
            # we still want to stage its deletion.
            rels.append(str(Path(p).resolve().relative_to(root)))
        except (ValueError, OSError):
            return False  # outside the vault — refuse rather than guess
    if not rels:
        return False
    add = _vault_git("add", "--", *rels)
    if add is None or add.returncode != 0:
        detail = (add.stderr.strip().splitlines() or ["git add failed"])[0] \
            if add is not None else "git unavailable"
        info(f"⚠ vault git: note NOT committed — {detail}")
        return False
    # Pathspec-limited commit: captures only these paths regardless of what
    # else is staged, so a concurrent write from another repo's session isn't
    # swept into this commit. A nothing-to-commit exit is a benign False.
    commit = _vault_git("commit", "-m", message, "--", *rels)
    if commit is not None and commit.returncode == 0:
        return True
    # The write itself succeeded, so never raise — but a hard commit failure
    # (no git identity is the classic) must be visible, or the user believes
    # the vault is versioned while nothing ever lands in history.
    out = ((commit.stdout + commit.stderr) if commit is not None else "").lower()
    if "nothing to commit" not in out and "nothing added" not in out:
        first = (commit.stderr.strip() or commit.stdout.strip()).splitlines() \
            if commit is not None else []
        detail = first[0] if first else "git commit failed"
        info(f"⚠ vault git: note saved but NOT committed — {detail}")
        if "please tell me who you are" in out or "auto-detect" in out:
            info("  fix: git -C <vault> config user.email you@example.com "
                 "(and user.name), then re-save or run /strata:sync")
    return False


def origin_branch() -> str | None:
    """The branch a note is authored on, for provenance. Returns None when
    there's no usable branch (not a repo, detached HEAD, or fresh repo) so
    callers can simply skip the `branch:` frontmatter field."""
    if not is_git_repo():
        return None
    b = current_branch()
    if b in ("unknown", "HEAD") or b.startswith("detached@"):
        return None
    return b


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

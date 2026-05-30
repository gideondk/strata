"""SQLite FTS5 + supersession + wikilink graph over the Strata vault.

Lives at ${CLAUDE_PLUGIN_DATA}/index.db. Never synced, rebuilt from disk.
Incremental: re-tokenises only files whose mtime/size changed."""
from __future__ import annotations

import contextlib
import sqlite3
from collections.abc import Iterable, Iterator
from pathlib import Path

import frontmatter

import lib_loader  # noqa: F401
from lib import (
    UnsafePathError,
    branch_slug,
    ensure_dir,
    first_heading,
    memory_dir,
    plugin_data_dir,
    safe_resolve,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    path        TEXT PRIMARY KEY,
    mtime       REAL NOT NULL,
    size        INTEGER NOT NULL,
    title       TEXT,
    status      TEXT,
    kind        TEXT,
    scope       TEXT,
    branch      TEXT,
    indexed_at  TEXT,
    relevance   REAL DEFAULT 1.0
);

CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(
    path UNINDEXED,
    title,
    body,
    scope UNINDEXED,
    branch UNINDEXED,
    tokenize = "unicode61 remove_diacritics 2"
);

-- Decision lifecycle: each row is one supersession edge.
-- `successor` supersedes `predecessor`.
CREATE TABLE IF NOT EXISTS supersedes (
    successor    TEXT NOT NULL,
    predecessor  TEXT NOT NULL,
    PRIMARY KEY (successor, predecessor)
);

-- Wikilink graph: src links to dst (resolved to vault-relative path or
-- the raw target string when unresolved).
CREATE TABLE IF NOT EXISTS links (
    src         TEXT NOT NULL,
    dst         TEXT NOT NULL,
    resolved    INTEGER NOT NULL,
    PRIMARY KEY (src, dst)
);

-- Inverse index: note → source-code file(s) it references. Read from
-- each note's `source_file:` frontmatter (string OR YAML list). Powers
-- the SessionStart primer's "files with recent context" section and
-- any future "what notes touch this file?" lookups.
CREATE TABLE IF NOT EXISTS source_files (
    path        TEXT NOT NULL,  -- note path, vault-relative
    source_file TEXT NOT NULL,  -- referenced source file path
    PRIMARY KEY (path, source_file)
);

CREATE INDEX IF NOT EXISTS files_scope ON files(scope);
CREATE INDEX IF NOT EXISTS files_branch ON files(branch);
CREATE INDEX IF NOT EXISTS files_status ON files(status);
CREATE INDEX IF NOT EXISTS files_relevance ON files(relevance);
CREATE INDEX IF NOT EXISTS supersedes_predecessor ON supersedes(predecessor);
CREATE INDEX IF NOT EXISTS links_dst ON links(dst);
CREATE INDEX IF NOT EXISTS source_files_by_src ON source_files(source_file);
"""

# Bump when the table layout changes. The index is disposable (rebuilt from
# disk by reindex), so a mismatch drops every table and lets the next reindex
# repopulate — no hand-written migrations needed.
SCHEMA_VERSION = 2

_TABLES = ("files", "fts", "supersedes", "links", "source_files")


def db_path() -> Path:
    d = plugin_data_dir()
    ensure_dir(d)
    return d / "index.db"


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create tables if absent; on a schema-version mismatch, drop every table
    and recreate. The index is disposable (rebuilt from disk by reindex), so a
    version bump needs no hand-written migration. Runs in autocommit, before any
    explicit write transaction. On a healthy DB this is a no-op `CREATE ... IF
    NOT EXISTS` and takes no write lock."""
    mismatch = conn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION
    if mismatch:
        for table in _TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.executescript(SCHEMA)
    if mismatch:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


@contextlib.contextmanager
def connect(write: bool = False) -> Iterator[sqlite3.Connection]:
    """Open the index. Pass `write=True` for any path that mutates rows.

    We run in autocommit (`isolation_level=None`) and grab the write lock up
    front with `BEGIN IMMEDIATE` on write paths. Python's default DEFERRED
    transaction only takes the write lock on the first write statement — so a
    read-then-write that loses a race to another writer returns SQLITE_BUSY
    *immediately*, ignoring busy_timeout. IMMEDIATE makes busy_timeout actually
    do its job. Read paths stay in autocommit and never block a writer.

    index.db is plugin-data-local (never synced), so WAL's shared-memory file
    is safe."""
    conn = sqlite3.connect(db_path(), isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(
            "PRAGMA journal_mode=WAL;"
            "PRAGMA synchronous=NORMAL;"
            "PRAGMA busy_timeout=5000;"
        )
        _ensure_schema(conn)
        if write:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.execute("COMMIT")
            except BaseException:
                with contextlib.suppress(sqlite3.Error):
                    conn.execute("ROLLBACK")
                raise
        else:
            yield conn
    finally:
        conn.close()


def _classify(path: Path) -> tuple[str, str | None]:
    """Return (scope, branch) for a memory file."""
    mem = memory_dir()
    try:
        rel = path.relative_to(mem)
    except ValueError:
        return ("other", None)
    parts = rel.parts
    if not parts:
        return ("root", None)
    scope = parts[0]
    branch = parts[1] if scope == "pr-context" and len(parts) > 1 else None
    return (scope, branch)


def _iter_memory_md() -> Iterator[Path]:
    """Walk all *.md under the vault, skipping symlinks (security) and
    build-output dirs (perf + signal-to-noise).

    Sub-symlinks could exfiltrate files outside the vault when we index +
    serve their content via the MCP, so we drop them silently.

    `graphify/` is excluded: it's a per-node markdown dump regenerated
    from `graphify-out/graph.json` (treat-as-build-output, per the
    graphify SKILL doc). On a real codebase it produces thousands of
    minimal notes that dwarf the actual memory ~40:1, slow cold reindex
    proportionally, and pollute `memory_search` results.
    """
    mem = memory_dir()
    if not mem.exists():
        return
    for p in mem.rglob("*.md"):
        if p.name in ("README.md", "INDEX.md"):
            continue
        # Reject if this path or any ancestor up to `mem` is a symlink.
        if _has_symlink_ancestor(p, mem):
            continue
        # Skip build-output dirs. `graphify/` is the only one today; the
        # tuple is here so other generated dirs can join the list cheaply.
        try:
            rel_parts = p.relative_to(mem).parts
        except ValueError:
            continue
        if rel_parts and rel_parts[0] in _BUILD_OUTPUT_DIRS:
            continue
        yield p


# Auto-regenerated dirs whose markdown is build output rather than
# user-authored memory. Indexing them is wasteful and pollutes search.
_BUILD_OUTPUT_DIRS: frozenset[str] = frozenset({"graphify"})


def _has_symlink_ancestor(target: Path, root: Path) -> bool:
    """Return True if `target` (or any path component between `root` and
    `target`) is a symlink. Used to guarantee the indexer never follows a
    symlink out of the vault."""
    try:
        rel = target.relative_to(root)
    except ValueError:
        return True
    current = root
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _purge(conn: sqlite3.Connection, rel: str) -> None:
    """Drop every index row for one note path."""
    conn.execute("DELETE FROM files WHERE path = ?", (rel,))
    conn.execute("DELETE FROM fts WHERE path = ?", (rel,))
    conn.execute("DELETE FROM supersedes WHERE successor = ?", (rel,))
    conn.execute("DELETE FROM links WHERE src = ?", (rel,))
    conn.execute("DELETE FROM source_files WHERE path = ?", (rel,))


def _resolve_branch(meta: dict, path_branch: str | None) -> str | None:
    """Branch a note belongs to. pr-context trusts its folder slug; other
    scopes fall back to the `branch:` provenance frontmatter (slugified to
    match), so a decision authored on a branch is still attributable."""
    if path_branch:
        return path_branch
    fm = str(meta.get("branch") or "").strip()
    if fm and fm not in ("(no-repo)", "unknown", "HEAD") and not fm.startswith("detached@"):
        return branch_slug(fm)
    return None


_CORRUPTION_MARKERS = (
    "malformed", "not a database", "file is encrypted",
    "disk image is malformed", "database corruption",
)


def _is_corruption(exc: Exception) -> bool:
    return any(m in str(exc).lower() for m in _CORRUPTION_MARKERS)


def _discard_index() -> None:
    """Delete index.db (+ its WAL/SHM sidecars). Safe: the vault on disk is the
    source of truth, so the next reindex rebuilds everything from scratch."""
    base = str(db_path())
    for suffix in ("", "-wal", "-shm"):
        with contextlib.suppress(OSError):
            Path(base + suffix).unlink()


def reindex(force: bool = False) -> dict:
    """Incremental reindex, self-healing. The index is a disposable cache, so a
    corrupt/unreadable DB is recoverable: discard it and rebuild from disk
    rather than surfacing a SQLite error to the user."""
    try:
        return _reindex(force)
    except sqlite3.DatabaseError as e:
        if not _is_corruption(e):
            raise
        _discard_index()
        return _reindex(True)


def _reindex(force: bool = False) -> dict:
    """Incremental reindex. Returns counts."""
    mem = memory_dir()
    if not mem.exists():
        return {"indexed": 0, "removed": 0, "unchanged": 0, "errors": 0}

    indexed = removed = unchanged = errors = 0

    with connect(write=True) as conn:
        # Build a quick lookup of what's in the DB
        existing: dict[str, tuple[float, int]] = {
            row["path"]: (row["mtime"], row["size"])
            for row in conn.execute("SELECT path, mtime, size FROM files")
        }
        on_disk: set[str] = set()

        for path in _iter_memory_md():
            try:
                stat = path.stat()
            except OSError:
                errors += 1
                continue
            rel = path.relative_to(mem).as_posix()
            on_disk.add(rel)

            prev = existing.get(rel)
            if (not force) and prev and prev[0] == stat.st_mtime and prev[1] == stat.st_size:
                unchanged += 1
                continue

            try:
                raw = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                # Unreadable now — purge any stale row rather than leaving the
                # old content cached as if it were still current.
                errors += 1
                _purge(conn, rel)
                continue

            try:
                post = frontmatter.loads(raw)
                meta = post.metadata or {}
                body_only = post.content
            except Exception:
                # Malformed frontmatter — fall back to the full file content
                meta = {}
                body_only = raw

            title = (
                str(meta.get("title") or "").strip()
                or str(meta.get("topic") or "").strip()
                or first_heading(path)
                or path.stem
            )
            status = str(meta.get("status") or "").strip() or None
            kind = str(meta.get("kind") or "").strip() or None
            scope, path_branch = _classify(path)
            branch = _resolve_branch(meta, path_branch)

            _purge(conn, rel)

            conn.execute(
                "INSERT INTO files(path, mtime, size, title, status, kind, "
                "scope, branch, indexed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
                (rel, stat.st_mtime, stat.st_size, title, status, kind,
                 scope, branch),
            )
            conn.execute(
                "INSERT INTO fts(path, title, body, scope, branch) VALUES (?, ?, ?, ?, ?)",
                (rel, title, body_only, scope, branch or ""),
            )

            # Supersession edges from the `supersedes:` frontmatter list
            for pred in _as_path_list(meta.get("supersedes")):
                resolved = _resolve_decision_ref(mem, pred)
                conn.execute(
                    "INSERT OR IGNORE INTO supersedes(successor, predecessor) "
                    "VALUES (?, ?)",
                    (rel, resolved or pred),
                )

            # Wikilink graph from the body
            for raw_target in _extract_wikilinks(body_only):
                resolved = _resolve_link(mem, raw_target)
                conn.execute(
                    "INSERT OR IGNORE INTO links(src, dst, resolved) "
                    "VALUES (?, ?, ?)",
                    (rel, resolved or raw_target, 1 if resolved else 0),
                )

            # Inverse note→source-file index from `source_file:`
            # frontmatter. Accepts scalar or list; trims and skips
            # empties.
            for sf in _as_path_list(meta.get("source_file")):
                sf_clean = sf.strip()
                if sf_clean:
                    conn.execute(
                        "INSERT OR IGNORE INTO source_files(path, source_file) "
                        "VALUES (?, ?)",
                        (rel, sf_clean),
                    )

            indexed += 1

        # Remove deleted files
        for rel in set(existing) - on_disk:
            _purge(conn, rel)
            removed += 1

        # Compute relevance per file from cheap heuristics:
        # - base 1.0
        # - +0.4 if last touched in 30 days, +0.2 if 90 days
        # - +0.1 per incoming link, capped at +0.5
        # - -0.8 if status in (invalidated, superseded, deprecated)
        # SQLite-only — no Python pass over the tree.
        # Discrete statements (not executescript) so they run inside this
        # write transaction — executescript would implicitly COMMIT mid-reindex.
        import time as _t
        now_ts = _t.time()
        d30 = now_ts - 30 * 86400
        d90 = now_ts - 90 * 86400
        conn.execute("UPDATE files SET relevance = 1.0")
        conn.execute(
            "UPDATE files SET relevance = relevance + 0.4 WHERE mtime >= ?",
            (d30,),
        )
        conn.execute(
            "UPDATE files SET relevance = relevance + 0.2 "
            "WHERE mtime >= ? AND mtime < ?",
            (d90, d30),
        )
        conn.execute(
            "UPDATE files SET relevance = relevance - 0.8 "
            "WHERE status IN ('invalidated', 'superseded', 'deprecated')"
        )
        conn.execute(
            "UPDATE files SET relevance = relevance + ("
            "  SELECT MIN(0.5, 0.1 * COUNT(*)) FROM links "
            "  WHERE links.dst = files.path AND links.resolved = 1) "
            "WHERE EXISTS ("
            "  SELECT 1 FROM links "
            "  WHERE links.dst = files.path AND links.resolved = 1)"
        )

    return {"indexed": indexed, "removed": removed,
            "unchanged": unchanged, "errors": errors}


# ---------------------------------------------------------------------------
# Reference resolution + wikilink extraction
# ---------------------------------------------------------------------------


import re as _re  # noqa: E402  -- intentional bottom-of-file utility import

_WIKILINK_RE = _re.compile(r"\[\[([^\]\|#]+)(?:\|[^\]]+)?\]\]")
_FENCED_CODE_RE = _re.compile(r"```[\s\S]*?```|~~~[\s\S]*?~~~", _re.MULTILINE)
_INLINE_CODE_RE = _re.compile(r"`[^`\n]+`")


def _extract_wikilinks(text: str) -> list[str]:
    """Pull `[[target]]` or `[[target|alias]]` from markdown body.

    Code-block aware: strips fenced (```/~~~) and inline-code spans first so
    wikilinks inside code samples don't become edges."""
    stripped = _FENCED_CODE_RE.sub("", text)
    stripped = _INLINE_CODE_RE.sub("", stripped)
    return [m.group(1).strip() for m in _WIKILINK_RE.finditer(stripped)
            if m.group(1).strip()]


def _as_path_list(value) -> list[str]:
    """Coerce a frontmatter field into a list of path-like strings.

    Accepts None | str | list[str] | list[dict{ref|path}].
    """
    if not value:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    out: list[str] = []
    for v in value:
        if isinstance(v, str) and v.strip():
            out.append(v.strip())
        elif isinstance(v, dict):
            ref = v.get("ref") or v.get("path") or v.get("slug")
            if isinstance(ref, str) and ref.strip():
                out.append(ref.strip())
    return out


def _resolve_decision_ref(mem: Path, ref: str) -> str | None:
    """Resolve a `supersedes` reference to a vault-relative path.

    Accepts:
      - vault-relative path (`decisions/2026-05-20-foo.md`)
      - bare filename (`2026-05-20-foo.md`)
      - bare slug (`2026-05-20-foo`)
    """
    candidates = [
        ref,
        ref if ref.endswith(".md") else f"{ref}.md",
        f"decisions/{ref}",
        f"decisions/{ref}.md" if not ref.endswith(".md") else f"decisions/{ref}",
    ]
    for c in candidates:
        p = (mem / c).resolve()
        try:
            p.relative_to(mem.resolve())
        except ValueError:
            continue
        if p.exists():
            return p.relative_to(mem).as_posix()
    return None


def _resolve_link(mem: Path, target: str) -> str | None:
    """Resolve a `[[wikilink]]` target to a vault-relative path.

    Wikilinks are by-name (Obsidian convention). We search the vault for any
    file whose stem matches the target. First match wins (Obsidian's rule).
    """
    target = target.strip()
    if not target:
        return None
    # Direct path attempt first
    p = (mem / (target if target.endswith(".md") else f"{target}.md")).resolve()
    try:
        rel = p.relative_to(mem.resolve())
        if p.exists():
            return rel.as_posix()
    except ValueError:
        pass
    # By-stem search
    stem = target.removesuffix(".md")
    for candidate in mem.rglob(f"{stem}.md"):
        if candidate.name in ("README.md", "INDEX.md"):
            continue
        return candidate.relative_to(mem).as_posix()
    return None


# ---------------------------------------------------------------------------
# Decision lifecycle queries
# ---------------------------------------------------------------------------


def superseded_paths() -> set[str]:
    """Paths that have been superseded by some other decision."""
    with connect() as conn:
        return {row["predecessor"]
                for row in conn.execute("SELECT predecessor FROM supersedes")}


def decision_chain(rel_path: str) -> dict:
    """Return the predecessor / successor chains for a decision.

    `predecessors` is what this decision supersedes (older).
    `successors` is what supersedes this decision (newer).
    """
    with connect() as conn:
        predecessors = [row["predecessor"] for row in conn.execute(
            "SELECT predecessor FROM supersedes WHERE successor = ? ORDER BY predecessor",
            (rel_path,),
        )]
        successors = [row["successor"] for row in conn.execute(
            "SELECT successor FROM supersedes WHERE predecessor = ? ORDER BY successor",
            (rel_path,),
        )]
        # Hydrate titles for nicer output
        def _title(p: str) -> str:
            row = conn.execute("SELECT title FROM files WHERE path = ?",
                               (p,)).fetchone()
            return row["title"] if row else p
        return {
            "path": rel_path,
            "title": _title(rel_path),
            "predecessors": [{"path": p, "title": _title(p)} for p in predecessors],
            "successors": [{"path": s, "title": _title(s)} for s in successors],
        }


def link_graph(rel_path: str) -> dict:
    """Return outgoing + incoming wikilink edges for a path."""
    with connect() as conn:
        outgoing = [
            {"path": row["dst"], "resolved": bool(row["resolved"])}
            for row in conn.execute(
                "SELECT dst, resolved FROM links WHERE src = ? ORDER BY dst",
                (rel_path,),
            )
        ]
        incoming = [row["src"] for row in conn.execute(
            "SELECT src FROM links WHERE dst = ? ORDER BY src",
            (rel_path,),
        )]
        return {
            "path": rel_path,
            "references": outgoing,
            "referenced_by": incoming,
        }


# ---------------------------------------------------------------------------
# Review / vault-health queries
# ---------------------------------------------------------------------------


def stale_decisions(stale_days: int = 14) -> list[dict]:
    """ADRs stuck in `proposed` longer than `stale_days` ago by mtime.

    Returns rows: {path, title, status, age_days}. Oldest first.
    """
    import time
    cutoff = time.time() - stale_days * 86400
    with connect() as conn:
        rows = conn.execute(
            "SELECT path, title, status, mtime FROM files "
            "WHERE scope = 'decisions' AND status = 'proposed' "
            "AND mtime < ? ORDER BY mtime",
            (cutoff,),
        ).fetchall()
        now = time.time()
        return [
            {
                "path": r["path"],
                "title": r["title"],
                "status": r["status"],
                "age_days": int((now - r["mtime"]) // 86400),
            }
            for r in rows
        ]


def orphan_notes(scope: str = "domain") -> list[dict]:
    """Notes in `scope` with no incoming or outgoing wikilinks.

    Orphans are usually a smell — either the note isn't useful, or it's
    missing the links that would put it on the map. Defaults to domain
    notes (where orphan-ness is a real signal).
    """
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT f.path, f.title FROM files f
            WHERE f.scope = ?
              AND NOT EXISTS (SELECT 1 FROM links l WHERE l.src = f.path)
              AND NOT EXISTS (SELECT 1 FROM links l WHERE l.dst = f.path)
            ORDER BY f.path
            """,
            (scope,),
        ).fetchall()
        return [{"path": r["path"], "title": r["title"]} for r in rows]


def files_missing_frontmatter(scope: str | None = None) -> list[dict]:
    """Files where title and status came from fallback (filename/heading),
    indicating either no frontmatter or no required fields."""
    with connect() as conn:
        if scope:
            rows = conn.execute(
                "SELECT path, title FROM files WHERE scope = ? "
                "AND (status IS NULL OR status = '') ORDER BY path",
                (scope,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT path, title, scope FROM files "
                "WHERE status IS NULL OR status = '' ORDER BY scope, path",
            ).fetchall()
        return [dict(r) for r in rows]


def unresolved_links() -> list[dict]:
    """Wikilinks that point at notes that don't exist. Source of typos."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT src, dst FROM links WHERE resolved = 0 ORDER BY src, dst",
        ).fetchall()
        return [dict(r) for r in rows]


def vault_summary() -> dict:
    """Aggregate counts + sizes across all indexed notes. Cheap to call —
    one SQL query, no filesystem walks. Used by the SessionStart primer
    to compute skim-vs-full-read token economics."""
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS notes, COALESCE(SUM(size), 0) AS bytes FROM files"
        ).fetchone()
        return {
            "notes": int(row["notes"] or 0),
            "bytes": int(row["bytes"] or 0),
        }


def source_file_index(limit: int = 6) -> list[dict]:
    """Inverse index: top source-code files by note-reference count.

    Returns up to `limit` entries, each `{source_file, note_count,
    latest_mtime, notes: [{path, title, kind, scope}, ...]}`. The notes
    list is sorted most-recent-first and capped at 5 per file (callers
    typically render fewer; the cap protects against pathological
    fan-out).
    """
    with connect() as conn:
        ranked = conn.execute(
            """
            SELECT
                sf.source_file              AS source_file,
                COUNT(*)                    AS note_count,
                MAX(f.mtime)                AS latest_mtime
            FROM source_files sf
            JOIN files f ON f.path = sf.path
            WHERE COALESCE(f.status, '') NOT IN ('auto', 'invalidated')
            GROUP BY sf.source_file
            ORDER BY note_count DESC, latest_mtime DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        result: list[dict] = []
        for r in ranked:
            notes = conn.execute(
                """
                SELECT f.path AS path, f.title AS title,
                       f.kind AS kind, f.scope AS scope
                FROM source_files sf
                JOIN files f ON f.path = sf.path
                WHERE sf.source_file = ?
                  AND COALESCE(f.status, '') NOT IN ('auto', 'invalidated')
                ORDER BY f.mtime DESC
                LIMIT 5
                """,
                (r["source_file"],),
            ).fetchall()
            result.append({
                "source_file":  r["source_file"],
                "note_count":   int(r["note_count"]),
                "latest_mtime": float(r["latest_mtime"] or 0.0),
                "notes":        [dict(n) for n in notes],
            })
        return result


def _safe_match(terms: Iterable[str], match_all: bool = True) -> str:
    """Build a safe FTS5 MATCH expression from user terms.

    Escapes quotes; joins with AND (all terms required) or OR (any term) per
    `match_all`. Phrases stay phrases if quoted.
    """
    clean: list[str] = []
    for t in terms:
        t = t.replace('"', '""').strip()
        if not t:
            continue
        clean.append(f'"{t}"')
    if not clean:
        return ""
    return (" AND " if match_all else " OR ").join(clean)


def search(
    terms: Iterable[str],
    scope: str | None = None,
    branch: str | None = None,
    limit: int = 20,
    offset: int = 0,
    include_invalidated: bool = False,
    match_all: bool = True,
) -> tuple[list[dict], int]:
    """Run an FTS query and return (page_of_rows, total_count).

    Pagination model: stable ORDER BY (bm25 rank, then path tiebreak),
    LIMIT/OFFSET. We also return the total count so the caller can build a
    next-cursor or display "showing N of M".

    `status = 'invalidated'` notes are filtered out by default — they
    stay readable + indexable but don't pollute search. Opt in with
    `include_invalidated=True` to see them (e.g. for audit / review).

    `status = 'auto'` notes (the staged auto-capture lane) are ALWAYS excluded
    from recall — they're quarantined unreviewed content and must not be served
    as canonical truth until a human promotes them (removes the flag). They
    surface only in the review queue (`/strata:dashboard`).
    """
    match = _safe_match(terms, match_all=match_all)
    if not match:
        return [], 0

    where = ["fts MATCH ?"]
    base_params: list = [match]
    if scope and scope != "all":
        where.append("scope = ?")
        base_params.append(scope)
    if branch:
        where.append("branch = ?")
        base_params.append(branch)
    # Quarantine unreviewed auto-notes always; hide invalidated unless opted in.
    excluded = ["'auto'"]
    if not include_invalidated:
        excluded.append("'invalidated'")
    where.append(
        "fts.path NOT IN (SELECT path FROM files "
        f"WHERE status IN ({', '.join(excluded)}))"
    )

    where_sql = " AND ".join(where)

    count_sql = f"SELECT COUNT(*) AS n FROM fts WHERE {where_sql}"
    page_sql = (
        "SELECT path, title, scope, branch, "
        "snippet(fts, 2, '[', ']', '…', 12) AS excerpt, "
        "bm25(fts) AS rank "
        f"FROM fts WHERE {where_sql} "
        "ORDER BY rank, path LIMIT ? OFFSET ?"
    )

    with connect() as conn:
        total = conn.execute(count_sql, base_params).fetchone()["n"]
        rows = conn.execute(
            page_sql, [*base_params, limit, offset],
        ).fetchall()
        return [dict(r) for r in rows], total


def get_file(rel_path: str) -> dict | None:
    """Return one file row plus its body. Path is relative to memory_dir().

    Rejects absolute paths, traversal, symlinks, and anything escaping the
    vault — via lib.safe_resolve.
    """
    mem = memory_dir()
    try:
        target = safe_resolve(rel_path, mem)
    except UnsafePathError:
        return None
    if not target.exists() or not target.is_file():
        return None
    try:
        body = target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return {
        "path": rel_path,
        "title": first_heading(target) or target.stem,
        "body": body,
        "size": target.stat().st_size,
    }


def list_recent(scope: str, limit: int = 10) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT path, title, scope, branch FROM files "
            "WHERE scope = ? ORDER BY path DESC LIMIT ?",
            (scope, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def list_branch_notes(branch_slug: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT path, title FROM files "
            "WHERE scope = 'pr-context' AND branch = ? ORDER BY path",
            (branch_slug,),
        ).fetchall()
        return [dict(r) for r in rows]


def status() -> dict:
    with connect() as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM files").fetchone()["n"]
        by_scope = {
            row["scope"]: row["n"]
            for row in conn.execute(
                "SELECT scope, COUNT(*) AS n FROM files GROUP BY scope"
            )
        }
        return {
            "db": str(db_path()),
            "total_files": total,
            "by_scope": by_scope,
        }

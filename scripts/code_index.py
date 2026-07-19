"""Coarse code-graph fallback — tree-sitter-based def + call extraction.

When Graphify isn't installed, this builds a `{nodes, edges}` payload in
the same shape as `graphify-out/graph.json` so the downstream readers in
code_graph.py (code_map, resolve_symbol, --strict-symbols) work with no
external dependency.

What the fallback gives you, honestly:
  - defs (functions, classes, methods, structs, enums, interfaces)
  - best-effort *within-file* call edges (no cross-file resolution)

What it does NOT give you (Graphify's job, when installed):
  - cross-file / cross-service call resolution
  - complexity / hot-path properties
  - LSP-resolved calls with confidence

Optional dep — if `tree-sitter-language-pack` isn't importable, `available()`
returns False and `build()` returns None. Mirrors embeddings.py's pattern.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import subprocess
from pathlib import Path

import lib_loader  # noqa: F401
from lib import plugin_data_dir, project_dir

# ---------------------------------------------------------------------------
# Availability — same shape as embeddings.available()
# ---------------------------------------------------------------------------


def available() -> bool:
    """Return True iff tree-sitter-language-pack is importable."""
    try:
        import tree_sitter_language_pack  # noqa: F401
    except ImportError:
        return False
    return True


# ---------------------------------------------------------------------------
# Language → (extension, def query, call query)
#
# Def queries capture `@name` (the identifier) and `@def` (the enclosing
# declaration node, for location). Call queries capture `@name` only.
# Each query was validated against the grammar in this pack (v1.8.1):
#   - Go uses `field_identifier` for method receivers' names.
#   - Swift has no `struct_declaration`; structs parse as
#     `class_declaration` with a `struct` keyword child.
#   - The pack uses newer grammar names: `csharp`, not `c_sharp`.
# ---------------------------------------------------------------------------

LANG_BY_EXT: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".cs": "csharp",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".rb": "ruby",
    ".swift": "swift",
}

# Per-language def + call extraction queries. The call query is best-effort:
# tree-sitter can't resolve a bare `foo()` to a definition without scope
# analysis, so we only emit edges where the callee name matches a def
# *in the same file* (see _edges_for_file).
_QUERIES: dict[str, tuple[str, str]] = {
    "python": (
        """
        (function_definition name: (identifier) @name) @def
        (class_definition name: (identifier) @name) @def
        """,
        "(call function: (identifier) @name) @call",
    ),
    "csharp": (
        """
        (class_declaration name: (identifier) @name) @def
        (interface_declaration name: (identifier) @name) @def
        (method_declaration name: (identifier) @name) @def
        (struct_declaration name: (identifier) @name) @def
        (enum_declaration name: (identifier) @name) @def
        """,
        "(invocation_expression function: (identifier) @name) @call",
    ),
    "typescript": (
        """
        (function_declaration name: (identifier) @name) @def
        (class_declaration name: (type_identifier) @name) @def
        (method_definition name: (property_identifier) @name) @def
        (interface_declaration name: (type_identifier) @name) @def
        """,
        "(call_expression function: (identifier) @name) @call",
    ),
    "tsx": (
        """
        (function_declaration name: (identifier) @name) @def
        (class_declaration name: (type_identifier) @name) @def
        (method_definition name: (property_identifier) @name) @def
        (interface_declaration name: (type_identifier) @name) @def
        """,
        "(call_expression function: (identifier) @name) @call",
    ),
    "javascript": (
        """
        (function_declaration name: (identifier) @name) @def
        (class_declaration name: (identifier) @name) @def
        (method_definition name: (property_identifier) @name) @def
        """,
        "(call_expression function: (identifier) @name) @call",
    ),
    "go": (
        """
        (function_declaration name: (identifier) @name) @def
        (method_declaration name: (field_identifier) @name) @def
        (type_declaration (type_spec name: (type_identifier) @name)) @def
        """,
        "(call_expression function: (identifier) @name) @call",
    ),
    "rust": (
        """
        (function_item name: (identifier) @name) @def
        (struct_item name: (type_identifier) @name) @def
        (enum_item name: (type_identifier) @name) @def
        (trait_item name: (type_identifier) @name) @def
        (impl_item type: (type_identifier) @name) @def
        """,
        "(call_expression function: (identifier) @name) @call",
    ),
    "java": (
        """
        (class_declaration name: (identifier) @name) @def
        (interface_declaration name: (identifier) @name) @def
        (method_declaration name: (identifier) @name) @def
        (enum_declaration name: (identifier) @name) @def
        """,
        "(method_invocation name: (identifier) @name) @call",
    ),
    "kotlin": (
        """
        (class_declaration name: (type_identifier) @name) @def
        (object_declaration name: (type_identifier) @name) @def
        (interface_declaration name: (type_identifier) @name) @def
        (function_declaration name: (simple_identifier) @name) @def
        """,
        "(call_expression function: (simple_identifier) @name) @call",
    ),
    "ruby": (
        """
        (class name: (constant) @name) @def
        (module name: (constant) @name) @def
        (method name: (identifier) @name) @def
        (singleton_method name: (identifier) @name) @def
        """,
        "(call method: (identifier) @name) @call",
    ),
    "swift": (
        """
        (function_declaration name: (simple_identifier) @name) @def
        (class_declaration name: (type_identifier) @name) @def
        (protocol_declaration name: (type_identifier) @name) @def
        """,
        "(call_expression function: (simple_identifier) @name) @call",
    ),
}

# Cached compiled (language, def_query, call_query) tuples — Query objects
# are reusable across parses; compiling once per language per process.
# A stored None means "grammar unavailable" — checked with `in`, since
# .get() can't tell it apart from a cache miss.
_PARSED_CACHE: dict[str, tuple[object, object, object] | None] = {}


def _parsed_for(lang_name: str):
    """Return (parser, def_query, call_query) for a language, compiled once.

    Returns None if the grammar isn't downloaded or the query won't compile
    — caller skips that file. Grammar download is best-effort on first use.
    """
    import tree_sitter_language_pack as tsp
    from tree_sitter import Parser, Query

    if lang_name in _PARSED_CACHE:
        return _PARSED_CACHE[lang_name]

    try:
        if lang_name not in tsp.downloaded_languages():
            # Best-effort one-time download. If it fails (offline), this
            # language is simply skipped — we never raise out of build().
            with contextlib.suppress(Exception):
                tsp.download([lang_name])
        lang = tsp.get_language(lang_name)
        def_src, call_src = _QUERIES[lang_name]
        def_q = Query(lang, def_src)
        call_q = Query(lang, call_src)
        parser = Parser(lang)
    except Exception:
        # Mark as unavailable so we don't retry per-file. Using a sentinel
        # rather than leaving it absent avoids re-attempting the download.
        _PARSED_CACHE[lang_name] = None
        return None
    triple = (parser, def_q, call_q)
    _PARSED_CACHE[lang_name] = triple
    return triple


# ---------------------------------------------------------------------------
# Walker — mirrors bootstrap-scan's ignore layering. NOT extracted to a
# shared helper yet because importing bootstrap-scan pulls doc_claims et
# al. into the import graph; see plan's "out of scope" note.
# ---------------------------------------------------------------------------

# Lowest-priority ignore layer. Identical intent to bootstrap-scan's
# DEFAULT_IGNORE_LINES; trimmed to the build/cache/tooling dirs that are
# never source code (bootstrap-scan's list also covers low-signal docs,
# which we don't need here since we walk by extension).
_DEFAULT_IGNORE_LINES = [
    "node_modules/", ".git/", "dist/", "build/", "target/",
    ".venv/", "venv/", "__pycache__/", ".next/", ".nuxt/",
    ".cache/", ".pytest_cache/", ".mypy_cache/", ".ruff_cache/",
    "coverage/", ".coverage/", "htmlcov/",
    "graphify-out/", ".strata/",
    "vendor/", "bower_components/", ".pnp/",
    "site-packages/", "Pods/", ".gradle/",
    ".astro/", ".svelte-kit/",
    ".claude/", ".github/", ".gitlab/", ".vscode/", ".idea/",
    ".zed/", ".agents/",
]


def _build_ignore_spec(pd: Path):
    """gitwildmatch PathSpec layered defaults → .ignore → .strataignore.

    Mirrors bootstrap-scan._build_ignore_spec; duplicated deliberately
    (see module comment).
    """
    import pathspec
    lines = list(_DEFAULT_IGNORE_LINES)
    for filename in (".ignore", ".strataignore"):
        f = pd / filename
        if f.exists():
            with contextlib.suppress(OSError):
                lines.extend(f.read_text(encoding="utf-8").splitlines())
    return pathspec.PathSpec.from_lines("gitwildmatch", lines)


def _list_git_visible_files(pd: Path) -> list[str] | None:
    """tracked + untracked-but-not-gitignored files. None if not a repo.

    Mirrors bootstrap-scan._list_git_visible_files; duplicated (see above).
    """
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


def _walk_source_files(pd: Path) -> list[Path]:
    """All parseable source files under pd, minus the layered ignore spec.

    Candidate set comes from `git ls-files` when in a repo (fast, respects
    .gitignore); falls back to rglob over known extensions otherwise.
    """
    git_files = _list_git_visible_files(pd)
    if git_files is not None:
        exts = set(LANG_BY_EXT)
        candidates = (pd / rel for rel in git_files
                      if Path(rel).suffix in exts)
    else:
        candidates = (p for p in pd.rglob("*")
                      if p.suffix in LANG_BY_EXT)

    spec = _build_ignore_spec(pd)
    out: list[Path] = []
    for p in candidates:
        if not p.is_file():
            continue
        rel = p.relative_to(pd).as_posix()
        if spec.match_file(rel):
            continue
        out.append(p)
    return sorted(out)


# ---------------------------------------------------------------------------
# Per-file extraction
# ---------------------------------------------------------------------------


def _sha256_content(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _node_text(node) -> str:
    """Safely decode a tree-sitter node's text (may be None per stubs)."""
    raw = node.text
    if raw is None:
        return ""
    return raw.decode("utf-8", errors="replace")


def _defs_for_file(p: Path, rel: str, lang_name: str) -> list[dict]:
    """Extract def nodes from one file. Each node is Graphify-shaped so
    code_graph.py's defensive parsing is unchanged."""
    triple = _parsed_for(lang_name)
    if triple is None:
        return []
    parser, def_q, _call_q = triple
    try:
        src = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    try:
        tree = parser.parse(src.encode())
    except Exception:
        return []
    from tree_sitter import QueryCursor

    out: list[dict] = []
    for _pat, caps in QueryCursor(def_q).matches(tree.root_node):
        names = caps.get("name", [])
        defs = caps.get("def", [])
        if not names:
            continue
        name = _node_text(names[0])
        decl = defs[0] if defs else names[0]
        line = decl.start_point[0] + 1  # 1-based
        out.append({
            "id": f"{rel}::{name}",
            "label": name,
            "norm_label": name.lower(),
            "source_file": rel,
            "source_location": str(line),
            "file_type": "code",
        })
    return out


def _edges_for_file(p: Path, rel: str, lang_name: str,
                    file_def_names: set[str]) -> list[dict]:
    """Best-effort within-file call edges. A call resolves to an edge only
    if the callee name matches a def *in this same file* — no cross-file
    resolution (needs scope/LSP). Source of the edge is the enclosing def,
    which we approximate as the file (the AST doesn't easily give us the
    caller's def name without a second pass)."""
    triple = _parsed_for(lang_name)
    if triple is None:
        return []
    _parser, _def_q, call_q = triple
    try:
        src = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    try:
        tree = triple[0].parse(src.encode())
    except Exception:
        return []
    from tree_sitter import QueryCursor

    out: list[dict] = []
    for _pat, caps in QueryCursor(call_q).matches(tree.root_node):
        names = caps.get("name", [])
        if not names:
            continue
        callee = _node_text(names[0])
        if callee not in file_def_names:
            continue  # can't resolve → no edge
        # Source endpoint: we don't track which def the call sits inside
        # without an enclosing-def walk; use the file-level id so the edge
        # still counts toward in-degree on the callee (PageRank proxy).
        out.append({
            "source": f"{rel}::",
            "target": f"{rel}::{callee}",
            "relation": "calls",
        })
    return out


# ---------------------------------------------------------------------------
# Public entry — build the coarse index
# ---------------------------------------------------------------------------


def _cache_path() -> Path:
    return plugin_data_dir() / "code_index.json"


def _load_cache() -> dict | None:
    p = _cache_path()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _save_cache(payload: dict) -> None:
    p = _cache_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload), encoding="utf-8")


def build(force: bool = False) -> dict | None:
    """Build (or incrementally refresh) the coarse code index.

    Returns the Graphify-shaped `{nodes, edges, source, file_hashes}`
    payload, or None if the optional dep is unavailable.

    Incremental: per-file sha256 lets a second build re-parse only files
    whose content changed. Pass force=True for a full rebuild.
    """
    if not available():
        return None

    pd = project_dir()
    if pd is None:
        return None

    cache = None if force else _load_cache()
    prev_hashes: dict[str, str] = cache.get("file_hashes", {}) if cache else {}

    files = _walk_source_files(pd)
    cur_hashes: dict[str, str] = {}
    nodes: list[dict] = []
    edges: list[dict] = []

    for p in files:
        rel = p.relative_to(pd).as_posix()
        try:
            h = _sha256_content(p)
        except OSError:
            continue
        cur_hashes[rel] = h
        # Skip re-parse when content is unchanged since last build.
        if not force and prev_hashes.get(rel) == h:
            # Reuse cached nodes/edges for this file.
            if cache:
                nodes.extend([n for n in cache.get("nodes", [])
                              if n.get("source_file") == rel])
                edges.extend([e for e in cache.get("edges", [])
                              if isinstance(e, dict)
                              and str(e.get("source", "")).startswith(f"{rel}::")])
            continue
        lang_name = LANG_BY_EXT.get(p.suffix)
        if lang_name is None or lang_name not in _QUERIES:
            continue
        file_nodes = _defs_for_file(p, rel, lang_name)
        nodes.extend(file_nodes)
        file_def_names = {n["label"] for n in file_nodes}
        edges.extend(_edges_for_file(p, rel, lang_name, file_def_names))

    # Also carry over nodes/edges for files that still exist but were
    # unchanged (handled in the loop above via cache reuse). Files that
    # were deleted between builds simply drop out — they're not in
    # `files`, so their nodes/edges aren't re-emitted.

    payload = {
        "source": "coarse",
        "nodes": nodes,
        "edges": edges,
        "file_hashes": cur_hashes,
    }
    _save_cache(payload)
    return payload

"""Graphify companion — read-only summary of `graphify-out/graph.json`.

Strata does NOT depend on Graphify's Python code. We just parse the JSON
it emits when installed and run alongside us, so Claude knows a code-
structure graph is available without us having to call Graphify directly.

If `graphify-out/graph.json` doesn't exist (Graphify not installed, or never
run), every function here returns None — no error, no surprise.

Schema is defensively parsed: Graphify's output format may evolve, so we use
.get() everywhere and never assume a particular key shape.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import lib_loader  # noqa: F401
from lib import project_dir

GRAPH_REL = Path("graphify-out") / "graph.json"
REPORT_REL = Path("graphify-out") / "GRAPH_REPORT.md"


def graph_path() -> Path | None:
    """Return absolute path to graph.json if it exists in the project."""
    pd = project_dir()
    if pd is None:
        return None
    p = pd / GRAPH_REL
    if not p.exists() or not p.is_file():
        return None
    # Confirm it's actually inside the project (defence in depth)
    try:
        p.resolve().relative_to(pd.resolve())
    except ValueError:
        return None
    return p


def _count(value) -> int | str:
    """Best-effort count: list → len, int → itself, else '?'."""
    if isinstance(value, list):
        return len(value)
    if isinstance(value, int):
        return value
    return "?"


def summary() -> dict | None:
    """Return a metadata summary of the code graph, or None if absent.

    Shape (all fields best-effort; missing → None):
      {
        "available": bool,
        "path": "graphify-out/graph.json",
        "size_bytes": int,
        "age_hours": int,
        "nodes": int | "?",
        "edges": int | "?",
        "languages": dict | list | None,
        "built_at": str | None,
        "error": str | None,   # set when JSON parse failed
      }
    """
    p = graph_path()
    if p is None:
        return None

    pd = project_dir()
    rel = str(p.relative_to(pd)) if pd else str(p)

    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return {
            "available": False,
            "path": rel,
            "error": str(e),
            "size_bytes": p.stat().st_size,
        }

    meta = data.get("metadata") or data.get("meta") or {}
    languages = (
        meta.get("languages")
        or data.get("languages")
    )
    built_at = (
        meta.get("built_at")
        or meta.get("generated_at")
        or meta.get("created_at")
        or data.get("built_at")
    )

    mtime = p.stat().st_mtime
    age_hours = int((time.time() - mtime) / 3600)

    return {
        "available": True,
        "path": rel,
        "size_bytes": p.stat().st_size,
        "age_hours": age_hours,
        "nodes": _count(data.get("nodes")),
        "edges": _count(data.get("edges")),
        "languages": languages,
        "built_at": built_at,
    }


def report_path() -> Path | None:
    """Return absolute path to GRAPH_REPORT.md if it exists."""
    pd = project_dir()
    if pd is None:
        return None
    p = pd / REPORT_REL
    return p if p.exists() and p.is_file() else None


# ---------------------------------------------------------------------------
# Symbol resolution — programmatic bridge to Graphify nodes
# ---------------------------------------------------------------------------


# Module-level cache for parsed graph.json + derived indices. Keyed by
# (path, mtime) so the cache invalidates when graph.json is rebuilt.
_GRAPH_CACHE: dict[tuple[str, float], dict] = {}
_SYMBOL_INDEX_CACHE: dict[tuple[str, float], dict[str, list[dict]]] = {}


def _cache_key(p: Path) -> tuple[str, float] | None:
    try:
        return (str(p), p.stat().st_mtime)
    except OSError:
        return None


def _load_graph_json() -> dict | None:
    """Parse graph.json with mtime-keyed cache.

    The cost matters: bootstrap-scan --verify calls resolve_symbol once
    per backtick identifier per doc — easily thousands of calls per
    scan. Without caching, each call re-parses a multi-MB JSON file.
    """
    p = graph_path()
    if p is None:
        return None
    key = _cache_key(p)
    if key is None:
        return None
    cached = _GRAPH_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    # Bound cache size — only keep the latest. Replace older entries.
    _GRAPH_CACHE.clear()
    _GRAPH_CACHE[key] = data
    return data


def _extract_node_names(node: dict) -> list[str]:
    """Pull every reasonable name variant from a graph node.

    Graphify's schema can use any of `name`, `id`, `symbol`, `label`. We
    also derive the leaf segment from dotted/slashed/colon-separated forms
    so `services.medication.MedicationService`, `services/medication.py:MedicationService`
    and the bare `MedicationService` all hit the same lookup bucket.
    """
    names: list[str] = []
    for key in ("name", "id", "symbol", "label"):
        v = node.get(key)
        if isinstance(v, str) and v.strip():
            names.append(v.strip())
            # Leaf of dotted / colon / slash separator
            leaf = v
            for sep in (":", ".", "/"):
                if sep in leaf:
                    leaf = leaf.rsplit(sep, 1)[-1]
            if leaf and leaf != v:
                names.append(leaf)
    return names


def symbol_index() -> dict[str, list[dict]] | None:
    """Build {name → [node]} lookup. Same name can map to multiple nodes
    (e.g. `process` in Python and TypeScript). Cached per graph mtime."""
    p = graph_path()
    if p is None:
        return None
    key = _cache_key(p)
    if key is None:
        return None
    cached = _SYMBOL_INDEX_CACHE.get(key)
    if cached is not None:
        return cached

    data = _load_graph_json()
    if data is None:
        return None
    nodes = data.get("nodes")
    if not isinstance(nodes, list):
        return None
    idx: dict[str, list[dict]] = {}
    for n in nodes:
        if not isinstance(n, dict):
            continue
        for name in set(_extract_node_names(n)):
            idx.setdefault(name, []).append(n)

    _SYMBOL_INDEX_CACHE.clear()
    _SYMBOL_INDEX_CACHE[key] = idx
    return idx


def resolve_symbol(name: str) -> list[dict]:
    """Return nodes whose any-name-variant matches. Empty list if no graph
    or no match."""
    idx = symbol_index()
    if idx is None:
        return []
    return idx.get(name, [])


def top_god_nodes(n: int = 5) -> list[str]:
    """Return the names of the top-N highest-degree nodes.

    Best-effort: counts edges by src/dst/source/target/from/to keys.
    Falls back to first-N node names if the edge schema is unrecognised.
    """
    data = _load_graph_json()
    if data is None:
        return []
    nodes = data.get("nodes") or []
    edges = data.get("edges") or []
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return []

    degree: dict[str, int] = {}
    for e in edges:
        if not isinstance(e, dict):
            continue
        for key in ("src", "source", "from"):
            v = e.get(key)
            if isinstance(v, str):
                degree[v] = degree.get(v, 0) + 1
                break
        for key in ("dst", "target", "to"):
            v = e.get(key)
            if isinstance(v, str):
                degree[v] = degree.get(v, 0) + 1
                break

    if not degree:
        out: list[str] = []
        for node in nodes[:n]:
            if not isinstance(node, dict):
                continue
            names = _extract_node_names(node)
            if names:
                out.append(names[0])
            if len(out) >= n:
                break
        return out

    # Sort by degree desc, then map node id back to a friendly name
    id_to_name: dict[str, str] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        names = _extract_node_names(node)
        if names:
            primary = names[0]
            for nm in names:
                id_to_name[nm] = primary

    top = sorted(degree.items(), key=lambda kv: -kv[1])[:n]
    return [id_to_name.get(node_id, node_id) for node_id, _ in top]


# ---------------------------------------------------------------------------
# Token-budgeted projection — aider-style dynamic repo map
# ---------------------------------------------------------------------------

# Approx token-cost per char for code-flavoured strings (file paths +
# short labels). Conservative; real ratio is ~3.5.
_CHARS_PER_TOKEN = 4


def _match_focus_ids(nodes: list[dict], focus: list[str]) -> set[str]:
    """Return node ids whose label/norm_label matches any focus symbol.

    Two-phase: exact label match first; substring-on-id is only the
    fallback when no exact match was found. Without that fallback gating,
    a focus like `OrderAggregate` would pull in `OrderAggregateTests`,
    `OrderAggregate.cs`, every test fixture whose id contains the
    substring — focus would be dominated by test scaffolding.

    Strips a leading `.` and trailing `()` so `Handle` matches the
    method-style label `.Handle()`.
    """
    if not focus:
        return set()
    targets = [s.lower().strip(".").rstrip("()") for s in focus if s]
    if not targets:
        return set()

    exact: set[str] = set()
    # Per-target substring fallback candidates, only used if exact matched nothing
    substring_buckets: dict[str, set[str]] = {t: set() for t in targets}

    for n in nodes:
        if not isinstance(n, dict):
            continue
        nid = n.get("id")
        if not isinstance(nid, str):
            continue
        label = (n.get("label") or "").lower().strip(".").rstrip("()")
        norm = (n.get("norm_label") or "").lower().strip(".").rstrip("()")
        nidlow = nid.lower()
        for sym in targets:
            if label == sym or norm == sym:
                exact.add(nid)
                continue
            if sym in nidlow:
                substring_buckets[sym].add(nid)

    out = set(exact)
    # Only fall back to substring for targets that found no exact match
    matched_targets = {
        sym for sym in targets
        if any((n.get("label") or "").lower().strip(".").rstrip("()") == sym
               or (n.get("norm_label") or "").lower().strip(".").rstrip("()") == sym
               for n in nodes if isinstance(n, dict))
    }
    for sym, bucket in substring_buckets.items():
        if sym not in matched_targets:
            out |= bucket
    return out


def project(
    focus: list[str] | None = None,
    budget: int = 1000,
    include_docs: bool = False,
) -> str:
    """Token-budgeted, tiered signature view of the code graph.

    Inspired by aider's repo-map design — rank nodes by in-degree, render
    top tier with file+location, middle tier with file only, low tier
    with label only. A focus list promotes matched nodes + their 1-hop
    neighbours into the top tier regardless of global rank.

    The whole point: instead of materialising static "domain notes per
    class," Claude calls this on demand. Graph stays the source of truth.

    Args:
        focus: optional symbol names to centre on.
        budget: target token budget (~chars/4). Soft cap — lines never
            truncate mid-token.
        include_docs: include `file_type=document` nodes too. Default
            False — docs already live in the vault.

    Returns:
        Markdown ready to inject into a prompt.
    """
    g = _load_graph_json()
    if g is None:
        return ("_code map unavailable — no `graphify-out/graph.json` in "
                "project. Run `/strata:graphify` to build one._")

    nodes = g.get("nodes") or []
    links = g.get("links") or g.get("edges") or []
    if not isinstance(nodes, list) or not nodes:
        return "_code map: graph has no nodes_"
    nodes_by_id: dict[str, dict] = {
        n["id"]: n for n in nodes
        if isinstance(n, dict) and isinstance(n.get("id"), str)
    }

    # Adjacency from each canonical edge schema. Graphify uses source/target;
    # other graph builders use src/dst or from/to.
    incoming: dict[str, list[str]] = {}
    outgoing: dict[str, list[str]] = {}
    for link in links:
        if not isinstance(link, dict):
            continue
        s = None
        t = None
        for key in ("source", "src", "from"):
            v = link.get(key)
            if isinstance(v, str):
                s = v
                break
        for key in ("target", "dst", "to"):
            v = link.get(key)
            if isinstance(v, str):
                t = v
                break
        if s and t:
            incoming.setdefault(t, []).append(s)
            outgoing.setdefault(s, []).append(t)

    # In-degree as PageRank proxy. Cheap, ~as effective at "find the hubs"
    # per aider's empirical results.
    indeg = {nid: len(srcs) for nid, srcs in incoming.items()}

    focus_ids = _match_focus_ids(nodes, focus or [])
    focus_no_match = bool(focus) and not focus_ids

    # Per-file churn signal (Tornhill): top-N hotspots get a +bonus so
    # hot-and-central files rank higher than stable-and-central.
    # One subprocess call, cached at the commit_graph layer.
    churn_bonus: dict[str, float] = {}
    try:
        import commit_graph
        hot = {h["path"]: h["commits"]
               for h in commit_graph.hotspots(days=90, top=50)}
        for nid, node in nodes_by_id.items():
            sf = node.get("source_file") or ""
            if sf in hot:
                # Bonus scaled to in-degree magnitude — top-3 hot files
                # roughly equivalent to a 5-edge bump.
                churn_bonus[nid] = min(5.0, hot[sf] / 4.0)
    except Exception:
        pass

    # Score = in-degree + churn + focus boost + neighbour boost.
    # Baseline every node at 0 so leaves (no incoming edges) still
    # appear in low tier.
    score: dict[str, float] = {
        nid: float(indeg.get(nid, 0)) + churn_bonus.get(nid, 0.0)
        for nid in nodes_by_id
    }
    for nid in focus_ids:
        score[nid] = score.get(nid, 0.0) + 1_000_000  # always in top tier
        for nb in incoming.get(nid, []) + outgoing.get(nid, []):
            score[nb] = score.get(nb, 0.0) + 1_000  # neighbours promoted

    # Rank, filtered to interesting nodes
    ranked: list[tuple[str, dict]] = []
    for nid, _s in sorted(score.items(), key=lambda x: -x[1]):
        n = nodes_by_id.get(nid)
        if n is None:
            continue
        if not include_docs and n.get("file_type") != "code":
            continue
        ranked.append((nid, n))

    if not ranked:
        return f"_code map: no matches for focus={focus!r}_"

    char_budget = budget * _CHARS_PER_TOKEN
    out: list[str] = []
    if focus and focus_no_match:
        out.append(
            f"# Code map — no nodes matched focus: {', '.join(focus)}"
        )
        out.append(
            "_Falling back to global top hubs. Check spelling, or try "
            "a leaf segment of a dotted name._"
        )
    elif focus:
        out.append(f"# Code map — focus: {', '.join(focus)}")
        out.append(
            "_★ = focus symbol; neighbours of focus promoted into top tier._"
        )
    else:
        out.append("# Code map — top symbols by reference count")
    out.append("")

    used = sum(len(line) + 1 for line in out)
    n_total = len(ranked)
    top_cut = max(5, n_total // 10)
    mid_cut = top_cut + max(10, n_total // 5)

    rendered = 0
    truncated = False
    for i, (nid, n) in enumerate(ranked):
        label = n.get("label") or "?"
        sf = n.get("source_file") or ""
        loc = n.get("source_location") or ""
        is_focus = nid in focus_ids
        marker = " ★" if is_focus else ""

        if i < top_cut or is_focus:
            line = (f"- `{label}` — {sf}:{loc}  "
                    f"(refs:{indeg.get(nid, 0)}){marker}")
        elif i < mid_cut:
            line = f"- `{label}` — {sf}{marker}"
        else:
            line = f"- `{label}`{marker}"

        if used + len(line) + 1 > char_budget:
            truncated = True
            break
        out.append(line)
        used += len(line) + 1
        rendered += 1

    if truncated:
        out.append("")
        out.append(
            f"_(+{n_total - rendered} more nodes — increase budget to see)_"
        )

    return "\n".join(out)


def find_drifted_notes(churn_threshold: int = 20) -> list[dict]:
    """Notes whose `code_refs:` no longer resolve OR whose `source_file:`
    has churned heavily since the note was written.

    Drift detection runs on two axes:
      1. Structural: code_refs symbols don't resolve in graph.json (the
         class/function moved or was deleted)
      2. Temporal: the source file has had > `churn_threshold` commits
         since the note's `created:` date (the underlying code has
         moved on; the note may be stale even if symbols still exist)

    Returns: [{path, title, unresolved: [...], churn_signal: {...}}]
    """
    p = graph_path()
    if p is None:
        return []
    try:
        # Local imports — keeps the module light when this helper isn't called
        import frontmatter

        import lib_loader  # noqa: F401
        from lib import memory_dir
    except ImportError:
        return []

    mem = memory_dir()
    if not mem.exists():
        return []

    # Cheap lazy import — only when this function is called.
    try:
        import commit_graph as _cg
    except Exception:
        _cg = None  # type: ignore[assignment]

    out: list[dict] = []
    for f in mem.rglob("*.md"):
        if f.name in ("README.md", "INDEX.md"):
            continue
        try:
            post = frontmatter.load(f)
        except Exception:
            continue
        refs = post.metadata.get("code_refs")
        source_file = post.metadata.get("source_file")
        created = post.metadata.get("created")

        # Structural drift: code_refs that don't resolve in current graph
        unresolved: list[str] = []
        if isinstance(refs, list):
            for sym in refs:
                s = str(sym).strip()
                if not s:
                    continue
                if resolve_symbol(s):
                    continue
                leaf = s.rsplit(".", 1)[-1]
                if leaf != s and resolve_symbol(leaf):
                    continue
                unresolved.append(s)

        # Temporal drift: source file has churned past threshold since
        # the note's `created:` timestamp.
        churn_signal: dict | None = None
        if (_cg is not None and isinstance(source_file, str)
                and isinstance(created, str) and len(created) >= 10):
            try:
                since_iso = str(created)[:10] + "T00:00:00"
                n = _cg.commits_since_path_was_written(source_file, since_iso)
                if n >= churn_threshold:
                    churn_signal = {
                        "source_file": source_file,
                        "created": str(created)[:10],
                        "commits_since": n,
                    }
            except Exception:
                pass

        if unresolved or churn_signal:
            rel = f.relative_to(mem).as_posix()
            entry: dict = {
                "path": rel,
                "title": post.metadata.get("title") or f.stem,
                "unresolved": unresolved,
            }
            if churn_signal:
                entry["churn_signal"] = churn_signal
            out.append(entry)
    return out


def graph_age_relative_to_head() -> dict | None:
    """Compare graph.json mtime to git HEAD commits.

    Returns:
      {"graph_age_days": int, "commits_since": int, "stale": bool, "reason": str}
    or None if the graph or repo isn't present.
    """
    import subprocess  # local — keeps import out of hot path
    p = graph_path()
    if p is None:
        return None
    pd = project_dir()
    if pd is None:
        return None
    try:
        graph_mtime = p.stat().st_mtime
    except OSError:
        return None

    age_days = int((time.time() - graph_mtime) / 86400)

    # Count commits since graph.json mtime
    commits_since = 0
    try:
        from datetime import datetime, timezone
        graph_dt = datetime.fromtimestamp(graph_mtime, tz=timezone.utc).isoformat()
        r = subprocess.run(
            ["git", "-C", str(pd), "log", f"--since={graph_dt}", "--oneline"],
            capture_output=True, text=True, check=False, timeout=5,
        )
        if r.returncode == 0:
            commits_since = len([line for line in r.stdout.splitlines()
                                  if line.strip()])
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        pass

    stale = commits_since > 20 or age_days > 7
    if stale:
        if commits_since > 20:
            reason = f"{commits_since} commits since last build"
        else:
            reason = f"{age_days} days old"
    else:
        reason = "fresh"
    return {
        "graph_age_days": age_days,
        "commits_since": commits_since,
        "stale": stale,
        "reason": reason,
    }


def format_primer_block(s: dict) -> str:
    """Compact one-paragraph block for the SessionStart primer.

    When the graph is stale (>7 days or >20 commits behind HEAD), the
    primer leads with a directive rebuild prompt — code_map projections
    are only as good as the graph they read from, so out-of-date here
    cascades into out-of-date everywhere.

    When fresh, surfaces the top god nodes so Claude has obvious
    exploration entry points without re-reading source files.
    """
    if not s.get("available"):
        return ""
    parts = [f"`{s['nodes']}` nodes", f"`{s['edges']}` edges"]
    if s.get("languages"):
        if isinstance(s["languages"], dict):
            langs = ", ".join(sorted(s["languages"].keys())[:5])
        elif isinstance(s["languages"], list):
            langs = ", ".join(str(x) for x in s["languages"][:5])
        else:
            langs = str(s["languages"])
        parts.append(f"langs: {langs}")
    age = s.get("age_hours")
    if age is not None:
        parts.append(f"built {age}h ago")

    out = ["### Code graph (Graphify)"]

    # Proactive staleness — lead with the directive when stale, so the
    # user sees the action before the stats.
    try:
        staleness = graph_age_relative_to_head()
        if staleness and staleness.get("stale"):
            out.append(
                f"**⚠ graph is stale ({staleness['reason']}) — "
                f"run `/strata:graphify` to refresh.**  "
                f"`code_map` / symbol resolution / freshness scores "
                f"all read this graph, so outdated here cascades."
            )
            out.append("")
    except Exception:
        pass

    out.append("_" + "  ·  ".join(parts) + "_")

    # God-node entry points
    try:
        hubs = top_god_nodes(5)
        if hubs:
            out.append(f"_top hubs: {', '.join(hubs)}_")
    except Exception:
        pass

    out.append(
        f"_query via the graphify plugin if installed, or read "
        f"`{s['path']}` directly_"
    )
    return "\n".join(out) + "\n"

"""Strata MCP server — official SDK, stdio transport.

All tools are READ-ONLY. Writes happen through user-typed slash commands so
that the Bash invocations are visible to the user. Every path is resolved
against the configured vault root and rejected if it escapes.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

# Make scripts/ importable regardless of cwd
_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from mcp.server import Server  # noqa: E402
from mcp.server.stdio import stdio_server  # noqa: E402
from mcp.types import (  # noqa: E402
    GetPromptResult,
    Prompt,
    PromptArgument,
    PromptMessage,
    Resource,
    TextContent,
    Tool,
)
from pydantic import AnyUrl  # noqa: E402

import db  # noqa: E402
from lib import branch_slug, current_branch, first_heading, memory_dir  # noqa: E402

server: Server = Server("strata")

# ---------------------------------------------------------------------------
# Tool catalogue
# ---------------------------------------------------------------------------


@server.list_tools()
async def list_tools() -> list[Tool]:
    # Ambient MCP surface kept deliberately small (the lighter the load,
    # the cheaper every conversation). Heavy reads happen via the
    # `strata:memory-recall` subagent — Claude dispatches it via the
    # Agent tool; the recall happens in isolated context and only a
    # curated summary returns. The MCP catalogue here is just the tools
    # that genuinely earn always-on access.
    return [
        Tool(
            name="recall",
            description=(
                "Unified vault recall. Layer 1 (compact ranked index, ~50-"
                "100 tokens/hit, default), Layer 2 (+ wikilink neighbours), "
                "or Layer 3 (full body of the top hit). Replaces "
                "memory_search / memory_get / domain_lookup / recent_* / "
                "memory_insights with one entry. Excludes invalidated "
                "notes by default; ranks by FTS bm25 * relevance "
                "(recency + incoming links - supersession). For deep "
                "synthesis across many notes, dispatch `strata:memory-"
                "recall` agent instead — it isolates the search context."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "layer": {"type": "integer", "default": 1,
                              "enum": [1, 2, 3]},
                    "budget": {"type": "integer", "default": 600,
                               "minimum": 100, "maximum": 4000,
                               "description": "Soft token cap (~4 chars/tok)."},
                    "scope": {"type": "string",
                              "enum": ["all", "decisions", "domain",
                                       "lessons", "procedural",
                                       "propositions", "pr-context"],
                              "default": "all"},
                    "since": {"type": "string",
                              "description":
                                  "ISO date — restrict to notes touched after."},
                    "limit": {"type": "integer", "default": 10,
                              "minimum": 1, "maximum": 50},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="memory_status",
            description="Vault scope counts + FTS db path. Ambient, cheap.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="current_pr",
            description=(
                "Open PR for current branch via `gh` CLI. Friendly fallback "
                "when `gh` absent or no PR exists."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="code_graph_status",
            description=(
                "Summary of the Graphify code graph at `graphify-out/graph.json`. "
                "Returns node/edge counts, languages, build age. Returns 'not "
                "available' if Graphify hasn't been run. We don't depend on "
                "Graphify's Python code — just the JSON it emits."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="plan_status",
            description=(
                "Correlate a planning subdir's claims against git history "
                "and the code graph. For every path / symbol mentioned in "
                "the planning markdown, reports whether it has commits "
                "behind it, whether it exists now, and whether the symbol "
                "resolves. Outputs a completion estimate + verdict hint. "
                "Used by bootstrap-worker to classify (high-evidence plans "
                "become accepted ADRs; low-evidence become 'we considered "
                "this' lessons). Pass `subdir` like `.planning/auth-rewrite`."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "subdir": {
                        "type": "string",
                        "description": "Project-relative planning subdir.",
                    },
                },
                "required": ["subdir"],
            },
        ),
        Tool(
            name="code_map",
            description=(
                "Token-budgeted projection of the code graph — aider-style "
                "dynamic repo map. Returns a tiered signature view of the "
                "most-referenced symbols. Pass `focus` to centre the map on "
                "specific symbols (their nodes + 1-hop neighbours rank into "
                "the top tier regardless of global degree). Reads "
                "`graphify-out/graph.json`. Use this BEFORE grepping the "
                "codebase when you need to know what something is, who calls "
                "it, or what hubs the system has — typically 500-2000 tokens "
                "of compressed structure vs. thousands grepping files."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "focus": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Symbol names to centre on, e.g. "
                                       "['OrderAggregate', 'Handle'].",
                    },
                    "budget": {
                        "type": "integer", "default": 1000,
                        "minimum": 200, "maximum": 8000,
                        "description": "Target token budget. Soft cap.",
                    },
                    "include_docs": {
                        "type": "boolean", "default": False,
                        "description": "Include `file_type=document` nodes. "
                                       "Default code-only.",
                    },
                },
            },
        ),
        Tool(
            name="bootstrap_scan",
            description=(
                "Enumerate candidate files for `strata:bootstrap`. "
                "Walks the repo's markdown (respecting .gitignore, "
                ".strataignore, .ignore), buckets by git age, and "
                "optionally cross-checks each doc's claims against "
                "`git ls-files` and `graph.json` to score freshness. "
                "Read-only — does not modify the vault. The actual "
                "marking step (recording a SHA after processing a "
                "file) is still a visible bash invocation."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "unprocessed": {
                        "type": "boolean", "default": True,
                        "description": "Show only files not yet marked "
                                       "as processed (or modified since).",
                    },
                    "bucket": {
                        "type": "string",
                        "enum": ["fresh", "aging", "old", "ancient",
                                 "untracked"],
                        "description": "Limit to a single age bucket.",
                    },
                    "verify": {
                        "type": "boolean", "default": False,
                        "description": "Cross-check path / symbol "
                                       "claims. Slower but more accurate.",
                    },
                    "min_freshness": {
                        "type": "number", "minimum": 0.0, "maximum": 1.0,
                        "description": "With verify, drop files below "
                                       "this freshness score.",
                    },
                    "max_size": {
                        "type": "integer", "default": 200000, "minimum": 1024,
                        "description": "Skip files larger than this many "
                                       "bytes (auto-generated docs are noisy).",
                    },
                    "max_age_days": {
                        "type": "integer", "minimum": 1,
                        "description": "Skip files whose last commit is "
                                       "older than this many days.",
                    },
                },
            },
        ),
    ]


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------


def _text(s: str) -> list[TextContent]:
    return [TextContent(type="text", text=s)]


def _ensure_indexed() -> None:
    try:
        db.reindex(force=False)
    except Exception as e:
        print(f"[strata.mcp] reindex error: {e}", file=sys.stderr)


def _run_recall(query: str, *, layer: int = 1, budget: int = 600,
                limit: int = 10, scope: str | None = None,
                since: str | None = None) -> str:
    """Run scripts/recall.py and return its stdout (or an error string).
    Shared by the `recall` tool and the prompts below — same retrieval path."""
    import subprocess as _sp
    query = (query or "").strip()
    if not query:
        return "error: empty query"
    argv = [sys.executable, str(_SCRIPTS / "recall.py"),
            "--query", query,
            "--layer", str(int(layer)),
            "--budget", str(int(budget)),
            "--limit", str(int(limit))]
    if scope and scope != "all":
        argv += ["--scope", str(scope)]
    if since:
        argv += ["--since", str(since)]
    try:
        proc = _sp.run(argv, capture_output=True, text=True,
                       check=False, timeout=30)
    except (_sp.SubprocessError, OSError) as e:
        # OSError covers interpreter-launch failures (not a SubprocessError
        # subclass) — honor the "returns an error string" contract.
        return f"recall failed: {e}"
    if proc.returncode != 0:
        return f"recall error: {proc.stderr.strip() or 'unknown'}"
    return proc.stdout


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    args = arguments or {}

    if name == "recall":
        query = (args.get("query") or "").strip()
        if not query:
            return _text("error: empty query")
        return _text(_run_recall(
            query,
            layer=int(args.get("layer") or 1),
            budget=int(args.get("budget") or 600),
            limit=int(args.get("limit") or 10),
            scope=args.get("scope"),
            since=args.get("since"),
        ))

    if name == "memory_search":
        _ensure_indexed()
        query = (args.get("query") or "").strip()
        if not query:
            return _text("error: empty query")
        limit = int(args.get("limit") or 10)
        # Opaque cursor — base64-encoded offset for now. Keeps the wire
        # format stable if we change the scheme later.
        import base64
        offset = 0
        cursor_in = args.get("cursor")
        if cursor_in:
            try:
                offset = int(base64.urlsafe_b64decode(cursor_in.encode()).decode())
                if offset < 0:
                    offset = 0
            except Exception:
                return _text("error: invalid cursor")

        rows, total = db.search(
            query.split(),
            scope=args.get("scope") or "all",
            branch=args.get("branch"),
            limit=limit,
            offset=offset,
        )
        if not rows:
            if offset == 0:
                return _text(f"no matches for: {query}")
            return _text(f"end of results for: {query}  ({total} total)")

        shown_to = offset + len(rows)
        out = [f"### Matches for: {query}  ({shown_to}/{total})"]
        for r in rows:
            loc = f"[{r['scope']}]"
            if r.get("branch"):
                loc += f"[{r['branch']}]"
            out.append(f"- `{r['path']}` {loc} — {r['title']}")
            out.append(f"  > {r['excerpt']}")

        if shown_to < total:
            next_cursor = base64.urlsafe_b64encode(
                str(shown_to).encode()).decode()
            out.append(f"\n_next page: pass cursor `{next_cursor}`_")
        return _text("\n".join(out))

    if name == "memory_get":
        p = (args.get("path") or "").strip()
        if not p:
            return _text("error: missing path")
        # db.get_file uses safe_resolve internally and returns None on any
        # sandbox/symlink/traversal violation.
        data = db.get_file(p)
        if data is None:
            return _text(f"error: not found or refused (sandbox/symlink): {p}")
        return _text(
            f"# {data['title']}\n"
            f"_path: {data['path']}  size: {data['size']}B_\n\n"
            + data["body"]
        )

    if name == "pr_context_for_branch":
        _ensure_indexed()
        slug = (args.get("branch_slug") or "").strip()
        if not slug:
            slug = branch_slug(current_branch())
        rows = db.list_branch_notes(slug)
        if not rows:
            return _text(f"no pr-context notes for branch slug: {slug}")
        out = [f"### pr-context for `{slug}`  ({len(rows)} note(s))"]
        for r in rows:
            out.append(f"- `{r['path']}` — {r['title']}")
        return _text("\n".join(out))

    if name == "recent_decisions":
        _ensure_indexed()
        rows = db.list_recent("decisions", limit=int(args.get("limit") or 5))
        if not rows:
            return _text("no decisions yet")
        out = [f"### Most recent decisions ({len(rows)})"]
        for r in rows:
            out.append(f"- `{r['path']}` — {r['title']}")
        return _text("\n".join(out))

    if name == "recent_lessons":
        _ensure_indexed()
        rows = db.list_recent("lessons", limit=int(args.get("limit") or 5))
        if not rows:
            return _text("no lessons yet")
        out = [f"### Most recent lessons ({len(rows)})"]
        for r in rows:
            out.append(f"- `{r['path']}` — {r['title']}")
        return _text("\n".join(out))

    if name == "domain_lookup":
        _ensure_indexed()
        term = (args.get("term") or "").strip().lower()
        if not term:
            return _text("error: empty term")
        limit = int(args.get("limit") or 10)
        mem = memory_dir()
        d = mem / "domain"
        if not d.exists():
            return _text("no domain notes")
        matches: list[tuple[str, str]] = []
        for f in sorted(d.glob("*.md")):
            if f.name in ("README.md", "INDEX.md"):
                continue
            title = first_heading(f) or f.stem
            if term in title.lower() or term in f.stem.lower():
                matches.append((f.relative_to(mem).as_posix(), title))
                if len(matches) >= limit:
                    break
        if not matches:
            return _text(f"no domain match for: {term}")
        out = [f"### Domain matches for `{term}` ({len(matches)})"]
        for rel, title in matches:
            out.append(f"- `{rel}` — {title}")
        return _text("\n".join(out))

    if name == "memory_status":
        s = db.status()
        by = ", ".join(f"{k}={v}" for k, v in s["by_scope"].items()) or "(empty)"
        return _text(
            f"index: {s['db']}\n"
            f"total files: {s['total_files']}\n"
            f"by scope: {by}"
        )

    if name == "current_pr":
        try:
            import pr_context as _pr
            pr = _pr.fetch_for_current_branch()
            return _text(_pr.format_full(pr))
        except Exception as e:
            return _text(f"error: pr context fetch failed: {e}")

    if name == "decision_chain":
        _ensure_indexed()
        p = (args.get("path") or "").strip()
        if not p:
            return _text("error: missing path")
        if p.startswith("/") or ".." in Path(p).parts:
            return _text("error: refusing absolute or traversal path")
        # No symlink check here — decision_chain is metadata-only and the
        # caller can't read file contents through it.
        chain = db.decision_chain(p)
        out = [f"# decision_chain: `{chain['path']}`",
               f"_{chain['title']}_", ""]
        if chain["predecessors"]:
            out.append(f"## Predecessors ({len(chain['predecessors'])}) — superseded by this")
            for pre in chain["predecessors"]:
                out.append(f"- `{pre['path']}` — {pre['title']}")
            out.append("")
        if chain["successors"]:
            out.append(f"## Successors ({len(chain['successors'])}) — this is superseded by")
            for suc in chain["successors"]:
                out.append(f"- `{suc['path']}` — {suc['title']}")
            out.append("")
        if not chain["predecessors"] and not chain["successors"]:
            out.append("_no chain edges — standalone decision_")
        return _text("\n".join(out))

    if name == "stale_decisions":
        _ensure_indexed()
        stale_days = int(args.get("stale_days") or 14)
        rows = db.stale_decisions(stale_days)
        if not rows:
            return _text(f"no decisions stale > {stale_days}d — good")
        out = [f"### Stale ADRs (> {stale_days}d in `proposed`) — {len(rows)}"]
        for r in rows:
            out.append(f"- `{r['path']}` — {r['title']}  _({r['age_days']}d)_")
        return _text("\n".join(out))

    if name == "orphan_notes":
        _ensure_indexed()
        scope = args.get("scope") or "domain"
        rows = db.orphan_notes(scope)
        if not rows:
            return _text(f"no orphan {scope}/ notes — good")
        out = [f"### Orphan {scope}/ notes — {len(rows)}"]
        for r in rows:
            out.append(f"- `{r['path']}` — {r['title']}")
        return _text("\n".join(out))

    if name == "memory_semantic_search":
        query = (args.get("query") or "").strip()
        if not query:
            return _text("error: empty query")
        try:
            import embeddings
        except Exception as e:
            return _text(f"semantic search unavailable: {e}")
        if not embeddings.available():
            return _text(
                "semantic search unavailable — `fastembed` not installed in "
                "the plugin venv. Re-run bin/bootstrap-venv.sh, or use "
                "memory_search (FTS5 keyword search) instead."
            )
        # Make sure embeddings are current with the FTS5 index
        _ensure_indexed()
        embeddings.reindex(force=False)
        rows = embeddings.search(
            query,
            limit=int(args.get("limit") or 10),
            scope=args.get("scope"),
        )
        if not rows:
            return _text(f"no semantic matches for: {query}")
        out = [f"### Semantic matches for: {query}  ({len(rows)})"]
        for r in rows:
            loc = f"[{r['scope']}]"
            if r.get("branch"):
                loc += f"[{r['branch']}]"
            out.append(
                f"- `{r['path']}` {loc} — {r['title']}  _(score: {r['score']})_"
            )
        return _text("\n".join(out))

    if name == "memory_insights":
        _ensure_indexed()
        topic = (args.get("topic") or "").strip()
        if not topic:
            return _text("error: missing topic")
        per_sect = int(args.get("limit_per_section") or 5)
        terms = topic.split()

        out = [f"# Insights for: {topic}", ""]

        # 1. FTS matches across scopes — fall back to semantic search when
        # FTS returns nothing (covers queries whose literal words don't
        # appear but whose meaning matches indexed notes).
        rows, total = db.search(terms, scope="all", limit=per_sect, offset=0)
        if rows:
            out.append(f"## Top matches ({len(rows)}/{total})")
            for r in rows:
                loc = f"[{r['scope']}]"
                if r.get("branch"):
                    loc += f"[{r['branch']}]"
                out.append(f"- `{r['path']}` {loc} — {r['title']}")
                out.append(f"  > {r['excerpt']}")
            out.append("")
        else:
            try:
                import embeddings
                if embeddings.available():
                    embeddings.reindex(force=False)
                    sem = embeddings.search(topic, limit=per_sect)
                    if sem:
                        out.append(f"## Top matches — semantic ({len(sem)})")
                        out.append("_(no exact keyword matches; "
                                   "showing semantically-related notes)_")
                        for r in sem:
                            loc = f"[{r['scope']}]"
                            if r.get("branch"):
                                loc += f"[{r['branch']}]"
                            out.append(
                                f"- `{r['path']}` {loc} — {r['title']}  "
                                f"_(score: {r['score']})_"
                            )
                        out.append("")
            except Exception:
                pass

        # 2. Recent decisions in scope (any matching the topic)
        with db.connect() as conn:
            dec_rows = conn.execute(
                "SELECT f.path, f.title FROM fts JOIN files f "
                "ON fts.path = f.path WHERE fts MATCH ? AND f.scope = 'decisions' "
                "ORDER BY f.path DESC LIMIT ?",
                (db._safe_match(terms), per_sect),
            ).fetchall()
        if dec_rows:
            out.append(f"## Related decisions ({len(dec_rows)})")
            for r in dec_rows:
                out.append(f"- `{r['path']}` — {r['title']}")
            out.append("")

        # 3. Domain notes touching the topic
        with db.connect() as conn:
            dom_rows = conn.execute(
                "SELECT f.path, f.title FROM fts JOIN files f "
                "ON fts.path = f.path WHERE fts MATCH ? AND f.scope = 'domain' "
                "ORDER BY f.path LIMIT ?",
                (db._safe_match(terms), per_sect),
            ).fetchall()
        if dom_rows:
            out.append(f"## Related domain notes ({len(dom_rows)})")
            for r in dom_rows:
                out.append(f"- `{r['path']}` — {r['title']}")
            out.append("")

        # 4. Code symbols matching (Graphify)
        try:
            import code_graph as _cg
            sym_hits: list[str] = []
            for term in terms:
                for n in _cg.resolve_symbol(term)[:per_sect]:
                    name_ = n.get("name") or n.get("id") or term
                    if name_ not in sym_hits:
                        sym_hits.append(name_)
                if len(sym_hits) >= per_sect:
                    break
            if sym_hits:
                out.append(f"## Code symbols (Graphify) ({len(sym_hits)})")
                for sym in sym_hits[:per_sect]:
                    out.append(f"- `graphify:{sym}`")
                out.append("")
        except Exception:
            pass

        if len(out) <= 2:
            return _text(f"no insights found for: {topic}")
        return _text("\n".join(out))

    if name == "plan_status":
        subdir = (args.get("subdir") or "").strip()
        if not subdir:
            return _text("error: missing subdir")
        if subdir.startswith("/") or ".." in Path(subdir).parts:
            return _text("error: refusing absolute or traversal path")
        import plan_correlate
        try:
            report = plan_correlate.correlate(subdir)
        except Exception as e:
            return _text(f"plan_status error: {e}")
        return _text(plan_correlate.render_markdown(report))

    if name == "code_map":
        import code_graph
        focus = args.get("focus") or None
        if focus is not None and not isinstance(focus, list):
            return _text("error: focus must be an array of strings")
        budget = int(args.get("budget") or 1000)
        include_docs = bool(args.get("include_docs", False))
        try:
            md = code_graph.project(
                focus=focus, budget=budget, include_docs=include_docs,
            )
        except Exception as e:
            return _text(f"code_map error: {e}")
        return _text(md)

    if name == "bootstrap_scan":
        import subprocess
        argv = [sys.executable, str(_SCRIPTS / "bootstrap-scan.py")]
        if args.get("unprocessed", True):
            argv.append("--unprocessed")
        if args.get("verify"):
            argv.append("--verify")
        bucket = args.get("bucket")
        if bucket:
            argv += ["--bucket", str(bucket)]
        if "min_freshness" in args and args["min_freshness"] is not None:
            argv += ["--min-freshness", str(args["min_freshness"])]
        if "max_size" in args and args["max_size"] is not None:
            argv += ["--max-size", str(args["max_size"])]
        if "max_age_days" in args and args["max_age_days"] is not None:
            argv += ["--max-age-days", str(args["max_age_days"])]
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, check=False, timeout=600,
            )
        except subprocess.SubprocessError as e:
            return _text(f"bootstrap_scan failed: {e}")
        if proc.returncode != 0:
            return _text(
                f"bootstrap_scan exited {proc.returncode}\n\n"
                f"stderr:\n{proc.stderr.strip()}"
            )
        return _text(proc.stdout)

    if name == "code_graph_status":
        import code_graph
        cg = code_graph.summary()
        if cg is None:
            return _text(
                "Graphify not detected (no `graphify-out/graph.json` in "
                "project). Install + run graphify in this repo to enable "
                "code-structure queries."
            )
        if not cg.get("available"):
            return _text(
                f"graph.json present but unreadable: {cg.get('error', '?')}"
            )
        lines = [
            "# Code graph",
            f"- path: `{cg['path']}`",
            f"- size: {cg['size_bytes']:,} bytes",
            f"- nodes: {cg['nodes']}",
            f"- edges: {cg['edges']}",
            f"- age: {cg['age_hours']}h since last build",
        ]
        if cg.get("languages"):
            lines.append(f"- languages: {cg['languages']}")
        if cg.get("built_at"):
            lines.append(f"- built_at: {cg['built_at']}")
        lines.append(
            "\n_Query nodes/edges via the graphify plugin if installed, "
            "or read graph.json directly._"
        )
        return _text("\n".join(lines))

    if name == "memory_graph":
        _ensure_indexed()
        p = (args.get("path") or "").strip()
        if not p:
            return _text("error: missing path")
        if p.startswith("/") or ".." in Path(p).parts:
            return _text("error: refusing absolute or traversal path")
        graph = db.link_graph(p)

        # Cross-domain enrichment: for unresolved vault wikilinks, check
        # whether they match a Graphify code-graph node.
        code_matches: list[tuple[str, str]] = []
        try:
            import code_graph
            for ref in graph["references"]:
                if ref["resolved"]:
                    continue
                target = ref["path"]
                hits = code_graph.resolve_symbol(target)
                if not hits:
                    leaf = target.rsplit(".", 1)[-1]
                    if leaf != target:
                        hits = code_graph.resolve_symbol(leaf)
                if hits:
                    code_matches.append((target, hits[0].get("name")
                                         or hits[0].get("id") or target))
        except Exception:
            pass

        out = [f"# memory_graph: `{graph['path']}`", ""]
        if graph["references"]:
            out.append(f"## References — vault ({len(graph['references'])})")
            for ref in graph["references"]:
                marker = "" if ref["resolved"] else "  _(unresolved in vault)_"
                out.append(f"- `{ref['path']}`{marker}")
            out.append("")
        if code_matches:
            out.append(f"## References — code symbols (Graphify) ({len(code_matches)})")
            for target, node_name in code_matches:
                out.append(f"- `[[{target}]]` → `graphify:{node_name}`")
            out.append("")
        if graph["referenced_by"]:
            out.append(f"## Referenced by ({len(graph['referenced_by'])})")
            for src in graph["referenced_by"]:
                out.append(f"- `{src}`")
            out.append("")
        if (not graph["references"] and not graph["referenced_by"]
                and not code_matches):
            out.append("_no wikilinks in or out_")
        return _text("\n".join(out))

    return _text(f"error: unknown tool: {name}")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Resources — addressable read-only view of the vault as MCP resources
#
# URI scheme: `strata://<scope>/<filename>` where scope ∈
# {decisions, lessons, domain, pr-context/<branch>}. Resources are an
# *additive* surface — tools remain the primary way Claude reads memory.
# Clients that support resources get nicer UX (browseable, subscribable
# entries) for known-path reads.
# ---------------------------------------------------------------------------


_URI_PREFIX = "strata://"


def _rel_from_uri(uri: str) -> str | None:
    if not uri.startswith(_URI_PREFIX):
        return None
    return uri[len(_URI_PREFIX):]


def _uri_from_rel(rel: str) -> str:
    return f"{_URI_PREFIX}{rel}"


@server.list_resources()
async def list_resources() -> list[Resource]:
    """Expose every indexed file as a resource. Cheap — we already have the
    metadata in SQLite."""
    try:
        db.reindex(force=False)
    except Exception as e:
        print(f"[strata.mcp] reindex error: {e}", file=sys.stderr)

    resources: list[Resource] = []
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT path, title, scope FROM files "
            "WHERE scope IN ('decisions', 'lessons', 'domain', 'pr-context') "
            "ORDER BY scope, path"
        ).fetchall()
        for r in rows:
            resources.append(Resource(
                uri=AnyUrl(_uri_from_rel(r["path"])),
                name=r["title"] or r["path"],
                description=f"{r['scope']}: {r['title']}",
                mimeType="text/markdown",
            ))
    return resources


@server.read_resource()
async def read_resource(uri: AnyUrl) -> str:
    """Serve a resource. Path-sandboxed via db.get_file (which uses
    safe_resolve under the hood). Returns markdown text."""
    rel = _rel_from_uri(str(uri))
    if rel is None:
        return f"error: unsupported URI scheme: {uri}"
    data = db.get_file(rel)
    if data is None:
        return f"error: not found or refused (sandbox/symlink): {rel}"
    # Resource bodies are plain content — no extra metadata header so the
    # markdown renders cleanly in resource viewers.
    return data["body"]


# ---------------------------------------------------------------------------
# Prompts — user-controlled slash commands that PRELOAD curated vault context
# before the model reasons (read-only; they just call the recall path).
# ---------------------------------------------------------------------------

_PROMPTS: list[Prompt] = [
    Prompt(
        name="recall-pack",
        description="Preload the most relevant Strata memory for a topic "
                    "(ranked across all scopes) before you start work.",
        arguments=[PromptArgument(
            name="topic", required=True,
            description="What you're about to work on.")],
    ),
    Prompt(
        name="decision-brief",
        description="Preload the decisions (ADRs) governing a topic, so new "
                    "work doesn't contradict or duplicate them.",
        arguments=[PromptArgument(
            name="topic", required=True,
            description="The area / feature / component.")],
    ),
    Prompt(
        name="pr-onboard",
        description="Preload the current branch's context — the pr-context "
                    "notes and the decisions/lessons most relevant to it.",
        arguments=[],
    ),
]


def _prompt_result(description: str, text: str) -> GetPromptResult:
    return GetPromptResult(
        description=description,
        messages=[PromptMessage(
            role="user", content=TextContent(type="text", text=text))],
    )


@server.list_prompts()
async def list_prompts() -> list[Prompt]:
    return _PROMPTS


@server.get_prompt()
async def get_prompt(name: str,
                     arguments: dict[str, str] | None) -> GetPromptResult:
    args = arguments or {}
    if name == "recall-pack":
        topic = (args.get("topic") or "").strip()
        if not topic:
            raise ValueError("recall-pack requires a 'topic' argument")
        body = _run_recall(topic, layer=1)
        return _prompt_result(
            f"Strata recall pack — {topic}",
            f"Relevant Strata memory for **{topic}** — use it to ground your "
            f"work; don't re-derive what's already decided:\n\n{body}")
    if name == "decision-brief":
        topic = (args.get("topic") or "").strip()
        if not topic:
            raise ValueError("decision-brief requires a 'topic' argument")
        body = _run_recall(topic, layer=2, scope="decisions")
        return _prompt_result(
            f"Strata decision brief — {topic}",
            f"Decisions (ADRs) governing **{topic}** — honor or explicitly "
            f"supersede them, don't silently contradict:\n\n{body}")
    if name == "pr-onboard":
        branch = current_branch()
        if branch in ("unknown", "HEAD") or branch.startswith("detached@"):
            return _prompt_result(
                "Strata PR onboard — no branch context",
                "No usable branch context (not on a named branch). Use the "
                "`recall-pack` prompt with an explicit topic instead.")
        topic = branch_slug(branch).replace("-", " ").strip() or branch
        body = _run_recall(topic, layer=1)
        return _prompt_result(
            f"Strata PR onboard — {branch}",
            f"Context for branch `{branch}` — the pr-context notes and the "
            f"decisions/lessons most relevant to it:\n\n{body}")
    raise ValueError(f"unknown prompt: {name}")


async def main() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())

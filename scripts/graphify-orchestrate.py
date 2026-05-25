#!/usr/bin/env python3
"""Shell-out wrapper around `graphify`. Default is AST-only (local, no LLM).
`--obsidian` runs our local writer over graph.json — replicates Graphify's
`--obsidian` flag without its LLM API-key requirement."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import lib_loader  # noqa: F401
from lib import info, is_git_repo, project_dir, repo_name, vault_root


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true",
                    help="Pass --force to `graphify update` — overwrites "
                         "graph.json even if the rebuild has fewer nodes. "
                         "Useful after refactors that deleted code.")
    ap.add_argument("--status", action="store_true",
                    help="Print code-graph status and exit.")
    ap.add_argument("--obsidian", action="store_true",
                    help="After graphify produces graph.json, write our own "
                         "per-node markdown into <vault>/<repo>/graphify/ "
                         "so code nodes appear in Obsidian's graph view. "
                         "Pure-mechanical, no LLM, no API key, no network. "
                         "Replicates Graphify's --obsidian without its LLM "
                         "requirement.")
    ap.add_argument("--deep", action="store_true",
                    help="Pass --mode deep to graphify (semantic edges via "
                         "LLM). Costs tokens AND sends file content to an "
                         "external LLM. Do NOT use for regulated content.")
    args = ap.parse_args()

    if args.status:
        import code_graph
        s = code_graph.summary()
        if s is None:
            print("[strata] no graph.json — run /strata:graphify to build")
            return 0
        if not s.get("available"):
            print(f"[strata] graph.json present but unreadable: "
                  f"{s.get('error', '?')}")
            return 1
        print(f"[strata] graph.json: {s['nodes']} nodes, {s['edges']} edges, "
              f"{s['age_hours']}h old")
        try:
            age = code_graph.graph_age_relative_to_head()
            if age:
                marker = " 🔴 STALE" if age["stale"] else ""
                print(f"[strata] vs HEAD: {age['commits_since']} commits since "
                      f"build{marker}")
        except Exception:
            pass
        return 0

    if shutil.which("graphify") is None:
        print("[strata] graphify not installed.",
              file=sys.stderr)
        print("[strata] install: pip install graphifyy && graphify install",
              file=sys.stderr)
        return 2

    if not is_git_repo():
        print("[strata] not in a git repo", file=sys.stderr)
        return 2

    pd = project_dir()
    if pd is None:
        print("[strata] no project dir", file=sys.stderr)
        return 2

    # `graphify update .` is the AST-only path in current Graphify versions
    # — their help text literally says "(no LLM needed)". The bare
    # `graphify .` form now always requires an LLM API key. We use update
    # by default and only opt into the full LLM path when --deep is set.
    if args.deep:
        cmd: list[str] = ["graphify", "."]
        cmd.extend(["--mode", "deep"])
    else:
        cmd = ["graphify", "update", "."]
        if args.rebuild:
            # Force a full re-extract even when the cache thinks nothing
            # changed. Useful after refactors that deleted code.
            cmd.append("--force")

    info(f"$ {' '.join(cmd)}  (cwd: {pd})")
    r = subprocess.run(cmd, cwd=str(pd))
    if r.returncode != 0:
        return r.returncode

    # Local Obsidian export (no LLM, no network) from the freshly-produced
    # graph.json. This replaces Graphify's own --obsidian flag.
    if args.obsidian:
        graph_json = pd / "graphify-out" / "graph.json"
        if not graph_json.exists():
            info("warning: graph.json not found after graphify run; "
                 "skipping obsidian export")
            return 0
        obsidian_dir = vault_root() / repo_name() / "graphify"
        count = _write_obsidian_notes(graph_json, obsidian_dir)
        info(f"wrote {count} per-node Obsidian notes to {obsidian_dir}")

    return 0


# ---------------------------------------------------------------------------
# Local Obsidian export — pure-mechanical, no LLM, no network
#
# Replicates the structure of Graphify's `to_obsidian()` (in their
# graphify/export.py) but driven from graph.json instead of their in-memory
# graph. Defensive parsing — works across schema variations.
# ---------------------------------------------------------------------------


def _safe_filename(label: str) -> str:
    """Strip filesystem-unsafe + Obsidian-unsafe chars; fall back to 'unnamed'."""
    import re
    s = re.sub(r'[\\/*?:"<>|#^\[\]]', "", str(label)).strip()
    return s or "unnamed"


def _write_obsidian_notes(graph_json: Path, obsidian_dir: Path) -> int:
    """Write one .md per node in graph.json with [[wikilinks]] for edges.

    Returns the number of notes written.
    """
    import json
    try:
        data = json.loads(graph_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        info(f"obsidian export: cannot read graph.json: {e}")
        return 0

    nodes = data.get("nodes") or []
    edges = data.get("edges") or []
    if not isinstance(nodes, list) or not isinstance(edges, list):
        info("obsidian export: unexpected graph.json shape; skipping")
        return 0

    obsidian_dir.mkdir(parents=True, exist_ok=True)

    # Build neighbor index from edges (defensive across schema keys)
    neighbors: dict[str, list[tuple[str, str]]] = {}
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        src = edge.get("src") or edge.get("source") or edge.get("from")
        dst = edge.get("dst") or edge.get("target") or edge.get("to")
        rel = edge.get("relation") or edge.get("type") or ""
        if not (isinstance(src, str) and isinstance(dst, str)):
            continue
        neighbors.setdefault(src, []).append((dst, rel))
        neighbors.setdefault(dst, []).append((src, rel))

    # Map node id → safe filename, with collision suffixes for duplicates
    id_to_fname: dict[str, str] = {}
    seen: dict[str, int] = {}
    for n in nodes:
        if not isinstance(n, dict):
            continue
        nid = n.get("id") or n.get("name") or n.get("label")
        if not isinstance(nid, str):
            continue
        label = n.get("label") or n.get("name") or nid
        base = _safe_filename(str(label))
        if base in seen:
            seen[base] += 1
            id_to_fname[nid] = f"{base}_{seen[base]}"
        else:
            seen[base] = 0
            id_to_fname[nid] = base

    # Write per-node notes
    count = 0
    for n in nodes:
        if not isinstance(n, dict):
            continue
        nid = n.get("id") or n.get("name") or n.get("label")
        if not isinstance(nid, str) or nid not in id_to_fname:
            continue
        label = n.get("label") or n.get("name") or nid

        lines: list[str] = ["---"]
        for key in ("source_file", "type", "file_type", "language", "location"):
            v = n.get(key)
            if isinstance(v, str) and v:
                lines.append(f'{key}: "{v}"')
        ftype = n.get("file_type") or n.get("type") or "node"
        lines.append("tags:")
        lines.append(f"  - graphify/{ftype}")
        lines.append("---")
        lines.append("")
        lines.append(f"# {label}")
        lines.append("")

        if nid in neighbors:
            lines.append("## Connections")
            seen_targets: set[str] = set()
            # Sort by target's display name for stable output
            for target_id, rel in sorted(
                neighbors[nid],
                key=lambda t: id_to_fname.get(t[0], t[0]),
            ):
                if target_id in seen_targets:
                    continue
                seen_targets.add(target_id)
                target_fname = id_to_fname.get(target_id, _safe_filename(target_id))
                rel_str = f" - `{rel}`" if rel else ""
                lines.append(f"- [[{target_fname}]]{rel_str}")
            lines.append("")

        # Inline tag at bottom for Obsidian's tag panel
        lines.append(f"#graphify/{ftype}")

        fname = id_to_fname[nid] + ".md"
        (obsidian_dir / fname).write_text("\n".join(lines), encoding="utf-8")
        count += 1

    return count


if __name__ == "__main__":
    sys.exit(main())

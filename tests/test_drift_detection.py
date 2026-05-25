"""Tests for code_graph.find_drifted_notes — surfaces vault notes whose
`code_refs:` frontmatter lists symbols that no longer resolve in the
current graph.json. Used by /strata:review.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))


def _write_graph(repo, payload: dict):
    out = repo / "graphify-out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "graph.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_note(mem: Path, rel: str, frontmatter: dict, body: str = "x\n"):
    p = mem / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    fm = ["---"]
    for k, v in frontmatter.items():
        if isinstance(v, list):
            items = ", ".join(repr(i) for i in v)
            fm.append(f"{k}: [{items}]")
        else:
            fm.append(f"{k}: {v}")
    fm.append("---\n\n")
    p.write_text("\n".join(fm) + body)
    return p


def _reload():
    for mod in ("code_graph", "lib"):
        if mod in sys.modules:
            del sys.modules[mod]


def test_no_graph_returns_empty(initialised_vault, env):
    _reload()
    import code_graph
    assert code_graph.find_drifted_notes() == []


def test_note_without_code_refs_ignored(initialised_vault, env):
    _reload()
    _write_graph(env["repo"], {
        "nodes": [{"id": "x", "label": "X", "file_type": "code"}],
        "links": [],
    })
    _write_note(initialised_vault, "domain/no-refs.md",
                {"title": "No refs", "status": "stable"})
    import code_graph
    assert code_graph.find_drifted_notes() == []


def test_drifted_note_flagged_when_refs_dont_resolve(initialised_vault, env):
    _reload()
    _write_graph(env["repo"], {
        "nodes": [
            {"id": "still_here", "label": "StillHere",
             "file_type": "code", "source_file": "src/a.cs"},
        ],
        "links": [],
    })
    _write_note(initialised_vault, "domain/order.md",
                {"title": "Order Aggregate", "status": "stable",
                 "code_refs": ["StillHere", "GoneSymbol", "AnotherGone"]})

    import code_graph
    drifted = code_graph.find_drifted_notes()
    assert len(drifted) == 1
    d = drifted[0]
    assert d["path"] == "domain/order.md"
    assert "StillHere" not in d["unresolved"]
    assert "GoneSymbol" in d["unresolved"]
    assert "AnotherGone" in d["unresolved"]


def test_dotted_leaf_match_still_resolves(initialised_vault, env):
    """A code_ref like `Services.Auth.AuthService` should resolve when
    the graph has a node `AuthService` (leaf match), not appear in
    drifted output."""
    _reload()
    _write_graph(env["repo"], {
        "nodes": [
            {"id": "auth_service", "label": "AuthService",
             "file_type": "code", "source_file": "src/auth.cs"},
        ],
        "links": [],
    })
    _write_note(initialised_vault, "domain/auth.md",
                {"title": "Auth", "status": "stable",
                 "code_refs": ["Services.Auth.AuthService"]})

    import code_graph
    assert code_graph.find_drifted_notes() == []


def test_all_refs_resolved_means_no_drift(initialised_vault, env):
    _reload()
    _write_graph(env["repo"], {
        "nodes": [
            {"id": "a", "label": "AggA", "file_type": "code",
             "source_file": "src/a.cs"},
            {"id": "b", "label": "AggB", "file_type": "code",
             "source_file": "src/b.cs"},
        ],
        "links": [],
    })
    _write_note(initialised_vault, "domain/both.md",
                {"title": "Both", "status": "stable",
                 "code_refs": ["AggA", "AggB"]})

    import code_graph
    assert code_graph.find_drifted_notes() == []

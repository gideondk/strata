"""Tests for the Graphify-companion code_graph helpers.

We don't actually install graphify — we synthesise graph.json files with the
shapes graphify reportedly emits, and confirm we read them defensively.
"""
from __future__ import annotations

import json


def _write_graph(repo, payload: dict):
    out = repo / "graphify-out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "graph.json").write_text(json.dumps(payload), encoding="utf-8")


def _sample_graph() -> dict:
    """A small networkx node-link shape with mixed code/doc nodes.

    Shape mirrors what Graphify emits: each node has id/label/file_type/
    source_file/source_location; each link has source/target/relation.
    Topology — OrderAggregate is referenced by 3 callers; Handle by 2.
    """
    return {
        "directed": False,
        "nodes": [
            {"id": "order_aggregate", "label": "OrderAggregate",
             "file_type": "code", "source_file": "services/visits/OrderAggregate.cs",
             "source_location": "L10"},
            {"id": "order_handle", "label": ".Handle()",
             "file_type": "code", "source_file": "services/visits/OrderAggregate.cs",
             "source_location": "L42"},
            {"id": "caller_a", "label": "PlaceOrder",
             "file_type": "code", "source_file": "services/orders/PlaceOrderCommand.cs",
             "source_location": "L7"},
            {"id": "caller_b", "label": "CancelOrder",
             "file_type": "code", "source_file": "services/orders/CancelOrderCommand.cs",
             "source_location": "L7"},
            {"id": "caller_c", "label": "OrderController",
             "file_type": "code", "source_file": "gateways/agency/OrderController.cs",
             "source_location": "L18"},
            {"id": "doc_node", "label": "README",
             "file_type": "document", "source_file": "README.md",
             "source_location": "L1"},
            {"id": "loner", "label": "Unused",
             "file_type": "code", "source_file": "services/dead/Unused.cs",
             "source_location": "L1"},
        ],
        "links": [
            {"source": "caller_a", "target": "order_aggregate", "relation": "calls"},
            {"source": "caller_b", "target": "order_aggregate", "relation": "calls"},
            {"source": "caller_c", "target": "order_aggregate", "relation": "references"},
            {"source": "caller_a", "target": "order_handle", "relation": "calls"},
            {"source": "caller_b", "target": "order_handle", "relation": "calls"},
        ],
    }


def test_project_unavailable_message_when_no_graph(env):
    import code_graph
    out = code_graph.project()
    assert "unavailable" in out.lower()
    assert "graphify" in out.lower()


def test_project_unfocused_ranks_by_indegree(env):
    """No focus → highest in-degree node leads. OrderAggregate has 3
    incoming edges, .Handle() has 2; OrderAggregate should rank first."""
    import code_graph
    _write_graph(env["repo"], _sample_graph())
    out = code_graph.project(budget=500)
    # First non-header bullet is the top-ranked symbol
    bullets = [line for line in out.splitlines() if line.startswith("- ")]
    assert bullets, "expected at least one bullet"
    assert "OrderAggregate" in bullets[0]
    # Document nodes excluded by default
    assert "README" not in out
    # Loner with no in-degree is fine to omit or rank last; just shouldn't
    # be first
    assert "Unused" not in bullets[0]


def test_project_focus_promotes_neighbours(env):
    """Focus on `OrderAggregate` → its 1-hop callers ranked into top tier
    with the ★ marker on the focus node itself."""
    import code_graph
    _write_graph(env["repo"], _sample_graph())
    out = code_graph.project(focus=["OrderAggregate"], budget=500)
    assert "focus: OrderAggregate" in out
    assert "★" in out
    # All 3 callers should appear (promoted by neighbour boost)
    for name in ("PlaceOrder", "CancelOrder", "OrderController"):
        assert name in out, f"caller {name!r} missing from focus projection"


def test_project_focus_matches_dotted_method_label(env):
    """Focus on `Handle` (bare) should match label `.Handle()` (dotted
    method form). Real graphify graphs use the dotted form."""
    import code_graph
    _write_graph(env["repo"], _sample_graph())
    out = code_graph.project(focus=["Handle"], budget=500)
    assert "★" in out, "Handle focus didn't match `.Handle()` label"


def test_project_budget_caps_output(env):
    """A tiny budget produces a short string and a truncation marker."""
    import code_graph
    _write_graph(env["repo"], _sample_graph())
    out = code_graph.project(budget=50)  # ~200 chars
    assert len(out) < 600, f"output {len(out)} chars exceeded tiny budget"
    assert "more nodes" in out or len(
        [line for line in out.splitlines() if line.startswith("- ")]
    ) < 7


def test_project_focus_zero_matches_warns(env):
    """Regression: a focus that matched nothing previously degraded
    silently to unfocused output, leading the caller to think their
    focus worked. Now we surface the no-match condition explicitly."""
    import code_graph
    _write_graph(env["repo"], _sample_graph())
    out = code_graph.project(focus=["NotARealClass"], budget=500)
    assert "no nodes matched" in out.lower()
    assert "NotARealClass" in out
    # Still shows global hubs as a fallback (not empty)
    assert "OrderAggregate" in out


def test_project_focus_exact_match_excludes_substring_noise(env):
    """Regression for real-graph noise: focus=`OrderAggregate` must NOT
    pull `OrderAggregateTests` into the focus set just because the id
    contains the substring. When an exact label match exists, the
    substring fallback is suppressed."""
    import code_graph
    payload = {
        "nodes": [
            # Exact match
            {"id": "order_aggregate", "label": "OrderAggregate",
             "file_type": "code",
             "source_file": "services/visits/OrderAggregate.cs",
             "source_location": "L7"},
            # Substring-only match — must NOT be in focus
            {"id": "order_aggregate_tests_node", "label": "OrderAggregateTests",
             "file_type": "code",
             "source_file": "services/visits/tests/OrderAggregateTests.cs",
             "source_location": "L1"},
            # Caller (legitimate neighbour, no ★)
            {"id": "caller", "label": "OrderRouter",
             "file_type": "code",
             "source_file": "services/orders/PlaceOrderCommand.cs",
             "source_location": "L1"},
        ],
        "links": [
            {"source": "caller", "target": "order_aggregate"},
            # Tests reference the class too
            {"source": "order_aggregate_tests_node", "target": "order_aggregate"},
        ],
    }
    _write_graph(env["repo"], payload)
    out = code_graph.project(focus=["OrderAggregate"], budget=500)
    # The exact-match class gets ★
    assert "OrderAggregate`" in out
    # The Tests class is a neighbour, so it can appear — but WITHOUT ★
    test_lines = [line for line in out.splitlines()
                  if "OrderAggregateTests" in line]
    for line in test_lines:
        assert "★" not in line, (
            f"OrderAggregateTests should not be marked focus: {line!r}"
        )


def test_project_include_docs_optional(env):
    """include_docs=True surfaces document nodes; default False hides them."""
    import code_graph
    _write_graph(env["repo"], _sample_graph())
    default = code_graph.project(budget=500)
    with_docs = code_graph.project(budget=500, include_docs=True)
    assert "README" not in default
    assert "README" in with_docs


def test_summary_none_when_no_graph(env):
    import code_graph
    assert code_graph.summary() is None
    assert code_graph.graph_path() is None


def test_summary_parses_basic_shape(env):
    import code_graph
    _write_graph(env["repo"], {
        "nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
        "edges": [{"src": "a", "dst": "b"}],
        "metadata": {
            "languages": {"python": 12, "typescript": 4},
            "built_at": "2026-05-21T08:00:00Z",
        },
    })
    s = code_graph.summary()
    assert s is not None
    assert s["available"] is True
    assert s["nodes"] == 3
    assert s["edges"] == 1
    assert s["languages"] == {"python": 12, "typescript": 4}
    assert s["built_at"] == "2026-05-21T08:00:00Z"
    assert s["path"] == "graphify-out/graph.json"


def test_summary_handles_missing_metadata(env):
    """Older / minimal graphify outputs might lack metadata. Don't crash."""
    import code_graph
    _write_graph(env["repo"], {
        "nodes": [],
        "edges": [],
    })
    s = code_graph.summary()
    assert s is not None
    assert s["available"] is True
    assert s["nodes"] == 0
    assert s["edges"] == 0
    assert s["languages"] is None
    assert s["built_at"] is None


def test_summary_handles_int_counts(env):
    """Graphify may emit pre-counted summary form rather than full arrays."""
    import code_graph
    _write_graph(env["repo"], {
        "nodes": 1234,
        "edges": 5678,
    })
    s = code_graph.summary()
    assert s["nodes"] == 1234
    assert s["edges"] == 5678


def test_summary_handles_malformed_json(env):
    import code_graph
    out = env["repo"] / "graphify-out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "graph.json").write_text("{not valid json")
    s = code_graph.summary()
    assert s is not None
    assert s["available"] is False
    assert "error" in s


def test_primer_block_renders_compactly(env):
    import code_graph
    _write_graph(env["repo"], {
        "nodes": [{"id": str(i)} for i in range(10)],
        "edges": [{"src": "a", "dst": "b"}],
        "metadata": {"languages": ["python", "go"]},
    })
    s = code_graph.summary()
    block = code_graph.format_primer_block(s)
    assert "10" in block  # nodes
    assert "Graphify" in block
    assert "graphify-out/graph.json" in block
    assert len(block) < 500  # stays compact for primer budget


def test_primer_block_empty_when_unavailable(env):
    import code_graph
    block = code_graph.format_primer_block({"available": False})
    assert block == ""


# ---- Symbol resolution + top god nodes -----------------------------------


def test_symbol_index_returns_none_without_graph(env):
    import code_graph
    assert code_graph.symbol_index() is None


def test_symbol_index_maps_name_to_node(env):
    import code_graph
    _write_graph(env["repo"], {
        "nodes": [
            {"id": "services.medication.MedicationService",
             "name": "MedicationService"},
            {"id": "foo"},
        ],
        "edges": [],
    })
    idx = code_graph.symbol_index()
    assert idx is not None
    assert "MedicationService" in idx
    # Also indexable by the dotted form
    assert "services.medication.MedicationService" in idx


def test_resolve_symbol_finds_match(env):
    import code_graph
    _write_graph(env["repo"], {
        "nodes": [{"id": "MyClass"}, {"id": "OtherClass"}],
        "edges": [],
    })
    hits = code_graph.resolve_symbol("MyClass")
    assert len(hits) == 1
    assert code_graph.resolve_symbol("NotPresent") == []


def test_resolve_symbol_by_leaf_of_dotted_form(env):
    import code_graph
    _write_graph(env["repo"], {
        "nodes": [{"id": "services.medication.MedicationService",
                   "name": "MedicationService"}],
        "edges": [],
    })
    # Leaf lookup works
    assert len(code_graph.resolve_symbol("MedicationService")) >= 1


def test_top_god_nodes_by_degree(env):
    import code_graph
    _write_graph(env["repo"], {
        "nodes": [
            {"id": "hub", "name": "hub"},
            {"id": "leaf1"},
            {"id": "leaf2"},
            {"id": "leaf3"},
        ],
        "edges": [
            {"src": "leaf1", "dst": "hub"},
            {"src": "leaf2", "dst": "hub"},
            {"src": "leaf3", "dst": "hub"},
        ],
    })
    top = code_graph.top_god_nodes(2)
    assert "hub" in top


def test_top_god_nodes_empty_when_no_graph(env):
    import code_graph
    assert code_graph.top_god_nodes() == []


def test_graph_age_relative_to_head_none_without_graph(env):
    import code_graph
    assert code_graph.graph_age_relative_to_head() is None


def test_graph_age_relative_to_head_reports_age(env):
    """Just confirm the shape of the response when graph is present."""
    import code_graph
    _write_graph(env["repo"], {"nodes": [], "edges": []})
    age = code_graph.graph_age_relative_to_head()
    assert age is not None
    assert "graph_age_days" in age
    assert "commits_since" in age
    assert "stale" in age

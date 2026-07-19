"""Tests for the tree-sitter coarse code index.

The coarse fallback lets Strata's code-graph features (code_map,
resolve_symbol, --strict-symbols) work when Graphify isn't installed.
It parses source files with tree-sitter-language-pack and emits a
{nodes, edges} payload in the same shape graphify-out/graph.json uses.

We synthesise small source trees in the temp repo and assert the index
extracts the expected def nodes, respects ignores, and caches
incrementally. The pack is an optional dep — tests skip gracefully when
it isn't importable (the `available()` contract mirrors embeddings.py).
"""
from __future__ import annotations

import hashlib
import json

import pytest


def _ts_available() -> bool:
    try:
        import tree_sitter_language_pack  # noqa: F401
    except ImportError:
        return False
    return True


# Graceful skip when the optional dep is absent. Mirrors how embeddings
# tests would handle a fastembed-less environment: the *behaviour* under
# test is the degradation, not the absence.
pytestmark = pytest.mark.skipif(
    not _ts_available(),
    reason="tree-sitter-language-pack not installed",
)


# ---------------------------------------------------------------------------
# Source samples — kept tiny so each asserts a specific extraction fact.
# ---------------------------------------------------------------------------

_PY_SAMPLE = '''\
"""A module."""
class OrderAggregate:
    def handle(self):
        return helper()

def helper():
    return 1
'''

_CS_SAMPLE = '''\
namespace App {
    public class OrderAggregate {
        public void Handle() {}
    }
    public interface IRepo {}
}
'''


def _write(repo, rel: str, body: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


def _import_code_index():
    import code_index
    return code_index


# ---------------------------------------------------------------------------
# available()
# ---------------------------------------------------------------------------


def test_available_returns_bool(env):
    ci = _import_code_index()
    assert isinstance(ci.available(), bool)


def test_available_degrades_when_import_absent(env, monkeypatch):
    """available() must return False if the pack can't be imported."""
    import sys
    ci = _import_code_index()
    monkeypatch.setitem(sys.modules, "tree_sitter_language_pack", None)
    assert ci.available() is False


# ---------------------------------------------------------------------------
# build() — extraction
# ---------------------------------------------------------------------------


def test_build_returns_none_when_unavailable(env, monkeypatch):
    import sys
    ci = _import_code_index()
    monkeypatch.setitem(sys.modules, "tree_sitter_language_pack", None)
    assert ci.build() is None


def test_build_extracts_python_defs(env):
    """A .py file yields one node per class/function, with the Graphify
    node shape so downstream parsing is unchanged."""
    ci = _import_code_index()
    _write(env["repo"], "svc/orders.py", _PY_SAMPLE)
    out = ci.build()
    assert out is not None
    labels = {n["label"] for n in out["nodes"]}
    assert {"OrderAggregate", "handle", "helper"} <= labels
    # Shape conformance — every node carries the fields code_graph.py reads.
    for n in out["nodes"]:
        assert {"id", "label", "norm_label", "source_file",
                "source_location", "file_type"} <= set(n)
        assert n["file_type"] == "code"


def test_build_extracts_csharp_defs(env):
    """C# uses the newer `csharp` grammar name; classes + interfaces +
    methods all extracted."""
    ci = _import_code_index()
    _write(env["repo"], "Svc/Orders.cs", _CS_SAMPLE)
    out = ci.build()
    assert out is not None
    labels = {n["label"] for n in out["nodes"]}
    assert {"OrderAggregate", "Handle", "IRepo"} <= labels
    cs_nodes = [n for n in out["nodes"]
                if n["source_file"] == "Svc/Orders.cs"]
    assert cs_nodes
    # source_location is a line number (stringified, Graphify-style).
    assert all(n["source_location"].isdigit() or n["source_location"].startswith("L")
               for n in cs_nodes)


def test_build_emits_within_file_call_edges(env):
    """handle() calls helper() in the same file → one CALLS edge. No
    cross-file edges are emitted (that's the honest coarse limitation)."""
    ci = _import_code_index()
    _write(env["repo"], "svc/orders.py", _PY_SAMPLE)
    out = ci.build()
    assert out is not None
    edges = out.get("edges") or out.get("links") or []
    assert edges, "expected at least one within-file call edge"
    # At least one edge whose target label resolves to `helper`.
    ids = {n["id"]: n["label"] for n in out["nodes"]}
    targets = {ids.get(_edge_endpoint(e, "target")) for e in edges}
    assert "helper" in targets, f"no edge targets helper; edges={edges}"


def _edge_endpoint(edge: dict, which: str) -> str | None:
    """Read source/target across the edge schemas code_graph.project()
    understands (source/src/from and target/dst/to)."""
    for key in ({"target": ("target", "dst", "to"),
                 "source": ("source", "src", "from")}[which]):
        v = edge.get(key)
        if isinstance(v, str):
            return v
    return None


def test_build_respects_strataignore(env):
    """Files matched by .strataignore are skipped — same ignore layering
    as bootstrap-scan."""
    ci = _import_code_index()
    _write(env["repo"], "kept.py", "class Kept:\n    pass\n")
    _write(env["repo"], "ignored/secret.py", "class Secret:\n    pass\n")
    (env["repo"] / ".strataignore").write_text("ignored/\n", encoding="utf-8")
    out = ci.build()
    assert out is not None
    labels = {n["label"] for n in out["nodes"]}
    assert "Kept" in labels
    assert "Secret" not in labels


def test_build_skips_unknown_extensions(env):
    """Unknown extensions are skipped, not crashed on. .txt yields nothing."""
    ci = _import_code_index()
    _write(env["repo"], "notes.txt", "class NotCode {}\n")
    out = ci.build()
    # No source files parsed → empty payload, not None (None means
    # "unavailable"). Distinguish deliberately.
    assert out is not None
    assert out["nodes"] == []


def test_build_skips_default_ignored_dirs(env):
    """node_modules/ etc. are excluded by DEFAULT_IGNORE_LINES without a
    user-written .strataignore."""
    ci = _import_code_index()
    _write(env["repo"], "real.py", "class Real:\n    pass\n")
    _write(env["repo"], "node_modules/pkg/index.js",
           "function dep() {}\n")
    out = ci.build()
    assert out is not None
    labels = {n["label"] for n in out["nodes"]}
    assert "Real" in labels
    assert "dep" not in labels


# ---------------------------------------------------------------------------
# Cache + incremental rebuild
# ---------------------------------------------------------------------------


def test_build_caches_to_plugin_data_dir(env):
    """First build writes code_index.json under plugin_data_dir(), shaped
    so a subsequent load reuses it without re-parsing."""
    ci = _import_code_index()
    _write(env["repo"], "svc/orders.py", _PY_SAMPLE)
    ci.build()
    cache = env["data"] / "code_index.json"
    assert cache.exists()
    payload = json.loads(cache.read_text(encoding="utf-8"))
    assert payload.get("source") == "coarse"
    assert "file_hashes" in payload
    assert "svc/orders.py" in payload["file_hashes"]
    assert isinstance(payload.get("nodes"), list)


def test_incremental_rebuild_only_reparses_changed_files(env):
    """file_hashes change-detection: an unchanged file keeps its hash; a
    modified file's hash differs after rebuild."""
    ci = _import_code_index()
    _write(env["repo"], "a.py", "class A:\n    pass\n")
    _write(env["repo"], "b.py", "class B:\n    pass\n")
    ci.build()
    before = json.loads((env["data"] / "code_index.json").read_text("utf-8"))
    hash_a_before = before["file_hashes"]["a.py"]

    # Touch only a.py
    _write(env["repo"], "a.py", "class A:\n    def new(self):\n        pass\n")
    ci.build()
    after = json.loads((env["data"] / "code_index.json").read_text("utf-8"))
    # b.py untouched → hash stable
    assert after["file_hashes"]["b.py"] == before["file_hashes"]["b.py"]
    # a.py changed → hash differs, and the new method shows up
    assert after["file_hashes"]["a.py"] != hash_a_before
    labels = {n["label"] for n in after["nodes"]
              if n["source_file"] == "a.py"}
    assert "new" in labels


def test_file_hash_is_content_based(env):
    """file_hashes value is a hex digest of file content (sha256), so an
    mtime-only change (git checkout same content) doesn't trigger
    re-parse."""
    ci = _import_code_index()
    _write(env["repo"], "x.py", "class X:\n    pass\n")
    ci.build()
    payload = json.loads((env["data"] / "code_index.json").read_text("utf-8"))
    h = payload["file_hashes"]["x.py"]
    expected = hashlib.sha256(b"class X:\n    pass\n").hexdigest()
    assert h == expected

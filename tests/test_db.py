"""Tests for FTS5 indexing, supersession edges, and wikilink graph."""
from __future__ import annotations

import textwrap


def _write(mem, rel, content):
    p = mem / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


def test_reindex_picks_up_titles_from_frontmatter(initialised_vault):
    import db
    mem = initialised_vault
    _write(mem, "decisions/2026-05-20-foo.md", textwrap.dedent("""\
        ---
        title: Foo Decision
        status: accepted
        date: 2026-05-20
        ---
        # ignored markdown heading
        Body text mentioning sqlite.
        """))
    counts = db.reindex(force=True)
    assert counts["indexed"] == 1
    rows, total = db.search(["sqlite"])
    assert total == 1
    assert len(rows) == 1
    assert rows[0]["title"] == "Foo Decision"


def test_supersedes_edge_recorded(initialised_vault):
    import db
    mem = initialised_vault
    _write(mem, "decisions/2026-05-20-old.md", textwrap.dedent("""\
        ---
        title: Old Decision
        status: accepted
        date: 2026-05-20
        ---
        Original choice.
        """))
    _write(mem, "decisions/2026-05-21-new.md", textwrap.dedent("""\
        ---
        title: New Decision
        status: accepted
        date: 2026-05-21
        supersedes:
          - 2026-05-20-old
        ---
        Replaces the old one.
        """))
    db.reindex(force=True)
    superseded = db.superseded_paths()
    assert "decisions/2026-05-20-old.md" in superseded
    chain = db.decision_chain("decisions/2026-05-21-new.md")
    assert len(chain["predecessors"]) == 1
    assert chain["predecessors"][0]["path"] == "decisions/2026-05-20-old.md"


def test_wikilink_edges(initialised_vault):
    import db
    mem = initialised_vault
    _write(mem, "domain/medication-windows.md", "# Medication Windows\n")
    _write(mem, "decisions/2026-05-20-doses.md", textwrap.dedent("""\
        ---
        title: Doses
        ---
        See [[medication-windows]] for the timing rules.
        """))
    db.reindex(force=True)
    graph = db.link_graph("decisions/2026-05-20-doses.md")
    paths = [r["path"] for r in graph["references"]]
    assert "domain/medication-windows.md" in paths


def test_wikilink_inside_code_block_is_ignored(initialised_vault):
    import db
    mem = initialised_vault
    _write(mem, "decisions/2026-05-20-x.md", textwrap.dedent("""\
        ---
        title: X
        ---
        Real link: [[real-target]]

        ```python
        # this should not be a link: [[fake-link-in-code]]
        ```
        """))
    db.reindex(force=True)
    graph = db.link_graph("decisions/2026-05-20-x.md")
    paths = [r["path"] for r in graph["references"]]
    assert any("real-target" in p for p in paths)
    assert not any("fake-link-in-code" in p for p in paths)


def test_graphify_dir_is_excluded_from_index(initialised_vault):
    """Markdown under `graphify/` is auto-generated build output (per
    the graphify SKILL doc). Indexing it bloats FTS 40:1 on real
    codebases and pollutes memory_search results. It must be skipped."""
    import db
    mem = initialised_vault
    _write(mem, "decisions/2026-05-26-real.md",
           "---\nkind: decision\n---\nReal memory note.\n")
    _write(mem, "graphify/Foo.cs.md",
           "---\nfile_type: code\n---\n# Foo.cs\n")
    _write(mem, "graphify/Bar.cs.md",
           "---\nfile_type: code\n---\n# Bar.cs\n")

    counts = db.reindex(force=True)
    assert counts["indexed"] == 1, (
        f"only the real decision should index, got {counts}"
    )
    # Confirm via search: graphify content must not match
    _, total = db.search(["Foo.cs"])
    assert total == 0


def test_source_files_table_populated_from_scalar_frontmatter(
        initialised_vault):
    """A note with `source_file: src/x.py` writes one row to source_files."""
    import db
    mem = initialised_vault
    _write(mem, "lessons/2026-05-26-one.md", textwrap.dedent("""\
        ---
        kind: handoff
        source_file: src/x.py
        ---
        body
        """))
    db.reindex(force=True)

    idx = db.source_file_index()
    assert len(idx) == 1
    assert idx[0]["source_file"] == "src/x.py"
    assert idx[0]["note_count"] == 1


def test_source_files_table_populated_from_list_frontmatter(
        initialised_vault):
    """A note with `source_file: [a, b]` writes one row per entry."""
    import db
    mem = initialised_vault
    _write(mem, "lessons/2026-05-26-multi.md", textwrap.dedent("""\
        ---
        kind: handoff
        source_file:
          - src/a.py
          - src/b.py
        ---
        body
        """))
    db.reindex(force=True)

    idx = db.source_file_index()
    sources = {e["source_file"] for e in idx}
    assert sources == {"src/a.py", "src/b.py"}


def test_source_files_table_cleaned_up_on_delete(initialised_vault):
    """When a note is removed from disk and reindex runs, its source_files
    rows must be cleaned up too (otherwise the by-file index keeps
    surfacing deleted notes)."""
    import db
    mem = initialised_vault
    note = _write(mem, "lessons/2026-05-26-tmp.md", textwrap.dedent("""\
        ---
        kind: handoff
        source_file: src/temp.py
        ---
        body
        """))
    db.reindex(force=True)
    assert any(e["source_file"] == "src/temp.py"
               for e in db.source_file_index())

    note.unlink()
    db.reindex(force=False)
    assert all(e["source_file"] != "src/temp.py"
               for e in db.source_file_index())


def test_vault_summary_counts_indexed_notes(initialised_vault):
    """vault_summary returns total note count + sum of indexed file sizes.
    Used by the SessionStart primer's token-economy line."""
    import db
    mem = initialised_vault
    _write(mem, "decisions/2026-05-26-a.md",
           "---\nkind: decision\n---\nA body\n")
    _write(mem, "domain/concept.md",
           "---\nkind: domain\n---\nA concept\n")
    db.reindex(force=True)

    s = db.vault_summary()
    assert s["notes"] == 2
    assert s["bytes"] > 0

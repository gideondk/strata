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

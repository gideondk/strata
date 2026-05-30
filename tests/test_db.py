"""Tests for FTS5 indexing, supersession edges, and wikilink graph."""
from __future__ import annotations

import os
import sqlite3
import textwrap
from pathlib import Path

import pytest


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


def test_source_file_discovered_from_body_when_absent(initialised_vault, env):
    """#110: with no source_file frontmatter, reindex discovers path-like
    tokens from the body that ACTUALLY exist in the repo, marked inferred."""
    import db
    mem = initialised_vault
    repo = env["repo"]
    (repo / "src").mkdir(parents=True, exist_ok=True)
    (repo / "src" / "rate_limiter.py").write_text("# real file\n")

    _write(mem, "decisions/2026-05-28-rl.md", textwrap.dedent("""\
        ---
        title: Rate limiting
        ---
        We changed the bucket logic in `src/rate_limiter.py` this week.
        """))
    db.reindex(force=True)
    idx = db.source_file_index()
    hit = next((e for e in idx if e["source_file"] == "src/rate_limiter.py"), None)
    assert hit is not None, "real referenced path should be discovered"
    assert hit["all_inferred"] is True  # discovered, not declared


def test_discovery_ignores_nonexistent_and_prose(initialised_vault, env):
    """Precision guard: a path-shaped token that doesn't resolve to a real repo
    file is NOT indexed (no pollution)."""
    import db
    mem = initialised_vault
    _write(mem, "decisions/2026-05-28-ghost.md", textwrap.dedent("""\
        ---
        title: Ghost
        ---
        Touches `src/does_not_exist.py` and mentions read/write tradeoffs.
        """))
    db.reindex(force=True)
    sources = {e["source_file"] for e in db.source_file_index()}
    assert "src/does_not_exist.py" not in sources
    assert "read/write" not in sources  # prose with a slash, no real file


def test_declared_source_file_wins_over_discovery(initialised_vault, env):
    """If frontmatter declares source_file, discovery does NOT run (declared
    is authoritative; inferred=0)."""
    import db
    mem = initialised_vault
    repo = env["repo"]
    (repo / "src").mkdir(parents=True, exist_ok=True)
    (repo / "src" / "other.py").write_text("# real\n")
    _write(mem, "decisions/2026-05-28-declared.md", textwrap.dedent("""\
        ---
        title: Declared
        source_file: src/declared.py
        ---
        Body also mentions `src/other.py` but declaration wins.
        """))
    db.reindex(force=True)
    idx = {e["source_file"]: e for e in db.source_file_index()}
    assert "src/declared.py" in idx
    assert idx["src/declared.py"]["all_inferred"] is False
    assert "src/other.py" not in idx  # discovery skipped when declared present


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


def test_wal_mode_enabled(initialised_vault):
    """connect() must put the index in WAL so concurrent hook writers don't
    hit SQLITE_BUSY."""
    import db
    with db.connect() as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"


def test_branch_stamped_in_frontmatter_is_indexed(initialised_vault):
    """A decision authored on a feature branch carries `branch:` provenance;
    reindex must slugify it into the branch column so it's attributable even
    though it lives outside pr-context/."""
    import db
    mem = initialised_vault
    _write(mem, "decisions/2026-05-28-rotate.md", textwrap.dedent("""\
        ---
        title: Rotate tokens
        branch: feat/auth-rewrite
        ---
        Decided to rotate refresh tokens.
        """))
    db.reindex(force=True)
    rows, total = db.search(["rotate"], branch="feat-auth-rewrite")
    assert total == 1
    assert rows[0]["branch"] == "feat-auth-rewrite"
    # A non-matching branch filter excludes it.
    _, other = db.search(["rotate"], branch="some-other-branch")
    assert other == 0


def test_pr_context_branch_comes_from_path(initialised_vault):
    """pr-context notes still derive branch from their folder slug, even
    without a `branch:` field — the path stays canonical for that scope."""
    import db
    mem = initialised_vault
    _write(mem, "pr-context/feat-login/2026-05-28-1030--gk--note.md",
           "---\nkind: session\n---\nWorking on login.\n")
    db.reindex(force=True)
    notes = db.list_branch_notes("feat-login")
    assert [n["path"] for n in notes] == [
        "pr-context/feat-login/2026-05-28-1030--gk--note.md"
    ]


def test_schema_version_mismatch_rebuilds(initialised_vault):
    """A stale schema version drops every table; the next reindex repopulates
    from disk (the index is disposable)."""
    import db
    mem = initialised_vault
    _write(mem, "decisions/2026-05-28-a.md",
           "---\ntitle: A\n---\nUnique body marker zalgon.\n")
    db.reindex(force=True)
    assert db.search(["zalgon"])[1] == 1

    # Simulate an older index: roll user_version back and clobber a table.
    with db.connect() as conn:
        conn.execute("PRAGMA user_version = 1")
    # Next connect sees the mismatch and wipes; reindex rebuilds.
    db.reindex(force=False)
    assert db.search(["zalgon"])[1] == 1
    with db.connect() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION


def test_unreadable_file_purges_stale_entry(initialised_vault, monkeypatch):
    """If a previously-indexed note becomes unreadable, reindex drops its row
    instead of leaving stale content cached as current."""
    import db
    mem = initialised_vault
    p = _write(mem, "lessons/2026-05-28-x.md",
               "---\nkind: handoff\n---\nbody marker quixotic.\n")
    db.reindex(force=True)
    assert db.search(["quixotic"])[1] == 1

    real_read = Path.read_text

    def boom(self, *a, **k):
        if self.name == "2026-05-28-x.md":
            raise OSError("simulated unreadable")
        return real_read(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", boom)
    os.utime(p, None)  # bump mtime so the incremental pass re-reads it
    db.reindex(force=False)
    assert db.search(["quixotic"])[1] == 0


def test_write_connection_opens_immediate_transaction(initialised_vault):
    """connect(write=True) holds an explicit transaction (BEGIN IMMEDIATE) so
    busy_timeout is honoured under contention; read connects stay autocommit."""
    import db
    with db.connect(write=True) as conn:
        assert conn.in_transaction is True
    with db.connect() as conn:
        assert conn.in_transaction is False


def test_reindex_recovers_from_corrupt_index(initialised_vault):
    """A corrupt index.db is a disposable cache: reindex discards it and
    rebuilds from disk rather than raising a SQLite error."""
    import db
    mem = initialised_vault
    _write(mem, "decisions/2026-05-29-a.md",
           "---\ntitle: A\n---\nUnique body marker frobnitz.\n")
    db.reindex(force=True)
    assert db.search(["frobnitz"])[1] == 1

    # Clobber the DB file (and drop any WAL/SHM sidecars) with garbage.
    base = str(db.db_path())
    for suffix in ("-wal", "-shm"):
        sidecar = Path(base + suffix)
        if sidecar.exists():
            sidecar.unlink()
    Path(base).write_bytes(b"this is definitely not a sqlite database\x00\xff")

    # A raw connect proves it's corrupt...
    with pytest.raises(sqlite3.DatabaseError):
        raw = sqlite3.connect(base)
        try:
            raw.execute("SELECT count(*) FROM files").fetchone()
        finally:
            raw.close()

    # ...but reindex self-heals (no raise) and the content comes back.
    counts = db.reindex(force=False)
    assert counts["indexed"] >= 1
    assert db.search(["frobnitz"])[1] == 1

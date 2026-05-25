"""Pagination tests for db.search."""
from __future__ import annotations


def _write(mem, rel, content):
    p = mem / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


def test_search_returns_total(initialised_vault):
    import db
    mem = initialised_vault
    for i in range(12):
        _write(mem, f"decisions/2026-05-{i:02d}-x.md",
               f"---\ntitle: Decision {i}\n---\nbody mentions sqlite.\n")
    db.reindex(force=True)
    rows, total = db.search(["sqlite"], limit=5, offset=0)
    assert len(rows) == 5
    assert total == 12


def test_search_pagination_walks_complete(initialised_vault):
    import db
    mem = initialised_vault
    for i in range(7):
        _write(mem, f"decisions/2026-05-{i:02d}-x.md",
               f"---\ntitle: D{i}\n---\nfindme\n")
    db.reindex(force=True)
    page1, total = db.search(["findme"], limit=3, offset=0)
    page2, _ = db.search(["findme"], limit=3, offset=3)
    page3, _ = db.search(["findme"], limit=3, offset=6)
    page4, _ = db.search(["findme"], limit=3, offset=9)
    assert total == 7
    assert len(page1) + len(page2) + len(page3) + len(page4) == 7
    # No duplicates across pages
    paths = {r["path"] for r in (*page1, *page2, *page3, *page4)}
    assert len(paths) == 7


def test_search_pagination_stable_ordering(initialised_vault):
    """Same query at same offset returns the same page."""
    import db
    mem = initialised_vault
    for i in range(10):
        _write(mem, f"decisions/2026-05-{i:02d}-x.md",
               f"---\ntitle: D{i}\n---\nfindme\n")
    db.reindex(force=True)
    page_a, _ = db.search(["findme"], limit=4, offset=4)
    page_b, _ = db.search(["findme"], limit=4, offset=4)
    assert [r["path"] for r in page_a] == [r["path"] for r in page_b]


def test_search_empty_returns_zero_total(initialised_vault):
    import db
    rows, total = db.search(["nonexistent-term-xyz"], limit=10, offset=0)
    assert rows == []
    assert total == 0

"""Tests for review queries: stale_decisions, orphan_notes, missing fm, unresolved links."""
from __future__ import annotations

import os
import time


def _write(mem, rel, content):
    p = mem / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


def _backdate(path, days):
    """Set both mtime and atime to `days` ago."""
    t = time.time() - days * 86400
    os.utime(path, (t, t))


def test_stale_decisions_picks_up_old_proposed(initialised_vault):
    import db
    mem = initialised_vault
    _write(mem, "decisions/2026-05-21-fresh.md",
           "---\ntitle: Fresh\nstatus: proposed\n---\n")
    stale = _write(mem, "decisions/2026-05-01-stale.md",
                   "---\ntitle: Stale\nstatus: proposed\n---\n")
    accepted = _write(mem, "decisions/2026-04-01-accepted.md",
                      "---\ntitle: Accepted\nstatus: accepted\n---\n")
    _backdate(stale, 30)
    _backdate(accepted, 30)
    db.reindex(force=True)

    flagged = db.stale_decisions(stale_days=14)
    paths = {r["path"] for r in flagged}
    assert "decisions/2026-05-01-stale.md" in paths
    assert "decisions/2026-05-21-fresh.md" not in paths  # not old enough
    assert "decisions/2026-04-01-accepted.md" not in paths  # not proposed


def test_orphan_notes_finds_unlinked_domain(initialised_vault):
    import db
    mem = initialised_vault
    _write(mem, "domain/lonely-concept.md",
           "---\ntitle: Lonely\n---\n# Lonely\nNo links here.\n")
    _write(mem, "domain/connected.md",
           "---\ntitle: Connected\n---\nReferences [[lonely-concept]].\n")
    db.reindex(force=True)

    orphans = db.orphan_notes("domain")
    paths = {o["path"] for o in orphans}
    # lonely-concept is referenced by connected, so it has 1 incoming link
    # → not orphan
    assert "domain/lonely-concept.md" not in paths
    # connected has 1 outgoing link → not orphan either


def test_orphan_notes_finds_truly_isolated(initialised_vault):
    import db
    mem = initialised_vault
    _write(mem, "domain/island.md",
           "---\ntitle: Island\n---\nNo links in or out.\n")
    _write(mem, "domain/other.md",
           "---\ntitle: Other\n---\nAlso isolated.\n")
    db.reindex(force=True)

    orphans = db.orphan_notes("domain")
    paths = {o["path"] for o in orphans}
    assert "domain/island.md" in paths
    assert "domain/other.md" in paths


def test_files_missing_frontmatter(initialised_vault):
    import db
    mem = initialised_vault
    _write(mem, "decisions/2026-05-21-good.md",
           "---\ntitle: Good\nstatus: accepted\n---\nbody\n")
    _write(mem, "decisions/2026-05-21-bad.md",
           "# Bad\nNo frontmatter at all.\n")
    db.reindex(force=True)

    missing = db.files_missing_frontmatter("decisions")
    paths = {r["path"] for r in missing}
    assert "decisions/2026-05-21-bad.md" in paths
    assert "decisions/2026-05-21-good.md" not in paths


def test_unresolved_links_finds_typos(initialised_vault):
    import db
    mem = initialised_vault
    _write(mem, "domain/exists.md", "---\ntitle: Exists\n---\n")
    _write(mem, "decisions/2026-05-21-x.md",
           "---\ntitle: X\n---\n"
           "Links to [[exists]] and [[ghost-typo]].\n")
    db.reindex(force=True)

    broken = db.unresolved_links()
    src_to_dst = {(r["src"], r["dst"]) for r in broken}
    assert ("decisions/2026-05-21-x.md", "ghost-typo") in src_to_dst
    # The resolved one shouldn't appear
    assert all("exists" not in dst or src != "decisions/2026-05-21-x.md"
               for src, dst in src_to_dst)

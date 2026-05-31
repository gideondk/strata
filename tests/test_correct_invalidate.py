"""Tests for correct-note.py + invalidate-note.py + search filter.

The correction surface: edit body, edit one field, mark invalidated.
Each path bumps `updated:` and appends to `corrections:` (correct) or
sets the invalidation frontmatter block (invalidate). Search filters
invalidated notes out of default results.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import frontmatter

HERE = Path(__file__).resolve().parent
CORRECT = HERE.parent / "scripts" / "correct-note.py"
INVALIDATE = HERE.parent / "scripts" / "invalidate-note.py"


def _run(script: Path, *args, body: str | None = None, env=None):
    return subprocess.run(
        [sys.executable, str(script), *args],
        input=body if body is not None else "",
        capture_output=True, text=True, check=False,
        env=env,
    )


def _seed_note(mem: Path, rel: str, body: str = "# Note\n\nOriginal body.\n") -> Path:
    p = mem / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "---\ntitle: Test Note\nstatus: stable\n---\n\n" + body
    )
    return p


# ---- correct-note.py ----

def test_correct_replaces_body(initialised_vault):
    mem = initialised_vault
    p = _seed_note(mem, "domain/sample.md")
    r = _run(CORRECT, "domain/sample.md", "--reason", "Clarified definition.",
             body="# Note\n\nNew clarified body.\n",
             env=os.environ.copy())
    assert r.returncode == 0
    post = frontmatter.load(p)
    assert "New clarified body" in post.content
    assert "Original body" not in post.content
    # Audit trail recorded
    log = post.metadata.get("corrections") or []
    assert len(log) == 1
    assert log[0]["reason"] == "Clarified definition."
    assert "updated" in post.metadata


def test_correct_set_field(initialised_vault):
    mem = initialised_vault
    p = _seed_note(mem, "domain/sample2.md")
    r = _run(CORRECT, "domain/sample2.md", "--set", "status=draft",
             "--reason", "Rolling back to draft.",
             env=os.environ.copy())
    assert r.returncode == 0
    post = frontmatter.load(p)
    assert post.metadata["status"] == "draft"
    log = post.metadata["corrections"]
    assert log[0]["reason"] == "Rolling back to draft."


def test_correct_refuses_nonexistent_note(initialised_vault):
    r = _run(CORRECT, "domain/nope.md", "--set", "status=draft",
             env=os.environ.copy())
    assert r.returncode == 2
    assert "not found" in r.stderr


def test_correct_refuses_traversal(initialised_vault):
    r = _run(CORRECT, "../../etc/passwd", "--set", "status=draft",
             env=os.environ.copy())
    assert r.returncode == 2


def test_correct_requires_a_change(initialised_vault):
    """Plain `correct-note.py <path>` with no --set and no stdin body
    should error — there's nothing to do."""
    mem = initialised_vault
    _seed_note(mem, "domain/sample3.md")
    # No --set, no body on stdin
    r = subprocess.run(
        [sys.executable, str(CORRECT), "domain/sample3.md"],
        # /dev/null stdin so it IS a tty-like empty read
        stdin=subprocess.DEVNULL,
        capture_output=True, text=True, check=False,
        env=os.environ.copy(),
    )
    assert r.returncode == 2


# ---- invalidate-note.py ----

def test_invalidate_marks_status_and_records_reason(initialised_vault):
    mem = initialised_vault
    p = _seed_note(mem, "domain/old-pattern.md")
    r = _run(INVALIDATE, "domain/old-pattern.md",
             "--reason", "Aggregate split in 2026-05 refactor.",
             "--replaced-by", "domain/new-pattern.md",
             env=os.environ.copy())
    assert r.returncode == 0
    post = frontmatter.load(p)
    assert post.metadata["status"] == "invalidated"
    assert "invalidated_at" in post.metadata
    assert post.metadata["invalidation_reason"].startswith("Aggregate split")
    assert post.metadata["replaced_by"] == "domain/new-pattern.md"


def test_invalidate_records_bitemporal_valid_time(initialised_vault):
    """--invalid-since captures when the fact stopped being TRUE, distinct from
    invalidated_at (when we recorded it)."""
    mem = initialised_vault
    p = _seed_note(mem, "domain/stale-fact.md")
    r = _run(INVALIDATE, "domain/stale-fact.md",
             "--reason", "Was wrong since the schema change.",
             "--invalid-since", "2026-01-15",
             env=os.environ.copy())
    assert r.returncode == 0
    post = frontmatter.load(p)
    assert post.metadata["invalid_since"] == "2026-01-15"
    # Transaction time and valid time are independent fields.
    assert post.metadata["invalidated_at"] != "2026-01-15"


def test_invalidate_omits_valid_time_when_not_given(initialised_vault):
    mem = initialised_vault
    _seed_note(mem, "domain/y.md")
    r = _run(INVALIDATE, "domain/y.md", "--reason", "obsolete",
             env=os.environ.copy())
    assert r.returncode == 0
    post = frontmatter.load(mem / "domain/y.md")
    assert "invalid_since" not in post.metadata


def test_invalidate_requires_reason(initialised_vault):
    mem = initialised_vault
    _seed_note(mem, "domain/x.md")
    r = _run(INVALIDATE, "domain/x.md", env=os.environ.copy())
    assert r.returncode != 0
    assert "reason" in r.stderr.lower()


# ---- search filter ----

def test_search_excludes_invalidated_by_default(initialised_vault):
    """A note marked invalidated must drop out of default search."""
    mem = initialised_vault
    _seed_note(mem, "domain/active.md",
               body="# Active\n\nThis aggregate handles orders.\n")
    _seed_note(mem, "domain/retired.md",
               body="# Retired\n\nThis aggregate handles orders.\n")
    _run(INVALIDATE, "domain/retired.md",
         "--reason", "Replaced.", env=os.environ.copy())

    sys.path.insert(0, str(HERE.parent / "scripts"))
    import db
    db.reindex(force=True)
    rows, _ = db.search(["orders"])
    paths = {r["path"] for r in rows}
    assert "domain/active.md" in paths
    assert "domain/retired.md" not in paths


def test_search_can_opt_in_to_invalidated(initialised_vault):
    """`include_invalidated=True` surfaces them (for audit / review)."""
    mem = initialised_vault
    _seed_note(mem, "domain/active2.md",
               body="# Active\n\nOrders aggregate.\n")
    _seed_note(mem, "domain/retired2.md",
               body="# Retired\n\nOrders aggregate.\n")
    _run(INVALIDATE, "domain/retired2.md",
         "--reason", "x", env=os.environ.copy())

    sys.path.insert(0, str(HERE.parent / "scripts"))
    import db
    db.reindex(force=True)
    rows, _ = db.search(["orders"], include_invalidated=True)
    paths = {r["path"] for r in rows}
    assert "domain/retired2.md" in paths

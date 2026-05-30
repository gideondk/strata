"""Tests for new-proposition.py — reasoning lifecycle (open → contested
→ converging → settled-as-decision / refuted-as-lesson)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import frontmatter

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "new-proposition.py"


def _run(*args, body: str | None = None, env=None):
    kw: dict = {"capture_output": True, "text": True, "check": False,
                "env": env}
    if body is not None:
        kw["input"] = body
    else:
        kw["stdin"] = subprocess.DEVNULL
    return subprocess.run([sys.executable, str(SCRIPT), *args], **kw)


def test_create_proposition_uses_default_template(initialised_vault):
    r = _run("--title", "Should we move to Postgres?",
             env=os.environ.copy())
    assert r.returncode == 0, r.stderr
    mem = initialised_vault
    matches = list((mem / "propositions").glob("*-should-we-move-to-postgres.md"))
    assert matches, "proposition file not created"
    post = frontmatter.load(matches[0])
    assert post.metadata["status"] == "open"
    assert "What we're trying to figure out" in post.content


def test_create_with_custom_body(initialised_vault):
    r = _run("--title", "Auth strategy",
             body="# Auth strategy\n\nThe question is custom.\n",
             env=os.environ.copy())
    assert r.returncode == 0, r.stderr
    mem = initialised_vault
    matches = list((mem / "propositions").glob("*-auth-strategy.md"))
    assert matches
    post = frontmatter.load(matches[0])
    assert "The question is custom" in post.content


def test_promote_to_settled(initialised_vault):
    r = _run("--title", "Pick a DB", env=os.environ.copy())
    assert r.returncode == 0
    mem = initialised_vault
    p = next((mem / "propositions").glob("*-pick-a-db.md"))
    rel = str(p.relative_to(mem))
    r2 = _run("--update", rel,
              "--settled-as", "decisions/2026-05-25-postgres.md",
              env=os.environ.copy())
    assert r2.returncode == 0, r2.stderr
    post = frontmatter.load(p)
    assert post.metadata["status"] == "settled-as-decision"
    assert post.metadata["settled_as"] == "decisions/2026-05-25-postgres.md"
    assert "settled_at" in post.metadata


def test_promote_to_refuted(initialised_vault):
    r = _run("--title", "Should we rewrite?", env=os.environ.copy())
    assert r.returncode == 0
    mem = initialised_vault
    p = next((mem / "propositions").glob("*-should-we-rewrite.md"))
    rel = str(p.relative_to(mem))
    r2 = _run("--update", rel,
              "--refuted-as", "lessons/2026-05-25-stuck-with-it.md",
              env=os.environ.copy())
    assert r2.returncode == 0, r2.stderr
    post = frontmatter.load(p)
    assert post.metadata["status"] == "refuted-as-lesson"
    assert post.metadata["refuted_as"] == "lessons/2026-05-25-stuck-with-it.md"


def test_invalid_status_rejected(initialised_vault):
    r = _run("--title", "X", "--status", "totally-made-up",
             env=os.environ.copy())
    assert r.returncode != 0


def test_init_creates_propositions_scope(initialised_vault):
    """initialised_vault fixture runs init-memory.py which must create
    the propositions/ scope as part of the standard layout."""
    assert (initialised_vault / "propositions").is_dir()


# --- debate log: append positions ------------------------------------------

def _create(initialised_vault, title="Should we shard tenants?"):
    r = _run("--title", title, env=os.environ.copy())
    assert r.returncode == 0, r.stderr
    # Resolve the exact file we created (init seeds a sample proposition, so a
    # bare glob is ambiguous).
    line = next(line for line in r.stdout.splitlines()
                if "proposition created:" in line)
    rel = line.split("proposition created:", 1)[1].strip()
    return initialised_vault / rel


def test_position_against_bumps_open_to_contested(initialised_vault):
    p = _create(initialised_vault)
    rel = str(p.relative_to(initialised_vault))
    r = _run("--update", rel, "--position", "--stance", "against",
             body="Sharding adds ops burden we can't staff.",
             env=os.environ.copy())
    assert r.returncode == 0, r.stderr
    post = frontmatter.load(p)
    assert post.metadata["status"] == "contested"
    assert "## Debate log" in post.content
    assert "against" in post.content
    assert "ops burden" in post.content


def test_position_for_keeps_status_open(initialised_vault):
    p = _create(initialised_vault)
    rel = str(p.relative_to(initialised_vault))
    r = _run("--update", rel, "--position", "--stance", "for",
             body="Sharding is the only way to hit the isolation SLA.",
             env=os.environ.copy())
    assert r.returncode == 0, r.stderr
    post = frontmatter.load(p)
    assert post.metadata["status"] == "open"


def test_positions_are_append_only(initialised_vault):
    p = _create(initialised_vault)
    rel = str(p.relative_to(initialised_vault))
    _run("--update", rel, "--position", "--stance", "for",
         body="First position keep-me.", env=os.environ.copy())
    _run("--update", rel, "--position", "--stance", "against",
         body="Second position also-keep-me.", env=os.environ.copy())
    post = frontmatter.load(p)
    # Both positions survive — the second did not clobber the first.
    assert "keep-me" in post.content
    assert "also-keep-me" in post.content
    assert post.content.count("## Debate log") == 1  # one section, two entries


def test_position_requires_body(initialised_vault):
    p = _create(initialised_vault)
    rel = str(p.relative_to(initialised_vault))
    r = _run("--update", rel, "--position", "--stance", "against",
             body="", env=os.environ.copy())
    assert r.returncode == 2


def test_position_without_update_errors(initialised_vault):
    """--position is append-to-existing; without --update it must NOT silently
    create a new note."""
    r = _run("--position", "--stance", "against", "--title", "Stray",
             body="prose", env=os.environ.copy())
    assert r.returncode == 2
    # No proposition titled 'stray' was created.
    assert not list((initialised_vault / "propositions").glob("*-stray.md"))


def test_position_with_settled_as_errors(initialised_vault):
    """A co-passed settle/refute must error, not be silently dropped."""
    p = _create(initialised_vault)
    rel = str(p.relative_to(initialised_vault))
    r = _run("--update", rel, "--position", "--stance", "for",
             "--settled-as", "decisions/2026-05-30-x.md",
             body="prose", env=os.environ.copy())
    assert r.returncode == 2

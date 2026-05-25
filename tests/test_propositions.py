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

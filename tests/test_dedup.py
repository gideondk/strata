"""Tests for the recall-before-write dedup gate on decisions."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN_ROOT = HERE.parent
ND = PLUGIN_ROOT / "scripts" / "new-decision.py"

# Make `import dedup` work without requiring a vault fixture.
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))


def _write(mem, rel, content):
    p = mem / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


def _run_decision(args, body="", env=None):
    """Invoke new-decision.py as a subprocess with the semantic layer disabled
    so the exact-title + FTS path is exercised deterministically and fast."""
    e = os.environ.copy()
    e["STRATA_DISABLE_EMBEDDINGS"] = "1"
    if env:
        e.update(env)
    return subprocess.run(
        [sys.executable, str(ND), *args],
        input=body, capture_output=True, text=True, check=False, env=e,
    )


def _existing_decision(mem, title="Use Postgres for tenants", status="accepted",
                       rel="decisions/2026-05-01-use-postgres.md"):
    _write(mem, rel, f"---\ntitle: {title}\nstatus: {status}\n---\n"
                     f"We chose Postgres.\n")


# --- classify() unit tests (no subprocess, no vault) -----------------------

def _cand(**kw):
    base = {"path": "decisions/x.md", "title": "X", "status": "accepted",
            "semantic": None, "fts": False, "exact_title": False}
    base.update(kw)
    return base


def test_classify_blocks_on_exact_title(monkeypatch):
    import dedup
    monkeypatch.setattr(dedup, "embeddings_available", lambda: True)
    verdict, top = dedup.classify([_cand(exact_title=True)])
    assert verdict == "block"
    assert top is not None


def test_classify_blocks_on_high_semantic(monkeypatch):
    import dedup
    monkeypatch.setattr(dedup, "embeddings_available", lambda: True)
    verdict, _ = dedup.classify([_cand(semantic=0.91)])
    assert verdict == "block"


def test_classify_warns_on_soft_semantic(monkeypatch):
    import dedup
    monkeypatch.setattr(dedup, "embeddings_available", lambda: True)
    verdict, _ = dedup.classify([_cand(semantic=0.80)])
    assert verdict == "warn"


def test_classify_resolved_exact_title_warns_not_blocks(monkeypatch):
    """A same-title match against superseded history must NOT hard-block."""
    import dedup
    monkeypatch.setattr(dedup, "embeddings_available", lambda: True)
    verdict, _ = dedup.classify([_cand(exact_title=True, status="superseded")])
    assert verdict == "warn"


def test_classify_fts_only_warns_without_embeddings(monkeypatch):
    import dedup
    monkeypatch.setattr(dedup, "embeddings_available", lambda: False)
    verdict, _ = dedup.classify([_cand(fts=True)])
    assert verdict == "warn"


def test_classify_fts_only_clears_with_embeddings(monkeypatch):
    """With the semantic layer present, keyword overlap that didn't clear the
    soft cosine bar is not a duplicate — don't even warn."""
    import dedup
    monkeypatch.setattr(dedup, "embeddings_available", lambda: True)
    verdict, _ = dedup.classify([_cand(fts=True)])
    assert verdict == "clear"


def test_classify_clear_when_empty():
    import dedup
    verdict, top = dedup.classify([])
    assert verdict == "clear"
    assert top is None


# --- _norm_title (regression guards for the review findings) ---------------

def test_norm_title_has_no_length_cap():
    """Distinct long titles sharing a 48-char prefix must NOT collide (else a
    legitimate new ADR gets a false-positive hard block)."""
    import dedup
    a = dedup._norm_title(
        "Use PostgreSQL as the primary datastore for tenant isolation in production")
    b = dedup._norm_title(
        "Use PostgreSQL as the primary datastore for tenant isolation in staging")
    assert a != b


def test_norm_title_folds_punctuation_and_case():
    import dedup
    base = dedup._norm_title("Use SQLite")
    assert dedup._norm_title("use sqlite.") == base   # trailing dot
    assert dedup._norm_title("Use  SQLite!") == base  # punctuation + spacing


def test_norm_title_empty_for_alnum_empty():
    import dedup
    assert dedup._norm_title("***") == ""
    assert dedup._norm_title("???") == ""


# --- find_similar_decisions (FTS + exact-title, no fastembed) --------------

def test_find_similar_exact_title(initialised_vault, monkeypatch):
    import dedup
    monkeypatch.setattr(dedup, "embeddings_available", lambda: False)
    mem = initialised_vault
    _existing_decision(mem)
    found = dedup.find_similar_decisions("use postgres for tenants")
    assert any(c["exact_title"] for c in found)


def test_find_similar_fts_overlap(initialised_vault, monkeypatch):
    import dedup
    monkeypatch.setattr(dedup, "embeddings_available", lambda: False)
    mem = initialised_vault
    _write(mem, "decisions/2026-05-02-redis-cache.md",
           "---\ntitle: Adopt Redis for caching\nstatus: accepted\n---\nbody\n")
    found = dedup.find_similar_decisions("Adopt Redis for the cache layer")
    assert any(c["fts"] and "redis" in c["path"] for c in found)


def test_find_similar_ignores_unrelated(initialised_vault, monkeypatch):
    import dedup
    monkeypatch.setattr(dedup, "embeddings_available", lambda: False)
    mem = initialised_vault
    _existing_decision(mem)
    found = dedup.find_similar_decisions("Rotate JWT signing keys quarterly")
    assert found == []


# --- new-decision.py gate (subprocess) -------------------------------------

def test_gate_blocks_duplicate_title(initialised_vault):
    mem = initialised_vault
    _existing_decision(mem)
    r = _run_decision(["--title", "Use Postgres for tenants"],
                      body="## Decision\nUse Postgres.\n")
    assert r.returncode == 3, r.stderr
    assert "dedup" in r.stderr.lower()
    # No second file was written.
    assert len(list((mem / "decisions").glob("*use-postgres*.md"))) == 1


def test_ack_new_bypasses_block(initialised_vault):
    mem = initialised_vault
    _existing_decision(mem)
    r = _run_decision(["--title", "Use Postgres for tenants", "--ack-new"],
                      body="## Decision\nDifferent context.\n")
    assert r.returncode == 0, r.stderr
    assert len(list((mem / "decisions").glob("*use-postgres*.md"))) == 2


def test_supersedes_bypasses_gate(initialised_vault):
    mem = initialised_vault
    _existing_decision(mem)
    r = _run_decision(
        ["--title", "Use Postgres for tenants", "--status", "accepted",
         "--supersedes", "2026-05-01-use-postgres"],
        body="## Decision\nNewer take.\n",
    )
    assert r.returncode == 0, r.stderr


def test_check_only_emits_json_and_does_not_write(initialised_vault):
    mem = initialised_vault
    _existing_decision(mem)
    before = list((mem / "decisions").glob("*.md"))
    r = _run_decision(["--title", "Use Postgres for tenants", "--check-only"],
                      body="## Decision\nUse Postgres.\n")
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["recommendation"] == "block"
    assert payload["candidates"]
    # Nothing written.
    assert list((mem / "decisions").glob("*.md")) == before


def test_no_dedup_bypasses_gate(initialised_vault):
    mem = initialised_vault
    _existing_decision(mem)
    r = _run_decision(["--title", "Use Postgres for tenants", "--no-dedup"],
                      body="## Decision\nUse Postgres.\n")
    assert r.returncode == 0, r.stderr
    assert len(list((mem / "decisions").glob("*use-postgres*.md"))) == 2


def test_distinct_title_writes_cleanly(initialised_vault):
    mem = initialised_vault
    _existing_decision(mem)
    r = _run_decision(["--title", "Rotate JWT signing keys quarterly"],
                      body="## Decision\nRotate keys.\n")
    assert r.returncode == 0, r.stderr
    assert len(list((mem / "decisions").glob("*rotate-jwt*.md"))) == 1


def test_gate_warns_but_writes(initialised_vault):
    """A 'warn' (keyword overlap, not exact) must PROCEED and write — warn must
    never refuse a write. Protects the core warn-vs-block safety contract."""
    mem = initialised_vault
    _write(mem, "decisions/2026-05-02-redis-cache.md",
           "---\ntitle: Adopt Redis for caching\nstatus: accepted\n---\nbody\n")
    r = _run_decision(["--title", "Adopt Redis for the cache layer"],
                      body="## Decision\nUse Redis.\n")
    assert r.returncode == 0, r.stderr
    assert "dedup" in r.stderr.lower() or "similar" in r.stderr.lower()
    assert len(list((mem / "decisions").glob(
        "*adopt-redis-for-the-cache-layer*.md"))) == 1


def test_gate_allows_distinct_long_prefixed_titles(initialised_vault):
    """Two distinct ADRs sharing a long (>48 char) title prefix must not
    hard-block each other (regression for the safe_slug truncation bug)."""
    mem = initialised_vault
    _write(mem, "decisions/2026-05-03-pg-prod.md",
           "---\ntitle: Use PostgreSQL as the primary datastore for tenant "
           "isolation in production\nstatus: accepted\n---\nbody\n")
    r = _run_decision(
        ["--title", "Use PostgreSQL as the primary datastore for tenant "
                    "isolation in staging"],
        body="## Decision\nStaging store.\n",
    )
    assert r.returncode == 0, r.stderr  # must NOT be a hard block (exit 3)


def test_check_only_with_supersedes_short_circuits(initialised_vault):
    """--check-only alongside --supersedes is a documented no-op: it reports
    clear without retrieval and writes nothing."""
    mem = initialised_vault
    _existing_decision(mem)
    r = _run_decision(
        ["--title", "Use Postgres for tenants", "--check-only",
         "--supersedes", "2026-05-01-use-postgres"],
        body="x",
    )
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {"recommendation": "clear", "candidates": []}
    assert len(list((mem / "decisions").glob("*use-postgres*.md"))) == 1

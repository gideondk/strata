"""Tests for the offline retrieval-quality harness (eval.py)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))


def _write(mem, rel, content):
    p = mem / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


def test_load_cases_coerces_and_validates(tmp_path):
    import eval as evalmod
    p = tmp_path / "golden.json"
    p.write_text(json.dumps({"cases": [
        {"query": "q", "expected": "decisions/a.md"},          # str → list
        {"query": "r", "expected": ["decisions/b.md", "x.md"]},
    ]}))
    cases = evalmod.load_cases(p)
    assert cases[0]["expected"] == ["decisions/a.md"]
    assert cases[1]["expected"] == ["decisions/b.md", "x.md"]

    p.write_text(json.dumps({"cases": [{"query": "q"}]}))  # missing 'expected'
    with pytest.raises(ValueError):
        evalmod.load_cases(p)


def test_evaluate_scores_recall_and_mrr(initialised_vault, monkeypatch):
    monkeypatch.setenv("STRATA_DISABLE_EMBEDDINGS", "1")  # FTS-only, deterministic
    import db
    import eval as evalmod
    mem = initialised_vault
    _write(mem, "decisions/2026-05-01-token-bucket.md",
           "---\ntitle: Token bucket rate limiting\nstatus: accepted\n---\n"
           "We rate limit with a token bucket.\n")
    _write(mem, "decisions/2026-05-02-unrelated.md",
           "---\ntitle: Logging format\n---\nStructured logs.\n")
    db.reindex(force=True)

    cases = [{"query": "rate limiting token bucket",
              "expected": ["decisions/2026-05-01-token-bucket.md"],
              "scope": "decisions"}]
    report = evalmod.evaluate(cases, k=5)
    assert report["cases"] == 1
    assert report["recall_at_k"] == 1.0   # the expected note was retrieved
    assert report["mrr"] > 0.0


def test_sweep_reports_both_pipelines(initialised_vault, monkeypatch):
    """--sweep compares rerank off vs on. With an injected scorer that's a
    no-op, both rows are equal — but the comparison structure must be present."""
    monkeypatch.setenv("STRATA_DISABLE_EMBEDDINGS", "1")
    import json as _json
    import subprocess
    import sys as _sys
    mem = initialised_vault
    _write(mem, "decisions/2026-05-01-x.md",
           "---\ntitle: Token bucket\n---\nrate limit body.\n")
    import db
    db.reindex(force=True)
    gp = mem / ".eval" / "golden.json"
    gp.parent.mkdir(parents=True, exist_ok=True)
    gp.write_text(_json.dumps({"cases": [
        {"query": "token bucket", "expected": ["decisions/2026-05-01-x.md"],
         "scope": "decisions"}]}))
    r = subprocess.run(
        [_sys.executable, str(HERE.parent / "scripts" / "eval.py"),
         "--sweep", "--json", "-k", "5"],
        capture_output=True, text=True, check=False, env=__import__("os").environ.copy())
    assert r.returncode == 0, r.stderr
    payload = _json.loads(r.stdout)
    assert "off" in payload and "on" in payload
    assert "recall_at_k" in payload["off"] and "recall_at_k" in payload["on"]


def test_evaluate_counts_a_miss(initialised_vault, monkeypatch):
    monkeypatch.setenv("STRATA_DISABLE_EMBEDDINGS", "1")
    import db
    import eval as evalmod
    mem = initialised_vault
    _write(mem, "decisions/2026-05-01-real.md", "---\ntitle: Real\n---\nbody.\n")
    db.reindex(force=True)
    cases = [{"query": "nonexistent zzqqxx topic",
              "expected": ["decisions/2026-05-99-ghost.md"], "scope": None}]
    report = evalmod.evaluate(cases, k=5)
    assert report["recall_at_k"] == 0.0
    assert report["per_case"][0]["miss"] == ["decisions/2026-05-99-ghost.md"]

"""Tests for the unified recall surface — Layer 1/2/3 + scope/since filters."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RECALL = HERE.parent / "scripts" / "recall.py"


def _run(*args, env=None):
    return subprocess.run(
        [sys.executable, str(RECALL), *args],
        capture_output=True, text=True, check=False, env=env,
    )


def _seed(mem: Path, rel: str, title: str, body: str = ""):
    p = mem / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    fm = f"---\ntitle: {title}\nstatus: stable\n---\n\n"
    p.write_text(fm + (body or f"# {title}\n"))
    return p


def test_layer1_returns_compact_index(initialised_vault):
    mem = initialised_vault
    _seed(mem, "domain/order-aggregate.md", "Order Aggregate",
          "# Order Aggregate\nHandles order state.\n")
    _seed(mem, "domain/payment-aggregate.md", "Payment Aggregate",
          "# Payment\nHandles payment state.\n")
    r = _run("--query", "order", "--layer", "1", "--budget", "400",
             env=os.environ.copy())
    assert r.returncode == 0
    out = r.stdout
    assert "order-aggregate.md" in out
    # Each line is short — under 200 chars for a single hit
    longest = max(len(line) for line in out.splitlines() if line) if out else 0
    assert longest < 250, f"layer1 line too long: {longest}"


def test_layer3_returns_full_body(initialised_vault):
    mem = initialised_vault
    _seed(mem, "domain/widget.md", "Widget",
          "# Widget\n\nA widget is the thing that does the widgetting. "
          "It contains the secret sauce.\n")
    r = _run("--query", "widget", "--layer", "3", "--budget", "800",
             env=os.environ.copy())
    assert r.returncode == 0
    assert "secret sauce" in r.stdout


def test_scope_filter_narrows_results(initialised_vault):
    mem = initialised_vault
    _seed(mem, "domain/auth.md", "Auth domain", "# Auth\nTokens.\n")
    _seed(mem, "decisions/2026-05-25-use-jwt.md", "Use JWT",
          "# Use JWT\nFor auth tokens.\n")
    r = _run("--query", "auth", "--scope", "decisions", "--layer", "1",
             env=os.environ.copy())
    assert r.returncode == 0
    assert "decisions/" in r.stdout
    assert "domain/auth.md" not in r.stdout


def test_no_matches_returns_friendly_message(initialised_vault):
    r = _run("--query", "totallymadeupnotexistingterm", "--layer", "1",
             env=os.environ.copy())
    assert r.returncode == 0
    assert "no relevant" in r.stdout.lower()


def test_budget_truncates_layer3(initialised_vault):
    mem = initialised_vault
    body = "# Huge\n\n" + ("word " * 5000)  # ~25KB
    _seed(mem, "domain/huge.md", "Huge note", body)
    r = _run("--query", "huge", "--layer", "3", "--budget", "200",
             env=os.environ.copy())
    assert r.returncode == 0
    # ~200 tokens * 4 chars + a bit of frame = should be under 1500 chars
    assert len(r.stdout) < 1500
    assert "..." in r.stdout


def test_invalidated_notes_excluded_by_default(initialised_vault):
    """Recall must not surface notes with status=invalidated. Pin the
    same filter behaviour as direct db.search()."""
    mem = initialised_vault
    _seed(mem, "domain/active.md", "Active", "# Active\nOrders.\n")
    p = mem / "domain" / "retired.md"
    p.write_text("---\ntitle: Retired\nstatus: invalidated\n---\n\n"
                 "# Retired\nOrders.\n")
    r = _run("--query", "orders", "--layer", "1", env=os.environ.copy())
    assert r.returncode == 0
    assert "domain/active.md" in r.stdout
    assert "domain/retired.md" not in r.stdout

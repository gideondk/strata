"""Symbol verification in /strata:decide against Graphify graph.json."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
NEW_DECISION = HERE.parent / "scripts" / "new-decision.py"


def _run(*args, body="body", env=None):
    return subprocess.run(
        [sys.executable, str(NEW_DECISION), *args],
        input=body,
        capture_output=True, text=True, check=False,
        env=env,
    )


def _write_graph(repo, payload):
    out = repo / "graphify-out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "graph.json").write_text(json.dumps(payload), encoding="utf-8")


def test_decide_succeeds_without_graph(initialised_vault, env):
    """No graph → symbol check is a no-op."""
    r = _run(
        "--title", "Test decision",
        body="Body mentions `SomeUnknownClass`.",
        env=os.environ.copy(),
    )
    assert r.returncode == 0


def test_decide_warns_on_unknown_symbol_when_graph_present(
        initialised_vault, env):
    """Graph present, body mentions unknown symbol → warns to stderr but
    still writes the ADR (default = non-strict)."""
    _write_graph(env["repo"], {
        "nodes": [{"id": "RealClass", "name": "RealClass"}],
        "edges": [],
    })
    r = _run(
        "--title", "Decision with typo",
        body="We will refactor `TypoClass` next week.",
        env=os.environ.copy(),
    )
    assert r.returncode == 0
    assert "TypoClass" in r.stderr
    assert "unresolved" in r.stderr


def test_decide_strict_symbols_blocks(initialised_vault, env):
    """--strict-symbols blocks the ADR when symbols don't resolve."""
    _write_graph(env["repo"], {
        "nodes": [{"id": "RealClass", "name": "RealClass"}],
        "edges": [],
    })
    r = _run(
        "--title", "Decision with typo strict",
        "--strict-symbols",
        body="We will refactor `TypoClass` next week.",
        env=os.environ.copy(),
    )
    assert r.returncode == 1


def test_decide_strict_passes_when_all_symbols_resolve(
        initialised_vault, env):
    """--strict-symbols allows the ADR when every backtick identifier
    matches a graph node."""
    _write_graph(env["repo"], {
        "nodes": [
            {"id": "OrderService", "name": "OrderService"},
            {"id": "PaymentQueue", "name": "PaymentQueue"},
        ],
        "edges": [],
    })
    r = _run(
        "--title", "Decision with valid refs",
        "--strict-symbols",
        body="Move logic from `OrderService` to `PaymentQueue` consumer.",
        env=os.environ.copy(),
    )
    assert r.returncode == 0


def test_decide_ignores_lowercase_short_words(initialised_vault, env):
    """Backticks around `the` or `null` shouldn't trigger symbol checks."""
    _write_graph(env["repo"], {
        "nodes": [{"id": "Foo"}],
        "edges": [],
    })
    r = _run(
        "--title", "Decision with code keywords",
        "--strict-symbols",
        body="When `the` value is `null`, fall back to default.",
        env=os.environ.copy(),
    )
    # Should pass — no uppercase / underscore / dot triggers
    assert r.returncode == 0

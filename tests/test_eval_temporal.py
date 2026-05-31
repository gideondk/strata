"""Integration test for the temporal/supersession benchmark harness.

Runs the real harness end-to-end (it builds a throwaway vault from the committed
pilot fixture, indexes it, and runs recall ON vs OFF) as a subprocess so it
can't leak its env mutation into the pytest process."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HARNESS = HERE.parent / "scripts" / "eval_temporal.py"
CASES = HERE.parent / "eval" / "temporal" / "cases.json"


def test_pilot_fixture_exists_and_parses():
    data = json.loads(CASES.read_text())
    assert data["cases"], "pilot temporal set must have cases"
    for c in data["cases"]:
        assert c.get("current") and c.get("superseded"), c["fact_id"]


def test_benchmark_runs_and_demotion_lifts_suppression():
    r = subprocess.run([sys.executable, str(HARNESS), "--json"],
                       capture_output=True, text=True, env=os.environ.copy())
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    supp = out["summary"]["stale_suppression"]
    rec = out["summary"]["current_recall@k"]
    # On the deliberately-hard pilot set the demotion must clearly beat OFF…
    assert supp["P(on>off)"] >= 0.95, supp
    # …and must NOT cost current-note findability (recall holds across arms).
    assert rec["on"].split(" = ")[0] == rec["off"].split(" = ")[0], rec

"""Tests for the warn-only secret/PII pre-step shared by save / decide."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN_ROOT = HERE.parent
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))


def test_warn_findings_flags_secret_and_clears_prose():
    import lint_check
    assert lint_check.warn_findings("token = AKIAIOSFODNN7EXAMPLE")
    assert lint_check.warn_findings("a normal note about rate limiting") == []


def test_unknown_preset_does_not_crash(initialised_vault):
    """memory-lint.load_presets sys.exit(2)s on an unknown preset; the pre-step
    must swallow that (SystemExit) and return [], never abort the caller."""
    import lint_check
    assert lint_check.warn_findings("anything", preset="nonexistent-zzz") == []


def test_save_warns_on_secret_but_still_saves(initialised_vault):
    """The pre-step is advisory: a detected secret warns on stderr but the save
    still succeeds (a false positive must never block a save)."""
    mem = initialised_vault
    save = PLUGIN_ROOT / "scripts" / "save-note.py"
    r = subprocess.run(
        [sys.executable, str(save), "--topic", "creds-note", "--kind", "session"],
        input="deploy key AKIAIOSFODNN7EXAMPLE pasted here",
        capture_output=True, text=True, check=False, env=os.environ.copy())
    assert r.returncode == 0, r.stderr          # still saves
    assert "lint" in r.stderr.lower()            # but warned
    assert list((mem / "pr-context").rglob("*creds-note.md"))

"""The `bin/strata` front-door dispatcher.

Skills call `strata <command>` instead of raw `run-python.sh .../scripts/<x>.py`
so a vault write reads as an intention-revealing command in the transcript. These
tests guard the two things that would silently break that: a command mapping to a
script that doesn't exist, and the dispatcher not failing closed on bad input.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_STRATA = _ROOT / "bin" / "strata"
_SCRIPTS = _ROOT / "scripts"


def _run(*args: str, stdin: str = "") -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(_STRATA), *args], input=stdin,
        capture_output=True, text=True, timeout=60,
    )


def _mapped_scripts() -> dict[str, str]:
    """Parse the case arms: `  word) script="x.py" ;;` → {word: x.py}."""
    text = _STRATA.read_text()
    pairs = re.findall(r'^\s*([a-z][a-z-]*)\)\s*script="([^"]+)"', text, re.M)
    return dict(pairs)


def test_dispatcher_is_executable():
    assert _STRATA.exists(), "bin/strata missing"
    assert _STRATA.stat().st_mode & 0o111, "bin/strata is not executable"


def test_every_command_maps_to_an_existing_script():
    mapping = _mapped_scripts()
    assert mapping, "no command→script arms parsed from bin/strata"
    missing = {cmd: s for cmd, s in mapping.items()
               if not (_SCRIPTS / s).exists()}
    assert not missing, f"commands point at missing scripts: {missing}"


def test_help_lists_commands_and_exits_zero():
    proc = _run("help")
    assert proc.returncode == 0
    # help prints to stderr; a few representative commands must appear.
    for cmd in ("decide", "procedure", "find", "reindex"):
        assert cmd in proc.stderr


def test_no_argument_fails_closed():
    proc = _run()
    assert proc.returncode == 2


def test_unknown_command_fails_closed():
    proc = _run("definitely-not-a-command")
    assert proc.returncode == 2
    assert "unknown command" in proc.stderr


@pytest.mark.parametrize("cmd", ["decide", "propose", "procedure", "save",
                                 "correct", "invalidate", "forget", "find",
                                 "review", "reindex"])
def test_core_commands_are_mapped(cmd):
    assert cmd in _mapped_scripts()

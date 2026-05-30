"""Shared secret/PII pre-step for write paths (save / decide / observe).

Secret-scanning a note before it lands must NOT depend on a probabilistic skill
pick (see the skills-UX research) — so save-note.py / new-decision.py call
`warn_findings()` here directly. Warn-only by design: it surfaces hits on stderr
and never blocks the write (a false positive must never stop you saving). The
standalone /strata:lint command remains for an explicit, blocking scan.
"""
from __future__ import annotations

import contextlib
import importlib.util
import os

import lib_loader  # noqa: F401

_MOD = None


def _memory_lint():
    """Import the hyphenated memory-lint.py module once (best-effort)."""
    global _MOD
    if _MOD is not None:
        return _MOD
    path = os.path.join(os.path.dirname(__file__), "memory-lint.py")
    spec = importlib.util.spec_from_file_location("memory_lint", path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _MOD = mod
    return mod


def warn_findings(text: str, preset: str = "secrets") -> list[str]:
    """Scan `text` with the given preset; return human-readable warning lines
    (empty when clean or on any failure). Never raises."""
    out: list[str] = []
    # Catch SystemExit too: memory-lint.load_presets() calls sys.exit(2) on an
    # unknown/missing preset, which suppress(Exception) would NOT catch — and a
    # pre-step must never abort the save it's advising on.
    with contextlib.suppress(Exception, SystemExit):
        ml = _memory_lint()
        if ml is None:
            return []
        blocks, warns = ml.load_presets([preset])
        for kind, rule, offset, snippet in ml.scan_text(text, blocks, warns):
            line, _col = ml._line_col(text, offset)
            out.append(f"[{kind}] {rule} (line {line}): {snippet}")
    return out


def emit_warnings(text: str, *, label: str = "note") -> None:
    """Print any secret/PII findings to stderr as an advisory pre-step. Best-
    effort; never blocks or raises into the caller."""
    import sys
    with contextlib.suppress(Exception, SystemExit):
        findings = warn_findings(text)
        if findings:
            print(f"[strata] lint: possible sensitive content in this {label} "
                  f"— review before sharing (use /strata:forget to redact):",
                  file=sys.stderr)
            for f in findings[:10]:
                print(f"  {f}", file=sys.stderr)

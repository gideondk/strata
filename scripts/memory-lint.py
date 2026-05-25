#!/usr/bin/env python3
"""Strata memory lint — scan files for secrets and (opt-in) PII/PHI.

Stdlib only. Patterns are loaded from JSON preset packs in ../presets/,
so the catalogue is extensible without touching code.

Usage:
  python3 memory-lint.py                          # scan vault, secrets preset
  python3 memory-lint.py --preset secrets,phi-uk  # multi-preset
  python3 memory-lint.py --scope staged           # staged *.md in host repo
  python3 memory-lint.py --scope <path>           # one file or dir
  python3 memory-lint.py --strict                 # warnings become blocks
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import lib_loader  # noqa: F401
from lib import memory_dir, plugin_root, project_dir

# ---------------------------------------------------------------------------
# Validators — referenced by name from preset JSON
# ---------------------------------------------------------------------------

def _nhs_mod11(match: re.Match[str]) -> bool:
    digits = re.sub(r"[ -]", "", match.group(0))
    if len(digits) != 10 or not digits.isdigit():
        return False
    s = sum(int(digits[i]) * (10 - i) for i in range(9))
    remainder = s % 11
    check = (11 - remainder) % 11
    if check == 10:
        return False
    return check == int(digits[9])


def _luhn(match: re.Match[str]) -> bool:
    digits = re.sub(r"[ -]", "", match.group(0))
    if not (12 <= len(digits) <= 19) or not digits.isdigit():
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _us_ssn(match: re.Match[str]) -> bool:
    """US Social Security Number heuristic: reject the obvious invalid ranges
    while still flagging values likely to be real (including ITINs)."""
    digits = re.sub(r"[ -]", "", match.group(0))
    if len(digits) != 9 or not digits.isdigit():
        return False
    area, group, serial = digits[:3], digits[3:5], digits[5:]
    if area in ("000", "666"):
        return False
    return group != "00" and serial != "0000"


def _dea_checksum(match: re.Match[str]) -> bool:
    """US DEA registration number checksum.

    Format: 2 letters + 7 digits. The 7th digit equals
    (d1+d3+d5 + 2*(d2+d4+d6)) mod 10.
    """
    s = match.group(0)
    if len(s) != 9:
        return False
    digits = s[2:]
    if not digits.isdigit():
        return False
    d = [int(c) for c in digits]
    expected = (d[0] + d[2] + d[4] + 2 * (d[1] + d[3] + d[5])) % 10
    return expected == d[6]


# Country code → expected IBAN length (subset; covers all current SEPA + most
# common others. Unknown country codes fall through to a generic 15-34 range.)
_IBAN_LEN: dict[str, int] = {
    "AD": 24, "AE": 23, "AL": 28, "AT": 20, "AZ": 28, "BA": 20, "BE": 16,
    "BG": 22, "BH": 22, "BR": 29, "BY": 28, "CH": 21, "CR": 22, "CY": 28,
    "CZ": 24, "DE": 22, "DK": 18, "DO": 28, "EE": 20, "EG": 29, "ES": 24,
    "FI": 18, "FO": 18, "FR": 27, "GB": 22, "GE": 22, "GI": 23, "GL": 18,
    "GR": 27, "GT": 28, "HR": 21, "HU": 28, "IE": 22, "IL": 23, "IQ": 23,
    "IS": 26, "IT": 27, "JO": 30, "KW": 30, "KZ": 20, "LB": 28, "LC": 32,
    "LI": 21, "LT": 20, "LU": 20, "LV": 21, "MC": 27, "MD": 24, "ME": 22,
    "MK": 19, "MR": 27, "MT": 31, "MU": 30, "NL": 18, "NO": 15, "PK": 24,
    "PL": 28, "PS": 29, "PT": 25, "QA": 29, "RO": 24, "RS": 22, "SA": 24,
    "SE": 24, "SI": 19, "SK": 24, "SM": 27, "TN": 24, "TR": 26, "UA": 29,
    "VA": 22, "VG": 24, "XK": 20,
}


def _iban_mod97(match: re.Match[str]) -> bool:
    """ISO 13616 / 7064 IBAN check.

    Steps: move first 4 chars (country + check) to the end, convert letters
    A-Z to 10-35, parse as a big integer, mod 97 must equal 1.
    """
    s = match.group(0).upper()
    if len(s) < 15:
        return False
    country = s[:2]
    expected = _IBAN_LEN.get(country)
    if expected is not None and len(s) != expected:
        return False
    rearranged = s[4:] + s[:4]
    try:
        numeric = "".join(
            str(ord(c) - 55) if c.isalpha() else c
            for c in rearranged
        )
    except Exception:
        return False
    try:
        return int(numeric) % 97 == 1
    except ValueError:
        return False


VALIDATORS: dict[str, Callable[[re.Match[str]], bool]] = {
    "nhs_mod11": _nhs_mod11,
    "luhn": _luhn,
    "us_ssn": _us_ssn,
    "dea_checksum": _dea_checksum,
    "iban_mod97": _iban_mod97,
}

# ---------------------------------------------------------------------------
# Preset loading
# ---------------------------------------------------------------------------


def _compile_flags(s: str | None) -> int:
    if not s:
        return 0
    flags = 0
    for ch in s:
        if ch == "i":
            flags |= re.IGNORECASE
        elif ch == "m":
            flags |= re.MULTILINE
        elif ch == "s":
            flags |= re.DOTALL
    return flags


class CompiledRule:
    __slots__ = ("name", "regex", "validator")

    def __init__(self, name: str, regex: re.Pattern[str],
                 validator: Callable[[re.Match[str]], bool] | None):
        self.name = name
        self.regex = regex
        self.validator = validator


def _compile_rules(raw: list[dict]) -> list[CompiledRule]:
    out: list[CompiledRule] = []
    for entry in raw:
        regex = re.compile(entry["regex"], _compile_flags(entry.get("flags")))
        validator = VALIDATORS.get(entry["validator"]) if entry.get("validator") else None
        out.append(CompiledRule(entry["name"], regex, validator))
    return out


def load_presets(names: list[str]) -> tuple[list[CompiledRule], list[CompiledRule]]:
    blocks: list[CompiledRule] = []
    warns: list[CompiledRule] = []
    preset_dir = plugin_root() / "presets"
    for name in names:
        path = preset_dir / f"{name}.json"
        if not path.exists():
            print(f"[strata] memory-lint: unknown preset '{name}' "
                  f"(looked in {preset_dir})", file=sys.stderr)
            sys.exit(2)
        raw = json.loads(path.read_text(encoding="utf-8"))
        blocks.extend(_compile_rules(raw.get("block", [])))
        warns.extend(_compile_rules(raw.get("warn", [])))
    return blocks, warns


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------


def scan_text(text: str, blocks: list[CompiledRule],
              warns: list[CompiledRule]) -> list[tuple[str, str, int, str]]:
    findings: list[tuple[str, str, int, str]] = []
    for rule in blocks:
        for m in rule.regex.finditer(text):
            if rule.validator and not rule.validator(m):
                continue
            findings.append(("BLOCK", rule.name, m.start(), m.group(0)[:64]))
    for rule in warns:
        for m in rule.regex.finditer(text):
            if rule.validator and not rule.validator(m):
                continue
            findings.append(("WARN", rule.name, m.start(), m.group(0)[:64]))
    return findings


def _line_col(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    col = offset - text.rfind("\n", 0, offset)
    return line, col


def _staged_md_in_project() -> list[Path]:
    pd = project_dir()
    if pd is None:
        return []
    try:
        out = subprocess.run(
            ["git", "-C", str(pd),
             "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        return []
    return [pd / p for p in out.stdout.splitlines() if p.endswith(".md")]


def _all_vault_files() -> list[Path]:
    mem = memory_dir()
    return list(mem.rglob("*.md")) if mem.exists() else []


def _files_for(scope: str) -> list[Path]:
    if scope == "staged":
        return _staged_md_in_project()
    if scope in ("vault", "all"):
        return _all_vault_files()
    p = Path(scope)
    if not p.is_absolute():
        pd = project_dir()
        p = (pd or Path.cwd()) / p
    if p.is_file():
        return [p]
    if p.is_dir():
        return list(p.rglob("*.md"))
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope", default="vault",
                    help="vault | staged | <relative-path>")
    ap.add_argument("--preset", default="secrets",
                    help="Comma-separated preset names. Defaults to 'secrets'. "
                         "Bundled: secrets, pii, phi-uk, phi-us, financial-iban. "
                         "Fork in presets/<name>.json.")
    ap.add_argument("--strict", action="store_true",
                    help="Treat WARN findings as BLOCK")
    ap.add_argument("--quiet", action="store_true",
                    help="Print only the summary line")
    args = ap.parse_args()

    presets = [p.strip() for p in args.preset.split(",") if p.strip()]
    blocks, warns = load_presets(presets)
    if not blocks and not warns:
        print("[strata] memory-lint: no rules loaded — check --preset", file=sys.stderr)
        return 2

    files = _files_for(args.scope)
    if not files:
        if not args.quiet:
            print("[strata] memory-lint: nothing to scan")
        return 0

    block_count = warn_count = 0
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            print(f"[strata] memory-lint: cannot read {f}: {e}", file=sys.stderr)
            continue

        findings = scan_text(text, blocks, warns)
        if not findings:
            continue

        pd = project_dir()
        try:
            rel = f.relative_to(pd).as_posix() if pd else f.as_posix()
        except ValueError:
            rel = f.as_posix()

        for level, name, off, snippet in findings:
            line, col = _line_col(text, off)
            effective = "BLOCK" if (level == "BLOCK" or args.strict) else "WARN"
            if not args.quiet:
                print(f"  [{effective}] {rel}:{line}:{col}  {name}  →  {snippet!r}")
            if effective == "BLOCK":
                block_count += 1
            else:
                warn_count += 1

    presets_str = ",".join(presets)
    if block_count:
        print(f"[strata] memory-lint: FAIL — {block_count} block, "
              f"{warn_count} warn ({presets_str})", file=sys.stderr)
        return 1
    print(f"[strata] memory-lint: OK ({warn_count} warn, presets={presets_str})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

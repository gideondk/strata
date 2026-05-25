"""Tests for memory-lint validators and preset loading."""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest


@pytest.fixture
def lint():
    """Import memory-lint.py (filename has a dash, so use importlib)."""
    here = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location(
        "memory_lint", here / "scripts" / "memory-lint.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["memory_lint"] = mod
    spec.loader.exec_module(mod)
    return mod


class TestValidators:
    def test_nhs_mod11_valid(self, lint):
        m = re.search(r"\d{10}", "9434765919")
        assert lint._nhs_mod11(m) is True

    def test_nhs_mod11_invalid(self, lint):
        m = re.search(r"\d{10}", "1234567890")
        assert lint._nhs_mod11(m) is False

    def test_luhn_valid_visa(self, lint):
        m = re.search(r"\d{16}", "4111111111111111")
        assert lint._luhn(m) is True

    def test_luhn_invalid(self, lint):
        m = re.search(r"\d{16}", "4111111111111112")
        assert lint._luhn(m) is False

    def test_us_ssn_valid(self, lint):
        m = re.search(r"\d{3}-\d{2}-\d{4}", "123-45-6789")
        assert lint._us_ssn(m) is True

    def test_us_ssn_invalid_area_000(self, lint):
        m = re.search(r"\d{3}-\d{2}-\d{4}", "000-45-6789")
        assert lint._us_ssn(m) is False

    def test_us_ssn_invalid_area_666(self, lint):
        m = re.search(r"\d{3}-\d{2}-\d{4}", "666-45-6789")
        assert lint._us_ssn(m) is False

    def test_us_ssn_invalid_serial_0000(self, lint):
        m = re.search(r"\d{3}-\d{2}-\d{4}", "123-45-0000")
        assert lint._us_ssn(m) is False

    def test_dea_checksum_known_valid(self, lint):
        m = re.search(r"[A-Z]{2}\d{7}", "AB1234563")
        assert lint._dea_checksum(m) is True

    def test_dea_checksum_invalid(self, lint):
        m = re.search(r"[A-Z]{2}\d{7}", "AB1234567")
        assert lint._dea_checksum(m) is False

    def test_iban_mod97_valid_gb(self, lint):
        # Well-known IBAN test value (Wikipedia)
        m = re.search(r"GB\d{2}[A-Z0-9]+", "GB82WEST12345698765432")
        assert lint._iban_mod97(m) is True

    def test_iban_mod97_invalid(self, lint):
        m = re.search(r"GB\d{2}[A-Z0-9]+", "GB82WEST12345698765431")
        assert lint._iban_mod97(m) is False

    def test_iban_mod97_wrong_length(self, lint):
        # GB IBAN is 22 chars; this is 24
        m = re.search(r"GB\d{2}[A-Z0-9]+", "GB82WEST1234569876543200")
        assert lint._iban_mod97(m) is False


class TestPresets:
    def test_loads_secrets(self, lint):
        blocks, _warns = lint.load_presets(["secrets"])
        assert len(blocks) > 0
        names = {b.name for b in blocks}
        assert "github-pat" in names

    def test_unknown_preset_exits(self, lint):
        with pytest.raises(SystemExit) as exc:
            lint.load_presets(["does-not-exist"])
        assert exc.value.code == 2

    def test_multi_preset_compose(self, lint):
        blocks, _ = lint.load_presets(["secrets", "pii", "phi-uk"])
        names = {b.name for b in blocks}
        assert "github-pat" in names
        assert "credit-card" in names
        assert "nhs-number" in names


class TestScanText:
    def test_finds_github_pat(self, lint):
        blocks, warns = lint.load_presets(["secrets"])
        findings = lint.scan_text(
            "token: ghp_abcdefghijklmnopqrstuvwxyz0123456789",
            blocks, warns,
        )
        assert any(name == "github-pat" for _, name, _, _ in findings)

    def test_clean_text(self, lint):
        blocks, warns = lint.load_presets(["secrets", "pii", "phi-uk", "phi-us"])
        findings = lint.scan_text(
            "The SSN flow goes through service X. We don't store NHS numbers.",
            blocks, warns,
        )
        # Word mentions only — no values — should be clean
        assert findings == []

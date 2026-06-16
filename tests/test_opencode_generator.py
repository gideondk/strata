"""Tests for the opencode skills generator.

Verifies that opencode/skills/ is derivable from skills/ with:
  - frontmatter name transformed to strata-<name> (opencode-legal)
  - Claude-Code-only keys stripped
  - no ${CLAUDE_PLUGIN_ROOT} references
  - folder names matching frontmatter names
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "skills"
_DST = _ROOT / "opencode" / "skills"
_STRATA = _ROOT / "bin" / "strata"

_CLAUDE_ONLY_KEYS = {"disable-model-invocation"}


def _source_skills() -> list[str]:
    return sorted(d.name for d in _SRC.iterdir() if (d / "SKILL.md").exists())


def test_opencode_skills_exist():
    if not _DST.exists():
        pytest.skip("opencode/skills/ not generated yet — run `strata generate-opencode-skills`")
    assert _DST.is_dir()


def test_every_source_skill_has_opencode_counterpart():
    if not _DST.exists():
        pytest.skip("opencode/skills/ not generated")
    for name in _source_skills():
        assert (_DST / f"strata-{name}" / "SKILL.md").exists(), \
            f"missing opencode skill for {name}"


@pytest.mark.skipif(not _DST.exists(), reason="opencode/skills/ not generated")
def test_frontmatter_names_match_folders():
    for d in sorted(_DST.iterdir()):
        skill = d / "SKILL.md"
        if not skill.exists():
            continue
        text = skill.read_text()
        for line in text.split("\n"):
            if line.startswith("name:"):
                fm_name = line.split(":", 1)[1].strip()
                assert fm_name == d.name, \
                    f"folder={d.name} but frontmatter name={fm_name}"
                assert ":" not in fm_name, \
                    f"colon in name {fm_name} — opencode rejects this"
                break
        else:
            pytest.fail(f"no name: in frontmatter for {d.name}")


@pytest.mark.skipif(not _DST.exists(), reason="opencode/skills/ not generated")
def test_no_claude_plugin_root_refs():
    offenders: list[str] = []
    for d in _DST.rglob("SKILL.md"):
        if "CLAUDE_PLUGIN_ROOT" in d.read_text():
            offenders.append(str(d))
    assert not offenders, f"CLAUDE_PLUGIN_ROOT leaked into: {offenders}"


@pytest.mark.skipif(not _DST.exists(), reason="opencode/skills/ not generated")
def test_no_claude_only_frontmatter_keys():
    offenders: list[str] = []
    for d in _DST.rglob("SKILL.md"):
        text = d.read_text()
        lines = text.split("\n")
        in_fm = False
        for line in lines:
            if line == "---":
                in_fm = not in_fm
                continue
            if in_fm:
                key = line.split(":")[0].strip() if ":" in line else ""
                if key in _CLAUDE_ONLY_KEYS:
                    offenders.append(f"{d}: {key}")
    assert not offenders, f"Claude-only keys leaked into: {offenders}"


def test_generator_is_idempotent(tmp_path):
    """Running the generator twice produces the same output."""
    proc = subprocess.run(
        [str(_STRATA), "generate-opencode-skills"],
        capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0
    first = {str(p.relative_to(_DST)): p.read_text()
             for p in _DST.rglob("SKILL.md")} if _DST.exists() else {}

    proc = subprocess.run(
        [str(_STRATA), "generate-opencode-skills"],
        capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0
    second = {str(p.relative_to(_DST)): p.read_text()
              for p in _DST.rglob("SKILL.md")} if _DST.exists() else {}

    assert first == second, "generator is not idempotent"


def test_generator_count_matches_source():
    if not _DST.exists():
        pytest.skip("opencode/skills/ not generated")
    src_count = len(_source_skills())
    dst_count = len(list(_DST.iterdir()))
    assert src_count == dst_count, \
        f"source has {src_count} skills, opencode has {dst_count}"

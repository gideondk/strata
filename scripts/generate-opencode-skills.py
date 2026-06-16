"""Generate opencode/skills/ from skills/.

opencode and Claude Code have different skill-naming conventions:
  - Claude Code: frontmatter `name: strata:save`, folder `save/`
  - opencode:    frontmatter `name: strata-save`, folder `strata-save/`

This script reads skills/<name>/SKILL.md, rewrites the frontmatter name to
`strata-<name>`, strips Claude-Code-only frontmatter keys, and writes
opencode/skills/strata-<name>/SKILL.md. The body is passed through verbatim —
skill bodies already use bare `strata` commands (no ${CLAUDE_PLUGIN_ROOT}).

Run via:  strata generate-opencode-skills
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "skills"
_DST = _ROOT / "opencode" / "skills"

# Claude Code frontmatter keys that opencode doesn't understand.
# opencode silently routes unknown keys into `options`, so they're harmless,
# but stripping them keeps the generated layer clean.
_CLAUDE_ONLY_KEYS = {"disable-model-invocation"}


def transform_name(raw: str) -> str:
    """`strata:save` → `strata-save`."""
    return raw.replace(":", "-")


def rewrite_frontmatter(text: str) -> str:
    """Transform the YAML frontmatter block: rename `name:`, strip CC-only keys."""
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return text

    fm = m.group(1)
    rest = text[m.end():]

    out: list[str] = []
    for line in fm.split("\n"):
        key = line.split(":")[0].strip() if ":" in line else ""
        if key in _CLAUDE_ONLY_KEYS:
            continue
        if line.startswith("name:"):
            old_name = line.split(":", 1)[1].strip()
            out.append(f"name: {transform_name(old_name)}")
        else:
            out.append(line)

    return "---\n" + "\n".join(out) + "\n---\n" + rest


def generate() -> None:
    if not _SRC.exists():
        raise SystemExit(f"skills/ not found at {_SRC}")

    # Clean slate.
    if _DST.exists():
        shutil.rmtree(_DST)
    _DST.mkdir(parents=True)

    count = 0
    for skill_dir in sorted(_SRC.iterdir()):
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue

        new_name = f"strata-{skill_dir.name}"
        out_dir = _DST / new_name
        out_dir.mkdir()
        (out_dir / "SKILL.md").write_text(rewrite_frontmatter(skill_md.read_text()))
        count += 1

    print(f"Generated {count} skills in {_DST}")


if __name__ == "__main__":
    generate()

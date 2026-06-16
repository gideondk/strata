"""Print the vault's INDEX.md (the cached dashboard).

Thin CLI wrapper so the dashboard skill's quick-read path doesn't need
inline Python or ${CLAUDE_PLUGIN_ROOT} path references. If INDEX.md doesn't
exist yet, prints nothing and exits 0 (the skill falls back to `strata dashboard`
which regenerates).
"""
from __future__ import annotations

from lib import memory_dir

index = memory_dir() / "INDEX.md"
if index.exists():
    print(index.read_text(), end="")

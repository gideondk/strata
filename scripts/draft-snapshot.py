"""Print a save-draft body composed from real git session state.

Thin CLI wrapper around session_state.draft_note_body(session_state.snapshot()).
Used by the `strata draft-snapshot` command so the save skill doesn't need
inline Python or ${CLAUDE_PLUGIN_ROOT} path references.
"""
from __future__ import annotations

import session_state

print(session_state.draft_note_body(session_state.snapshot()))

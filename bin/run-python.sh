#!/usr/bin/env bash
# strata — invoke a plugin script using the private venv.
#
# This wrapper is the SINGLE entry point for every script invocation:
# hooks, MCP server, skills. Doing it through here guarantees three things:
#
#   1. The private .venv/ exists (auto-bootstrapped on first call).
#   2. The script runs against the .venv's Python, not the system one.
#   3. STRATA_VAULT_PATH and STRATA_REPO_NAME are resolved from
#      Claude Code's userConfig — either via auto-exported
#      CLAUDE_PLUGIN_OPTION_* envs, or by reading
#      ~/.claude/settings.json directly as a last resort.
#
# This means callers never have to set env vars themselves. Whether
# Claude invokes us via a hook, an MCP server start, or a Bash tool from
# a SKILL.md, the script gets the right vault path.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv"

if [[ ! -x "$VENV/bin/python" ]] || [[ ! -f "$VENV/.strata-installed" ]]; then
  "$ROOT/bin/bootstrap-venv.sh"
fi

# Pull userConfig values into STRATA_* env vars if not already set.
# Order of precedence (highest first):
#   1. STRATA_* shell env (explicit override)
#   2. CLAUDE_PLUGIN_OPTION_* (Claude Code auto-export)
#   3. ~/.claude/settings.json `pluginConfigs.strata@strata.options`
#   4. Script default (~/StrataVault, auto-detected repo)

_promote_option() {
  local our_var="$1"
  local claude_var="$2"
  if [[ -z "${!our_var:-}" ]] && [[ -n "${!claude_var:-}" ]]; then
    export "$our_var=${!claude_var}"
  fi
}
_promote_option STRATA_VAULT_PATH CLAUDE_PLUGIN_OPTION_VAULT_PATH
_promote_option STRATA_REPO_NAME  CLAUDE_PLUGIN_OPTION_REPO_NAME

# Last-resort: read settings.json. Only do this if STRATA_VAULT_PATH
# still isn't set after the above. Cheap (one small JSON file).
if [[ -z "${STRATA_VAULT_PATH:-}" ]] && command -v python3 >/dev/null 2>&1; then
  for settings in "$HOME/.claude/settings.json" "$HOME/.claude/settings.local.json"; do
    [[ -f "$settings" ]] || continue
    val="$(python3 - "$settings" <<'PYEOF' 2>/dev/null || true
import json, sys
try:
    with open(sys.argv[1]) as f:
        s = json.load(f)
    for key in ("strata@strata", "strata@local", "strata"):
        opts = (s.get("pluginConfigs", {}).get(key) or {}).get("options") or {}
        v = opts.get("vault_path") or ""
        if v:
            print(v)
            break
except Exception:
    pass
PYEOF
)"
    if [[ -n "$val" ]]; then
      export STRATA_VAULT_PATH="$val"
      break
    fi
  done
fi

exec "$VENV/bin/python" "$@"

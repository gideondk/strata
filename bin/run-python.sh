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
_promote_option STRATA_VAULT_SYNC CLAUDE_PLUGIN_OPTION_VAULT_SYNC
_promote_option STRATA_GIT_REMOTE CLAUDE_PLUGIN_OPTION_GIT_REMOTE

# Last-resort: read settings.json — but ONLY when STRATA_VAULT_PATH is still
# unset after the above. That's the rare case (env or auto-export normally
# covers it), which matters because hooks route every tool call through this
# wrapper: gating on the always-empty optional vars (git_remote defaults to
# "") would spawn python3 on every single invocation. The other Strata
# options ride along in the same one parse.
if [[ -z "${STRATA_VAULT_PATH:-}" ]] && command -v python3 >/dev/null 2>&1; then
  for settings in "$HOME/.claude/settings.json" "$HOME/.claude/settings.local.json"; do
    [[ -f "$settings" ]] || continue
    # One `KEY=value` line per option. Values have newlines/CRs stripped in
    # python so a malformed settings value can never span lines, and the
    # shell assigns them verbatim — no eval, nothing re-parsed by bash.
    lines="$(python3 - "$settings" <<'PYEOF' 2>/dev/null || true
import json, sys
FIELDS = {
    "vault_path": "STRATA_VAULT_PATH",
    "repo_name": "STRATA_REPO_NAME",
    "vault_sync": "STRATA_VAULT_SYNC",
    "git_remote": "STRATA_GIT_REMOTE",
}
try:
    with open(sys.argv[1]) as f:
        s = json.load(f)
    for key in ("strata@strata", "strata@local", "strata"):
        opts = (s.get("pluginConfigs", {}).get(key) or {}).get("options") or {}
        if not opts:
            continue
        for field, var in FIELDS.items():
            v = opts.get(field)
            if v:
                clean = str(v).replace("\n", " ").replace("\r", " ").strip()
                print(f"{var}={clean}")
        break
except Exception:
    pass
PYEOF
)"
    if [[ -n "$lines" ]]; then
      while IFS= read -r line; do
        [[ "$line" != *=* ]] && continue
        var="${line%%=*}"
        val="${line#*=}"
        case "$var" in
          STRATA_VAULT_PATH|STRATA_REPO_NAME|STRATA_VAULT_SYNC|STRATA_GIT_REMOTE)
            # Only fill vars still empty — env / auto-export always win.
            [[ -z "${!var:-}" ]] && export "$var=$val"
            ;;
        esac
      done <<< "$lines"
      break
    fi
  done
fi

exec "$VENV/bin/python" "$@"

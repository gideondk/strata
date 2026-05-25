#!/usr/bin/env bash
# strata — bootstrap a private venv inside the plugin root.
# Idempotent. Picks the highest available Python >= 3.10 (mcp SDK requirement).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv"
REQ="$ROOT/requirements.txt"

if [[ -x "$VENV/bin/python" ]] && [[ -f "$VENV/.strata-installed" ]]; then
  exit 0
fi

# Pick the best Python >= 3.10. Prefer specific minor versions over `python3`
# because `python3` is often the system 3.9 on macOS.
PY=""
for candidate in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" - <<'PYCHK' >/dev/null 2>&1
import sys
sys.exit(0 if sys.version_info >= (3, 10) else 1)
PYCHK
    then
      PY="$candidate"
      break
    fi
  fi
done

if [[ -z "$PY" ]]; then
  echo "strata: need Python 3.10+ on PATH (mcp SDK requirement)" >&2
  echo "         install via: brew install python@3.13" >&2
  exit 1
fi

VER="$("$PY" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
echo "strata: using $PY (Python $VER)" >&2

if [[ ! -d "$VENV" ]]; then
  echo "strata: creating venv at $VENV" >&2
  "$PY" -m venv "$VENV"
fi

"$VENV/bin/python" -m pip install --quiet --disable-pip-version-check --upgrade pip >/dev/null
"$VENV/bin/python" -m pip install --quiet --disable-pip-version-check -r "$REQ"

touch "$VENV/.strata-installed"
echo "strata: deps installed in $VENV" >&2

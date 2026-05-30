---
name: strata:lint
disable-model-invocation: true
description: Scan vault or staged files for credentials, PII, and (opt-in) PHI via pluggable JSON presets. Use when the user says "check for secrets", "scan for credentials", "is this safe to save", or mentions an API key/token/password/patient data. Runs automatically as a pre-step inside /strata:save and /strata:decide, so secret-scanning never depends on a probabilistic skill pick.
---

# strata:lint

Pluggable scanner. Patterns live in `presets/*.json`, credentials by
Default, PII and region-specific PHI as opt-in presets. Add your own.

Even though the vault lives outside the repo and isn't usually committed,
it **is** sync'd to other team members, same blast radius. Lint before sync.

## When to use

- Periodically across the whole vault (`--scope vault`, the default).
- Before committing if you're export-promoting a decision into the host repo
  (`--scope staged`).
- As part of a `pre-push` git hook in the host repo (recommended — see
  `INSTALL.md`).

## How

The wrapper script handles the venv automatically, invoke via
`${CLAUDE_PLUGIN_ROOT}/bin/run-python.sh`:

```bash
# Default: scan the whole vault with the `secrets` preset
"${CLAUDE_PLUGIN_ROOT}/bin/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/memory-lint.py"

# Add region-specific PHI presets
"${CLAUDE_PLUGIN_ROOT}/bin/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/memory-lint.py" \
  --preset secrets,pii,phi-us

# Staged *.md files in the host repo
"${CLAUDE_PLUGIN_ROOT}/bin/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/memory-lint.py" \
  --scope staged --preset secrets,pii

# A specific file or directory
"${CLAUDE_PLUGIN_ROOT}/bin/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/memory-lint.py" \
  --scope ~/StrataVault/myrepo/pr-context/feat-x/

# Treat warnings as errors (CI mode)
"${CLAUDE_PLUGIN_ROOT}/bin/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/memory-lint.py" \
  --scope vault --preset secrets,pii --strict
```

Exit code 0 = clean, 1 = findings, 2 = misuse.

## Bundled presets

| Preset | Catches |
|---|---|
| `secrets` (default) | AWS, GitHub, Slack, OpenAI, Anthropic tokens, JWTs, PEM blocks, connection-string passwords, Azure account keys, GCP service-account markers |
| `pii` | Credit cards (Luhn-validated), client/user-id literal assignments, emails |
| `phi-uk` | NHS numbers (Mod-11 verified), UK postcodes (BS7666) |
| `phi-us` | SSN (with structural validation), DEA numbers (checksum-verified) |

All findings are BLOCK-level by default, they detect actual identifier
**values**, not vocabulary. The lint deliberately does **not** warn on words
Like "SSN", "NHS number", or "HIPAA" appearing in prose, because team memory
Notes will legitimately discuss systems that handle that data ("the SSN flow
Goes through service X", "we don't store NHS numbers in this table"). That's
the whole point of ADRs.

Use `--strict` in CI to fail on any warn-level finding from presets that have
Them (currently only `pii` does).

## Tuning / adding presets

Each preset is a JSON file in `presets/`:

```json
{
  "id": "my-org",
  "description": "Org-specific patterns",
  "block": [
    { "name": "internal-token", "regex": "MYORG-[A-Z0-9]{32}" }
  ],
  "warn": [
    { "name": "internal-host", "regex": "\\binternal\\.myorg\\.example\\b" }
  ]
}
```

Optional `flags` (`i`, `m`, `s`, case-insensitive, multi-line, dotall) and
`validator` (a function name from `VALIDATORS` in `memory-lint.py` —
currently `nhs_mod11`, `luhn`, `us_ssn`, `dea_checksum`).

Reference it via `--preset secrets,my-org`. PRs adding new region presets
Welcome.

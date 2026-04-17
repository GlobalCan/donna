#!/usr/bin/env bash
# entrypoint.sh — decrypt sops YAML secrets at startup, export as env, then exec the command.
#
# Expects:
#   $DONNA_SECRETS_FILE — path to the sops-encrypted YAML (default: /app/secrets/prod.enc.yaml)
#   $SOPS_AGE_KEY_FILE  — path to the age private key (default: /run/secrets/age.key)
#
# The YAML format is straightforward: top-level keys are env var names, values
# are their string values. Example decrypted content:
#
#   ANTHROPIC_API_KEY: sk-ant-xxx
#   DISCORD_BOT_TOKEN: mfa.xxx
#   DISCORD_ALLOWED_USER_ID: "123456789012345678"
#
# We parse with Python so we don't depend on yq / have to hand-roll YAML parsing.
set -euo pipefail

SECRETS_FILE="${DONNA_SECRETS_FILE:-/app/secrets/prod.enc.yaml}"
AGE_KEY_FILE="${SOPS_AGE_KEY_FILE:-/run/secrets/age.key}"

if [[ -f "$SECRETS_FILE" && -f "$AGE_KEY_FILE" ]]; then
    export SOPS_AGE_KEY_FILE="$AGE_KEY_FILE"
    # Decrypt → parse YAML → emit export statements → source them.
    # Keep plaintext entirely in a here-doc pipeline, never on disk.
    eval "$(
        sops -d "$SECRETS_FILE" 2>/dev/null | python -c '
import sys, yaml, shlex
try:
    data = yaml.safe_load(sys.stdin) or {}
except yaml.YAMLError as e:
    sys.stderr.write(f"[entrypoint] YAML parse error: {e}\n")
    sys.exit(0)
if not isinstance(data, dict):
    sys.stderr.write("[entrypoint] secrets YAML must be a top-level mapping\n")
    sys.exit(0)
for k, v in data.items():
    if not isinstance(k, str) or not k:
        continue
    # env names must be [A-Z_][A-Z0-9_]*
    import re
    if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", k):
        sys.stderr.write(f"[entrypoint] skipping non-env-var key: {k}\n")
        continue
    print(f"export {k}={shlex.quote(str(v))}")
'
    )"
    echo "[entrypoint] secrets decrypted from $SECRETS_FILE"
else
    echo "[entrypoint] no sops secrets at $SECRETS_FILE (or age key missing) — using env_file only"
fi

exec "$@"

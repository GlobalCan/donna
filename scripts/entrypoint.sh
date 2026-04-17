#!/usr/bin/env bash
# entrypoint.sh — decrypt sops secrets at startup, then exec the command
set -euo pipefail

SECRETS_FILE="${DONNA_SECRETS_FILE:-/app/secrets/prod.enc.yaml}"
AGE_KEY="${DONNA_AGE_KEY:-/run/secrets/age.key}"

if [[ -f "$SECRETS_FILE" && -f "$AGE_KEY" ]]; then
    export SOPS_AGE_KEY_FILE="$AGE_KEY"
    # Decrypt and export each KEY=VALUE pair into the environment
    while IFS= read -r line; do
        [[ -z "$line" || "$line" == \#* ]] && continue
        export "$line"
    done < <(sops -d "$SECRETS_FILE" 2>/dev/null | grep -E '^[A-Z_][A-Z0-9_]*=' || true)
    echo "[entrypoint] secrets decrypted from $SECRETS_FILE"
else
    echo "[entrypoint] no sops secrets found at $SECRETS_FILE — using env from env_file only"
fi

exec "$@"

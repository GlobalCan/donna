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
    # Decrypt → parse YAML → emit export statements → eval them.
    # Plaintext is captured into a shell variable (not disk) and eval'd.
    # Any failure in the pipeline (sops decrypt, YAML parse, zero keys)
    # aborts the container — better than silently starting with no secrets.
    if ! EXPORTS=$(sops -d "$SECRETS_FILE" | python -c '
import sys, yaml, shlex, re
try:
    data = yaml.safe_load(sys.stdin)
except yaml.YAMLError as e:
    sys.stderr.write(f"[entrypoint] YAML parse error: {e}\n")
    sys.exit(1)
if not isinstance(data, dict):
    sys.stderr.write(
        "[entrypoint] secrets must be a top-level YAML mapping (KEY: value), "
        "not dotenv (KEY=value)\n"
    )
    sys.exit(1)
count = 0
for k, v in data.items():
    if not isinstance(k, str) or not re.fullmatch(r"[A-Z_][A-Z0-9_]*", k):
        sys.stderr.write(f"[entrypoint] skipping non-env-var key: {k!r}\n")
        continue
    print(f"export {k}={shlex.quote(str(v))}")
    count += 1
if count == 0:
    sys.stderr.write("[entrypoint] no env-var keys found in decrypted secrets\n")
    sys.exit(1)
sys.stderr.write(f"[entrypoint] parsed {count} secret(s)\n")
'); then
        echo "[entrypoint] FATAL: secret decryption/parse failed — aborting" >&2
        exit 1
    fi
    eval "$EXPORTS"
    unset EXPORTS
    echo "[entrypoint] secrets loaded from $SECRETS_FILE"
else
    echo "[entrypoint] no sops secrets at $SECRETS_FILE (or age key missing) — using env_file only"
fi

# Apply pending alembic migrations before starting the service.
#
# Pre-fix (v0.4.2) this entrypoint just decrypted secrets and exec'd the
# command, so migrations sat unapplied silently after every deploy until
# an operator manually ran `alembic upgrade head`. Discovered 2026-04-30
# during the v0.4.3 deploy when migration 0006 didn't take effect after a
# routine `docker compose pull && up -d` — the new code shipped but the
# DB schema didn't match, leading to "I deployed but nothing changed"
# confusion.
#
# Only the bot/worker roles run migrations — botctl invocations and any
# other ad-hoc entrypoint use should not. Running for both bot AND worker
# is safe: alembic locks via SQLite, and the second one to enter sees
# "already at head" and no-ops in <1s.
#
# A migration failure here is fatal — better to crash the container with
# a visible error than to start the service against a stale schema.
if [[ "${DONNA_PROCESS_ROLE:-}" == "bot" || "${DONNA_PROCESS_ROLE:-}" == "worker" ]]; then
    echo "[entrypoint] applying pending migrations (alembic upgrade head)"
    if ! alembic upgrade head; then
        echo "[entrypoint] FATAL: alembic upgrade head failed — refusing to start" >&2
        exit 1
    fi
fi

exec "$@"
